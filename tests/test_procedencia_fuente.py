"""
Capa 5 de la política grado médico: cualificación de la fuente.
===============================================================
Regla del PI (22-oct-2026): «esto sí se puede afirmar si se remite a una
evidencia trazable respaldada por un centro de evidencia científica, un paper
validado por pares y que a la fecha no haya sido refutado, o guías de práctica
clínica por asociación científica acreditada o respetable científicamente».

Cada condición de la regla con su caso PERMITIDO y su caso BLOQUEADO, y la
integración en el motor: `affirmable` solo es True cuando TODA la evidencia
que sostiene la respuesta cualifica. `UNKNOWN != PASS`: sin metadatos de
procedencia la respuesta se entrega declarada NO afirmable.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from core.backends.base import Citation, EvidenceChunk  # noqa: E402
from core.llm.base import LLMClient  # noqa: E402
from core.rag.engine import UNQUALIFIED_RESPONSE, LastRAGEngine  # noqa: E402
from core.rag.failure_graph import FailureGraph, UNSUPPORTED_GENERATION  # noqa: E402
from core.rag.provenance import (  # noqa: E402
    CLINICAL_GUIDELINE, EVIDENCE_CENTER, INTERNAL, NOT_AFFIRMABLE_FOOTER,
    PEER_REVIEWED, PREPRINT, SourceProvenance, assess, qualify,
)
from tests.doubles import FakeBackend, FakeLastIndex  # noqa: E402

HOY = date(2026, 10, 22)
RECIENTE = (HOY - timedelta(days=10)).isoformat()
CADUCADA = (HOY - timedelta(days=400)).isoformat()


def _q(**meta):
    return qualify(SourceProvenance.from_dict(meta), today=HOY)


# ============================================================
# 1 · La regla, condición a condición
# ============================================================

def test_permitido_paper_revisado_no_refutado_comprobado():
    q = _q(tier=PEER_REVIEWED, retraction_status="none", retraction_checked_at=RECIENTE,
           identifier="10.1000/xyz")
    assert q.qualified and q.reason == "QUALIFIED:peer_reviewed"
    assert q.check_age_days == 10


def test_permitido_guia_de_asociacion_acreditada_y_centro_de_evidencia():
    assert _q(tier=CLINICAL_GUIDELINE, accredited=True, retraction_status="none",
              retraction_checked_at=RECIENTE).qualified
    assert _q(tier=EVIDENCE_CENTER, publisher="Cochrane", retraction_status="none",
              retraction_checked_at=RECIENTE).qualified


def test_bloqueado_retractada_manda_sobre_todo_y_contamina():
    q = _q(tier=PEER_REVIEWED, retraction_status="retracted", retraction_checked_at=RECIENTE)
    assert not q.qualified and q.blocking and q.reason.startswith("RETRACTED")
    c = _q(tier=EVIDENCE_CENTER, retraction_status="concern", retraction_checked_at=RECIENTE)
    assert c.blocking and c.reason.startswith("CONCERN")


def test_bloqueado_niveles_no_cualificados_y_guia_no_acreditada():
    for tier in (PREPRINT, INTERNAL, "web", "grey_literature"):
        q = _q(tier=tier, retraction_status="none", retraction_checked_at=RECIENTE)
        assert not q.qualified and q.reason == f"UNQUALIFIED_TIER:{tier}"
        assert not q.blocking, "no cualificar no es lo mismo que estar refutada"
    assert _q(tier=CLINICAL_GUIDELINE, accredited=False, retraction_status="none",
              retraction_checked_at=RECIENTE).reason.startswith("GUIDELINE_NOT_ACCREDITED")
    assert _q(tier=CLINICAL_GUIDELINE, retraction_status="none",
              retraction_checked_at=RECIENTE).reason == "GUIDELINE_ACCREDITATION_UNKNOWN"


def test_bloqueado_a_la_fecha_exige_comprobacion_con_fecha_y_vigente():
    """«Que a la fecha no haya sido refutado» no es una creencia: es una
    comprobación fechada. Sin fecha, caducada o sin hacer => no afirmable."""
    assert _q(tier=PEER_REVIEWED, retraction_status="none").reason.startswith(
        "RETRACTION_CHECK_UNDATED")
    assert _q(tier=PEER_REVIEWED, retraction_status="none",
              retraction_checked_at=CADUCADA).reason.startswith("RETRACTION_CHECK_STALE")
    assert _q(tier=PEER_REVIEWED, retraction_status="unknown",
              retraction_checked_at=RECIENTE).reason.startswith("RETRACTION_UNCHECKED")
    assert _q(tier=PEER_REVIEWED, retraction_status="none",
              retraction_checked_at="2099-01-01").reason.startswith("RETRACTION_CHECK_IN_FUTURE")


def test_procedencia_desconocida_no_es_pass():
    q = _q()
    assert not q.qualified and q.tier == "unknown" and q.reason.startswith("UNKNOWN_TIER")
    assert not q.blocking


def test_assess_resuelve_por_locator_block_id_o_documento():
    chunks = [
        EvidenceChunk(text="a", locator="blk_1",
                      citation=Citation(document="Guía ESC 2024", block_id="blk_1")),
        EvidenceChunk(text="b", locator="blk_2",
                      citation=Citation(document="Preprint X", block_id="blk_2")),
        EvidenceChunk(text="c", locator="blk_3"),
    ]
    meta = {"Guía ESC 2024": {"tier": CLINICAL_GUIDELINE, "accredited": True,
                              "retraction_status": "none", "retraction_checked_at": RECIENTE},
            "blk_2": {"tier": PREPRINT, "retraction_status": "none",
                      "retraction_checked_at": RECIENTE}}
    a = assess(chunks, meta, today=HOY)
    assert a.qualified == ["blk_1"] and a.unqualified_known == ["blk_2"] and a.unknown == ["blk_3"]
    assert not a.affirmable


# ============================================================
# 2 · Integración en el motor
# ============================================================

EV = [
    "La metformina es el tratamiento de primera línea en la diabetes tipo 2 y reduce la hemoglobina glucosilada.",
    "Está contraindicada en insuficiencia renal grave por el riesgo de acidosis láctica.",
]
RESPUESTA = ("La metformina es el tratamiento de primera línea en la diabetes tipo 2. "
             "Está contraindicada en insuficiencia renal grave.")


class _GenLLM(LLMClient):
    name = "gen"

    def __init__(self, salida: str = RESPUESTA):
        self.salida = salida

    async def generate(self, prompt, *, max_tokens=8192):
        return "A" if "Pregunta de examen" in prompt else self.salida


def _corpus(docs=("Guía DM2", "Guía DM2")):
    return [EvidenceChunk(text=t, locator=f"blk_{i}", score=0.9,
                          citation=Citation(document=docs[i], page=i + 1, block_id=f"blk_{i}"))
            for i, t in enumerate(EV)]


def _run(source_meta=None, salida=RESPUESTA, corpus=None, **kwargs):
    engine = LastRAGEngine(FakeBackend(corpus=corpus or _corpus()), FakeLastIndex(),
                           _GenLLM(salida), failure_graph=FailureGraph(),
                           source_meta=source_meta, **kwargs)
    out = asyncio.run(engine.run("tratamiento de la diabetes tipo 2"))
    out["_engine"] = engine
    return out


META_GPC = {"Guía DM2": {"tier": CLINICAL_GUIDELINE, "accredited": True,
                         "publisher": "SED", "retraction_status": "none",
                         "retraction_checked_at": RECIENTE}}


def test_motor_permitido_fuente_cualificada_es_afirmable():
    out = _run(META_GPC)
    assert out["affirmable"] is True and out["abstained"] is False
    assert NOT_AFFIRMABLE_FOOTER not in out["response"]
    assert out["features"]["provenance"]["affirmable"] is True
    assert out["confidence"] > 0.5


def test_motor_sin_metadatos_entrega_declarado_no_afirmable():
    out = _run(None)
    assert out["affirmable"] is False and out["abstained"] is False
    assert "primera línea" in out["response"], "se entrega"
    assert NOT_AFFIRMABLE_FOOTER in out["response"], "y lo dice"
    assert out["confidence"] <= 0.5
    assert any(d.get("reason") == "SOURCE_NOT_QUALIFIED" for d in out["degradations"])


def test_motor_bloqueado_fuente_retractada_retiene_la_respuesta():
    meta = {"Guía DM2": {"tier": PEER_REVIEWED, "retraction_status": "retracted",
                         "retraction_checked_at": RECIENTE}}
    out = _run(meta)
    assert out["response"] == UNQUALIFIED_RESPONSE
    assert out["abstained"] is True and out["affirmable"] is False and out["confidence"] == 0.0
    assert out["features"]["abstention"]["kind"] == "source_retracted_blocked"
    assert any(d.get("reason") == "SOURCE_RETRACTED_BLOCKED" for d in out["degradations"])
    assert out["_engine"].failure_graph.counts()[UNSUPPORTED_GENERATION] >= 1


def test_motor_retira_la_frase_que_solo_sostiene_un_preprint():
    corpus = _corpus(docs=("Guía DM2", "Preprint 2026"))
    meta = {**META_GPC,
            "Preprint 2026": {"tier": PREPRINT, "retraction_status": "none",
                              "retraction_checked_at": RECIENTE}}
    out = _run(meta, corpus=corpus)
    assert "primera línea" in out["response"], "lo sostenido por la GPC se entrega"
    assert "insuficiencia renal" not in out["response"], \
        "lo sostenido solo por el preprint se retira"
    assert "fuente no cualificada" in out["response"]
    assert out["affirmable"] is False
    d = [x for x in out["degradations"] if x.get("reason") == "UNQUALIFIED_SOURCE_CLAIMS_REDACTED"]
    assert d and d[0]["redacted"] == 1


def test_modo_strict_retiene_tambien_la_procedencia_desconocida():
    out = _run(None, source_policy="strict")
    assert out["response"] == UNQUALIFIED_RESPONSE
    assert out["features"]["abstention"]["kind"] == "source_unqualified_blocked"


def test_modo_declare_entrega_integro_y_declara():
    out = _run(None, source_policy="declare")
    assert NOT_AFFIRMABLE_FOOTER not in out["response"]
    assert out["affirmable"] is False
    assert any(d.get("reason") == "SOURCE_NOT_QUALIFIED_DECLARED" for d in out["degradations"])


def test_modo_off_explicito_no_evalua_y_nunca_afirma():
    out = _run(META_GPC, source_policy="off")
    assert "provenance" not in out["features"]
    assert out["affirmable"] is False, "sin evaluar la procedencia no se afirma"


def test_comprobacion_caducada_deja_de_ser_afirmable():
    meta = {"Guía DM2": {**META_GPC["Guía DM2"], "retraction_checked_at": CADUCADA}}
    out = _run(meta, max_check_age_days=180)
    assert out["affirmable"] is False
    frag = out["features"]["provenance"]["fragments"]["blk_0"]
    assert frag["reason"].startswith("RETRACTION_CHECK_STALE")


def test_politica_de_procedencia_desconocida_falla_al_construir():
    with pytest.raises(ValueError, match="source_policy"):
        LastRAGEngine(FakeBackend(), FakeLastIndex(), _GenLLM(), source_policy="confiar")
