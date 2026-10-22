"""
Capa 3 de la política grado médico: anclaje claim ↔ evidencia congelada.
========================================================================
Port horizontal de la capa que ya operaba en los forks (AESPLA-PRL, FIMABIS).
Cada control con su caso PERMITIDO y su caso BLOQUEADO, como exige el marco:
una capacidad sin caso bloqueado no está verificada.

Alcance declarado: verifica anclaje LITERAL de datos duros (valor+unidad,
dosis, porcentaje) y literalidad de citas textuales. No juzga veracidad
clínica ni equivalencia semántica: una frase sin datos duros ni citas pasa
por ausencia de material verificable, y el estado lo dice
(`sin_claims_duros`), que no es lo mismo que un PASS.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from core.backends.base import Citation, EvidenceChunk  # noqa: E402
from core.llm.base import LLMClient  # noqa: E402
from core.rag.engine import (  # noqa: E402
    UNGROUNDED_RESPONSE, LastRAGEngine,
)
from core.rag.failure_graph import FailureGraph, UNSUPPORTED_GENERATION  # noqa: E402
from core.rag.grounding import (  # noqa: E402
    find_fabricated_quotes, freeze_evidence, hard_tokens,
    strip_fabricated_quotes, verify_grounding,
)
from tests.doubles import FakeBackend, FakeLastIndex  # noqa: E402

EVIDENCIA = "La dosis inicial de metformina es 500 mg cada 12 horas; reduce la HbA1c un 1,2 %."


def _chunks(text: str = EVIDENCIA) -> list[EvidenceChunk]:
    return [EvidenceChunk(text=text, locator="blk_dosis", score=0.9,
                          citation=Citation(document="Guía DM2", section="3.2",
                                            page=43, block_id="blk_dosis"))]


# ============================================================
# 1 · Congelación: procedencia reproducible
# ============================================================

def test_congelacion_es_reproducible_y_sensible_al_contenido():
    a = freeze_evidence(_chunks())
    b = freeze_evidence(_chunks())
    c = freeze_evidence(_chunks("Otro fragmento distinto con 250 mg."))
    assert a.hash == b.hash, "mismos fragmentos ⇒ mismo hash (reproducible)"
    assert a.hash != c.hash, "distinta evidencia ⇒ distinto hash"
    assert a.fragments[0].sha256 and a.fragments[0].locator == "blk_dosis"


# ============================================================
# 2 · Datos duros: qué cuenta como afirmación verificable
# ============================================================

def test_dato_duro_requiere_unidad_no_un_numero_suelto():
    assert hard_tokens("La dosis es 500 mg cada 12 horas.") >= {"500 mg"}
    assert hard_tokens("Reduce la HbA1c un 1,2 %.") == {"1.2 %"}
    # Aparato de cita y años: procedencia, no afirmación clínica
    assert hard_tokens("Según la guía (p.42), el tratamiento es eficaz.") == set()
    assert hard_tokens("El estudio de 2024 incluyó pacientes adultos.") == set()
    assert hard_tokens("Es el tratamiento de primera línea [3].") == set()


def test_normalizacion_tolera_formato_pero_no_cambia_el_valor():
    freeze = freeze_evidence(_chunks())
    # mismo valor escrito distinto: anclado
    assert verify_grounding("Se administran 500mg al inicio.", freeze).grounded
    # valor distinto: NO anclado (la normalización no perdona cifras)
    assert not verify_grounding("Se administran 850 mg al inicio.", freeze).grounded


# ============================================================
# 3 · Anclaje: permitido vs bloqueado
# ============================================================

def test_permitido_respuesta_anclada_en_la_evidencia():
    freeze = freeze_evidence(_chunks())
    report = verify_grounding(
        "La dosis inicial es 500 mg cada 12 horas y reduce la HbA1c un 1,2 %.",
        freeze)
    assert report.grounded and report.state == "anclada"
    assert report.n_claims >= 1 and not report.unanchored


def test_bloqueado_dato_inventado_no_presente_en_la_evidencia():
    freeze = freeze_evidence(_chunks())
    report = verify_grounding("La dosis inicial es 850 mg cada 8 horas.", freeze)
    assert not report.grounded and report.state == "sin_anclaje"
    assert "850 mg" in report.unanchored[0]["missing"]


def test_estado_parcial_distingue_lo_anclado_de_lo_inventado():
    freeze = freeze_evidence(_chunks())
    report = verify_grounding(
        "La dosis inicial es 500 mg. El objetivo es bajar 3,5 % la HbA1c.",
        freeze)
    assert report.state == "parcial"
    assert len(report.anchored) == 1 and len(report.unanchored) == 1


def test_texto_sin_datos_duros_se_nombra_no_se_aprueba():
    freeze = freeze_evidence(_chunks())
    report = verify_grounding("La metformina es el tratamiento de primera línea.",
                              freeze)
    assert report.state == "sin_claims_duros", \
        "ausencia de material verificable NO es un PASS de anclaje"
    assert report.grounded is True  # no hay nada que contradiga la evidencia


# ============================================================
# 4 · Citas textuales fabricadas
# ============================================================

def test_bloqueado_cita_textual_que_no_consta_literalmente():
    freeze = freeze_evidence(_chunks())
    fabricadas = find_fabricated_quotes(
        'El documento dice «la dosis máxima es de 3 g diarios».', freeze)
    assert fabricadas, "una cita que no consta es fabricación, no paráfrasis"


def test_permitido_cita_textual_literal():
    freeze = freeze_evidence(_chunks())
    assert find_fabricated_quotes(
        'Dice «La dosis inicial de metformina es 500 mg cada 12 horas»', freeze) == []


def test_modo_declare_retira_la_cita_y_deja_marca():
    freeze = freeze_evidence(_chunks())
    texto, fabricadas = strip_fabricated_quotes(
        'Según la fuente «dato inventado de prueba largo».', freeze)
    assert fabricadas and "cita retirada" in texto
    assert "dato inventado" not in texto


# ============================================================
# 5 · Integración en el motor: la respuesta no anclada NO se entrega
# ============================================================

class _LLM(LLMClient):
    name = "fake-gen"

    def __init__(self, salida: str):
        self.salida = salida

    async def generate(self, prompt, *, max_tokens=8192):
        return "A" if "Pregunta de examen" in prompt else self.salida


def _run(salida: str, **kwargs) -> dict:
    engine = LastRAGEngine(FakeBackend(corpus=_chunks()), FakeLastIndex(),
                           _LLM(salida), failure_graph=FailureGraph(), **kwargs)
    out = asyncio.run(engine.run("dosis inicial de metformina"))
    out["_engine"] = engine
    return out


def test_motor_permitido_entrega_la_respuesta_anclada():
    out = _run("La dosis inicial es 500 mg cada 12 horas [1].")
    assert "500 mg" in out["response"]
    assert out["abstained"] is False
    assert out["features"]["grounding"]["state"] == "anclada"
    assert out["features"]["grounding"]["evidence_hash"]


def test_motor_bloqueado_retiene_la_respuesta_con_dato_inventado():
    out = _run("La dosis inicial es 850 mg cada 8 horas [1].")
    assert out["response"] == UNGROUNDED_RESPONSE
    assert "850 mg" not in out["response"], "el dato inventado no llega al usuario"
    assert out["abstained"] is True and out["confidence"] == 0.0
    assert out["features"]["abstention"]["kind"] == "ungrounded_blocked"
    declarado = [d for d in out["degradations"]
                 if d.get("reason") == "UNGROUNDED_CLAIMS_BLOCKED"]
    assert declarado and declarado[0]["unanchored"] >= 1
    assert out["_engine"].failure_graph.counts()[UNSUPPORTED_GENERATION] >= 1


def test_motor_bloqueado_por_cita_fabricada():
    out = _run('El documento afirma «texto que no consta en la evidencia».')
    assert out["response"] == UNGROUNDED_RESPONSE
    assert out["features"]["grounding"]["fabricated_quotes"] >= 1


def test_modo_declare_entrega_pero_declara_el_estado():
    out = _run("La dosis inicial es 850 mg cada 8 horas [1].", grounding="declare")
    assert out["response"] != UNGROUNDED_RESPONSE   # se entrega
    assert any(d.get("reason") == "UNGROUNDED_CLAIMS_DECLARED"
               for d in out["degradations"]), "entregar sin declarar sería silencioso"
    assert out["features"]["grounding"]["state"] == "sin_anclaje"


def test_modo_off_es_explicito_y_no_verifica():
    out = _run("La dosis inicial es 850 mg cada 8 horas [1].", grounding="off")
    assert "850 mg" in out["response"]
    assert "grounding" not in out["features"], \
        "sin verificación no se simula un informe de anclaje"


def test_politica_de_anclaje_desconocida_falla_al_construir():
    with pytest.raises(ValueError, match="grounding"):
        LastRAGEngine(FakeBackend(), FakeLastIndex(), _LLM("x"),
                      grounding="quizas")
