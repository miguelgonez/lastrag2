"""
Capa 4 de la política grado médico: verificador claim ↔ evidencia.
==================================================================
Cierra el hueco que la capa 3 declaraba: las afirmaciones PARAFRASEADAS, sin
cifras ni comillas. Cada método (léxico, semántico, juez) y cada decisión del
motor con su caso PERMITIDO y su caso BLOQUEADO.

Métrica de grado médico sobre el banco sintético con ground truth:
  · fugas = 0  (ningún claim inventado o contradicho pasa como respaldado)
  · falsos bloqueos: se MIDEN y se declaran, no se ocultan.

Alcance declarado: el juez se ejercita contra un servidor OpenAI-compatible
REAL en proceso (no contra ALIA); el método semántico contra un embedder
inyectado determinista. La calidad con ALIA real y con FastEmbed multilingüe
queda UNKNOWN hasta ejecutarse en el Spark / con el modelo descargado.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from core.backends.base import Citation, EvidenceChunk  # noqa: E402
from core.llm.base import LLMClient, LocalLLM  # noqa: E402
from core.rag.engine import UNVERIFIED_RESPONSE, LastRAGEngine  # noqa: E402
from core.rag.failure_graph import FailureGraph, UNSUPPORTED_GENERATION  # noqa: E402
from core.rag.grounding import freeze_evidence  # noqa: E402
from core.rag.verifier import (  # noqa: E402
    CONTRADICTED, META, REDACTION_MARK, SUPPORTED, UNSUPPORTED,
    ClaimVerifier, is_meta, redact, run_verifier_benchmark,
)
from tests.doubles import FakeBackend, FakeLastIndex  # noqa: E402

EV = [
    "La metformina es el tratamiento de primera línea en la diabetes tipo 2 y reduce la hemoglobina glucosilada.",
    "La dosis inicial recomendada es de 500 mg cada 12 horas con las comidas.",
    "Está contraindicada en insuficiencia renal grave por el riesgo de acidosis láctica.",
]


def _freeze(texts=EV):
    return freeze_evidence([EvidenceChunk(text=t, locator=f"blk_{i}", score=1.0,
                                          citation=Citation(document="Guía DM2", page=i + 1))
                            for i, t in enumerate(texts)])


def _verify(answer: str, verifier: ClaimVerifier | None = None, texts=EV):
    return asyncio.run((verifier or ClaimVerifier()).verify(answer, _freeze(texts)))


# ============================================================
# 1 · Banco sintético con ground truth: 0 fugas, falsos bloqueos medidos
# ============================================================

def test_banco_sintetico_sin_fugas_con_metodo_lexico():
    r = asyncio.run(run_verifier_benchmark(ClaimVerifier()))
    assert r["fugas"] == 0, [c for c in r["cases"] if c["leak"]]
    # Coste del fail-closed sin modelo semántico: las dos paráfrasis fuertes.
    assert r["falsos_bloqueos"] == 2, r["falsos_bloqueos_sobre_respaldados"]
    assert r["exact"] == r["n"] - 2
    assert r["methods"]["semantic"] == "unavailable" and r["methods"]["judge"] == "unavailable"


# ============================================================
# 2 · Método léxico: permitido / bloqueado / contradicción / polaridad
# ============================================================

def test_lexico_permitido_parafrasis_leve_con_span():
    rep = _verify("En la diabetes tipo 2 la metformina se considera de primera línea.")
    c = rep.claims[0]
    assert c.verdict == SUPPORTED and c.method == "lexical"
    assert c.span["locator"] == "blk_0" and "primera línea" in c.span["sentence"]


def test_lexico_bloqueado_afirmacion_inventada():
    rep = _verify("La metformina mejora la función hepática en todos los pacientes.")
    assert rep.claims[0].verdict == UNSUPPORTED
    assert rep.state == "unsupported"


def test_lexico_contradiccion_por_direccion_opuesta():
    rep = _verify("La metformina aumenta la hemoglobina glucosilada en la diabetes tipo 2.")
    c = rep.claims[0]
    assert c.verdict == CONTRADICTED and "direction_opposite" in c.flags
    assert rep.state == "contradicted"


def test_lexico_polaridad_distinta_no_se_da_por_respaldada():
    rep = _verify("La metformina no es el tratamiento de primera línea en la diabetes tipo 2.")
    c = rep.claims[0]
    assert c.verdict == UNSUPPORTED and "polarity_mismatch" in c.flags
    assert c.lexical >= 0.9, "solapamiento alto no basta si la polaridad difiere"


def test_meta_no_cuenta_ni_se_retira():
    assert is_meta("A continuación se resume la evidencia disponible.")
    assert is_meta("¿Cuál es la dosis?")
    assert is_meta("- Guía DM2 · 3.2 Dosificación · p.43")
    assert not is_meta("La metformina reduce la hemoglobina glucosilada.")
    rep = _verify("A continuación se resume la evidencia disponible sobre el caso.\n"
                  "La metformina es el tratamiento de primera línea en la diabetes tipo 2.")
    assert [c.verdict for c in rep.claims] == [META, SUPPORTED]
    assert rep.state == "supported"


# ============================================================
# 3 · Método semántico (embedder inyectado): nunca decide solo
# ============================================================

class _SynonymEmbedder:
    """Embedder determinista: proyecta sinónimos declarados al mismo eje para
    ejercitar el camino semántico sin modelo descargado."""
    model_id = "fake-synonyms-v1"
    _SYN = {"farmaco": "metformina", "opcion": "tratamiento", "inicial": "primera",
            "preferente": "linea", "diabeticos": "diabetes"}

    def __call__(self, texts):
        from core.rag.verifier import content_terms
        vocab: list[str] = []
        bags = []
        for t in texts:
            terms = {self._SYN.get(w, w) for w in content_terms(t)}
            bags.append(terms)
            for w in terms:
                if w not in vocab:
                    vocab.append(w)
        return [[1.0 if w in bag else 0.0 for w in vocab] for bag in bags]


def test_semantico_rescata_parafrasis_con_minimo_lexico():
    v = ClaimVerifier(embedder=_SynonymEmbedder(), semantic_threshold=0.5,
                      semantic_min_lexical=0.2)
    rep = _verify("El farmaco es la opcion inicial preferente para diabeticos.", v)
    c = rep.claims[0]
    assert c.lexical < v.lexical_threshold, "el léxico solo no lo rescata"
    assert c.verdict == SUPPORTED and c.method == "semantic+lexical"
    assert rep.methods["semantic"] == "applied:fake-synonyms-v1"


def test_semantico_no_rescata_sin_minimo_lexico():
    v = ClaimVerifier(embedder=_SynonymEmbedder(), semantic_threshold=0.5,
                      semantic_min_lexical=0.5)
    rep = _verify("El farmaco es la opcion preferente para diabeticos.", v)
    assert rep.claims[0].verdict == UNSUPPORTED, \
        "similitud no es implicación: sin solapamiento mínimo no decide"


def test_semantico_no_anula_una_contradiccion():
    v = ClaimVerifier(embedder=_SynonymEmbedder(), semantic_threshold=0.1,
                      semantic_min_lexical=0.0)
    rep = _verify("La metformina aumenta la hemoglobina glucosilada en la diabetes tipo 2.", v)
    assert rep.claims[0].verdict == CONTRADICTED


# ============================================================
# 4 · Juez (LLM soberano) contra servidor OpenAI-compatible REAL en proceso
# ============================================================

class _JudgeServer:
    """Responde A/B/C según el contenido del claim; programable para fallar."""

    def __init__(self, *, answer_for=None, status: int = 200):
        self.calls: list[str] = []
        self.answer_for = answer_for or (lambda claim: "C")
        self.status = status
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._send(200, {"data": [{"id": "alia-test", "object": "model"}]})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                prompt = body["messages"][0]["content"]
                outer.calls.append(prompt)
                if outer.status != 200:
                    self._send(outer.status, {"error": "boom"})
                    return
                claim = prompt.split('Afirmación: "', 1)[1].split('"', 1)[0]
                self._send(200, {"choices": [{"message": {"content": outer.answer_for(claim)}}]})

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _judge_rule(claim: str) -> str:
    low = claim.lower()
    if "aumenta" in low:
        return "B"
    if " no " in f" {low} ":
        return "C"                 # el juez simulado no sabe de negaciones: decide el código
    if "preferente" in low or "primera línea" in low or "filtrado" in low:
        return "**A)**"            # con adorno: debe normalizarse
    if "duplica" in low:
        return "no sabría decir"   # ilegible: fail-closed
    return "C"


def test_juez_rescata_parafrasis_fuerte_y_devuelve_span():
    srv = _JudgeServer(answer_for=_judge_rule).start()
    try:
        v = ClaimVerifier(judge=LocalLLM(srv.endpoint, model="alia-test", max_retries=0))
        rep = _verify("Debe evitarse cuando el filtrado glomerular está gravemente disminuido.", v)
        c = rep.claims[0]
        assert c.verdict == SUPPORTED and c.method == "judge" and c.judge == "A"
        assert c.span and c.span["locator"].startswith("blk_")
        assert rep.methods["judge"] == "applied"
        assert srv.calls, "el juez se invocó de verdad por HTTP"
    finally:
        srv.stop()


def test_juez_contradiccion_y_fail_closed_en_c_e_ilegible():
    srv = _JudgeServer(answer_for=_judge_rule).start()
    try:
        v = ClaimVerifier(judge=LocalLLM(srv.endpoint, model="alia-test", max_retries=0))
        rep = _verify(
            "La metformina aumenta la hemoglobina glucosilada. "
            "La metformina mejora la función hepática en todos los pacientes. "
            "La sitagliptina combinada duplica la eficacia glucémica.", v)
        verdicts = {c.sentence[:25]: (c.verdict, c.judge) for c in rep.claims}
        assert verdicts["La metformina aumenta la "] == (CONTRADICTED, "B")
        assert verdicts["La metformina mejora la f"] == (UNSUPPORTED, "C")
        assert verdicts["La sitagliptina combinada"] == (UNSUPPORTED, "UNPARSEABLE")
        assert any("judge_unparseable" in c.flags for c in rep.claims)
    finally:
        srv.stop()


def test_juez_caido_se_declara_y_cae_al_metodo_de_codigo():
    srv = _JudgeServer(status=500).start()
    try:
        v = ClaimVerifier(judge=LocalLLM(srv.endpoint, model="alia-test",
                                         max_retries=0, backoff=0.01))
        rep = _verify("La metformina es el tratamiento de primera línea en la diabetes tipo 2.", v)
        assert rep.methods["judge"].startswith("unavailable:ERROR:")
        assert rep.claims[0].verdict == SUPPORTED and rep.claims[0].method == "lexical"
    finally:
        srv.stop()


def test_banco_sintetico_con_juez_cierra_los_falsos_bloqueos():
    """Con el juez (aquí simulado por reglas) las paráfrasis fuertes se
    recuperan sin abrir ninguna fuga."""
    srv = _JudgeServer(answer_for=_judge_rule).start()
    try:
        v = ClaimVerifier(judge=LocalLLM(srv.endpoint, model="alia-test", max_retries=0))
        r = asyncio.run(run_verifier_benchmark(v))
        assert r["fugas"] == 0
        assert r["falsos_bloqueos"] == 0, r["falsos_bloqueos_sobre_respaldados"]
    finally:
        srv.stop()


# ============================================================
# 5 · Integración en el motor: retirada parcial, retención, modos
# ============================================================

class _GenLLM(LLMClient):
    name = "gen"

    def __init__(self, salida: str):
        self.salida = salida
        self.prompts: list[str] = []

    async def generate(self, prompt, *, max_tokens=8192):
        self.prompts.append(prompt)
        if "¿El FRAGMENTO respalda" in prompt:
            return "A"                      # juez permisivo (sólo para contar llamadas)
        return "A" if "Pregunta de examen" in prompt else self.salida


def _run(salida: str, **kwargs) -> dict:
    corpus = [EvidenceChunk(text=t, locator=f"blk_{i}", score=0.9,
                            citation=Citation(document="Guía DM2", page=i + 1))
              for i, t in enumerate(EV)]
    llm = _GenLLM(salida)
    engine = LastRAGEngine(FakeBackend(corpus=corpus), FakeLastIndex(), llm,
                           failure_graph=FailureGraph(), **kwargs)
    out = asyncio.run(engine.run("tratamiento de la diabetes tipo 2"))
    out["_engine"], out["_llm"] = engine, llm
    return out


def test_motor_permitido_respuesta_respaldada_integra():
    out = _run("La metformina es el tratamiento de primera línea en la diabetes tipo 2. "
               "Está contraindicada en insuficiencia renal grave.")
    assert out["abstained"] is False
    assert REDACTION_MARK not in out["response"]
    assert out["features"]["verification"]["state"] == "supported"
    assert out["features"]["verification"]["evidence_hash"] == \
        out["features"]["grounding"]["evidence_hash"], "misma congelación en capas 3 y 4"


def test_motor_retira_la_frase_inventada_y_entrega_el_resto():
    out = _run("La metformina es el tratamiento de primera línea en la diabetes tipo 2. "
               "Además mejora la función hepática en todos los pacientes.")
    assert "primera línea" in out["response"]
    assert "función hepática" not in out["response"], "lo inventado no llega al usuario"
    assert REDACTION_MARK in out["response"]
    assert out["abstained"] is False
    d = [x for x in out["degradations"] if x.get("reason") == "UNSUPPORTED_CLAIMS_REDACTED"]
    assert d and d[0]["redacted"] == 1
    assert out["confidence"] <= 0.5, "la confianza se capa por la proporción respaldada"
    assert out["_engine"].failure_graph.counts()[UNSUPPORTED_GENERATION] >= 1


def test_motor_retiene_la_respuesta_si_contradice_la_evidencia():
    out = _run("La metformina es el tratamiento de primera línea en la diabetes tipo 2. "
               "La metformina aumenta la hemoglobina glucosilada.")
    assert out["response"] == UNVERIFIED_RESPONSE
    assert out["abstained"] is True and out["confidence"] == 0.0
    assert out["features"]["abstention"]["kind"] == "contradicted_blocked"
    assert any(x.get("reason") == "CLAIMS_CONTRADICTED_BLOCKED" for x in out["degradations"])


def test_motor_retiene_si_nada_queda_respaldado():
    out = _run("La metformina mejora la función hepática en todos los pacientes. "
               "Los ensayos de 2023 demostraron beneficio cardiovascular.")
    assert out["response"] == UNVERIFIED_RESPONSE
    assert out["features"]["abstention"]["kind"] == "unsupported_blocked"


def test_modo_declare_entrega_integro_pero_declara():
    out = _run("La metformina es el tratamiento de primera línea en la diabetes tipo 2. "
               "Además mejora la función hepática en todos los pacientes.",
               verification="declare")
    assert "función hepática" in out["response"]
    assert any(x.get("reason") == "UNSUPPORTED_CLAIMS_DECLARED" for x in out["degradations"])
    assert out["features"]["verification"]["unsupported"] == 1


def test_modo_off_explicito_no_verifica_ni_simula():
    out = _run("Además mejora la función hepática en todos los pacientes.",
               verification="off")
    assert "función hepática" in out["response"]
    assert "verification" not in out["features"]


def test_juez_del_motor_usa_el_llm_soberano_cuando_se_activa():
    out = _run("La metformina es el tratamiento de primera línea en la diabetes tipo 2.",
               verification_judge=True)
    assert any("¿El FRAGMENTO respalda" in p for p in out["_llm"].prompts)
    assert out["features"]["verification"]["methods"]["judge"] == "applied"
    assert out["features"]["verification"]["claims"][0]["method"] == "judge"


def test_politica_de_verificacion_desconocida_falla_al_construir():
    with pytest.raises(ValueError, match="verification"):
        LastRAGEngine(FakeBackend(), FakeLastIndex(), _GenLLM("x"), verification="tal vez")


def test_redact_deja_marca_y_cuenta():
    rep = _verify("La metformina es el tratamiento de primera línea en la diabetes tipo 2. "
                  "Cura la diabetes en tres semanas en todos los casos.")
    texto, n = redact("La metformina es el tratamiento de primera línea en la diabetes tipo 2. "
                      "Cura la diabetes en tres semanas en todos los casos.", rep)
    assert n == 1 and REDACTION_MARK in texto and "tres semanas" not in texto
