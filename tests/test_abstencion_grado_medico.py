"""
Política de abstención grado médico (decisión del PI, 22-oct-2026).
===================================================================
«Si no lo sabe, lo dice, antes de inventar.» La garantía de cero invención es
CÓDIGO en dos capas, y aquí se ejercitan el caso permitido y los bloqueados:

  Capa 1 · sin evidencia (local/grafo/externa) el LLM NI SE CONSULTA:
           abstención determinista.
  Capa 2 · si aun con evidencia el modelo responde «desde conocimiento
           general», esa salida se BLOQUEA y se sustituye por la abstención,
           declarándolo en degradations[] y en el failure graph.

Límite declarado: estas capas garantizan «sin evidencia no hay respuesta» y
«una salida auto-declarada como conocimiento general no se entrega». NO
verifican frase a frase la generación contra los spans (eso es trabajo futuro
del Evidence Pack); el claim «0 alucinaciones» a nivel de frase queda fuera
de lo acreditado por esta suite.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.llm.base import LLMClient  # noqa: E402
from core.rag.engine import (  # noqa: E402
    ABSTENTION_RESPONSE, LastRAGEngine,
)
from core.rag.failure_graph import (  # noqa: E402
    FailureGraph, NO_EVIDENCE, UNSUPPORTED_GENERATION,
)
from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM  # noqa: E402


class EmptyLastIndex(FakeLastIndex):
    async def structural_search(self, query, *, top_k=5):
        return []


class CountingLLM(LLMClient):
    """Cuenta llamadas; distingue grade (MCQ) de generación."""
    name = "counting"

    # La generación del doble debe ser una afirmación REAL respaldada por el
    # corpus de FakeBackend: la capa 4 verifica claims, también en las pruebas.
    def __init__(self, generation="La metformina es primera linea en DM2 (Guia DM2, p.42)."):
        self.generation = generation
        self.grade_calls = 0
        self.generation_calls = 0

    async def generate(self, prompt, *, max_tokens=8192):
        if "Pregunta de examen" in prompt:
            self.grade_calls += 1
            return "A"
        self.generation_calls += 1
        return self.generation


# ------------------------------------------------------------
# Caso permitido: con evidencia, el motor responde con normalidad
# ------------------------------------------------------------

def test_permitido_con_evidencia_responde_y_declara_politica():
    llm = CountingLLM()
    out = asyncio.run(LastRAGEngine(FakeBackend(), FakeLastIndex(), llm)
                      .run("tratamiento de la diabetes tipo 2"))
    assert out["abstained"] is False
    assert out["features"]["generation_policy"] == "abstain"
    assert llm.generation_calls == 1
    assert out["citations"] and out["confidence"] > 0


# ------------------------------------------------------------
# Capa 1 bloqueada: sin evidencia, el LLM ni se consulta
# ------------------------------------------------------------

def test_bloqueado_sin_evidencia_abstencion_sin_llamar_al_llm():
    llm = CountingLLM()
    engine = LastRAGEngine(FakeBackend(corpus=[]), EmptyLastIndex(), llm,
                           failure_graph=FailureGraph())
    out = asyncio.run(engine.run("tema sin evidencia en el corpus"))
    assert out["response"] == ABSTENTION_RESPONSE
    assert out["abstained"] is True
    assert out["confidence"] == 0.0
    assert out["is_general_knowledge"] is False
    assert out["features"]["abstention"]["kind"] == "no_evidence"
    assert llm.generation_calls == 0, \
        "sin evidencia la generación NO debe ejecutarse (garantía por código)"
    assert out["absence"]["type"] == NO_EVIDENCE  # taxonomía intacta


# ------------------------------------------------------------
# Capa 2 bloqueada: la salida "desde conocimiento general" no se entrega
# ------------------------------------------------------------

def test_bloqueado_salida_de_conocimiento_general_se_sustituye():
    tramposo = ("⚠️ **Aviso:** No se encontró evidencia en los documentos "
                "indexados. Esta respuesta se basa en conocimiento médico "
                "general. La dosis habitual es 500 mg.")
    llm = FakeLLM(response=tramposo)   # grade=A, generación intenta inventar
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), llm,
                           failure_graph=FailureGraph())
    out = asyncio.run(engine.run("tratamiento de la diabetes tipo 2"))
    assert out["response"] == ABSTENTION_RESPONSE
    assert "500 mg" not in out["response"]
    assert out["abstained"] is True and out["confidence"] == 0.0
    assert out["features"]["abstention"]["kind"] == "general_knowledge_blocked"
    assert any(d.get("reason") == "GENERAL_KNOWLEDGE_BLOCKED"
               for d in out["degradations"]), "el bloqueo queda declarado"
    assert engine.failure_graph.counts()[UNSUPPORTED_GENERATION] >= 1


def test_modelo_que_se_abstiene_queda_normalizado_a_confianza_cero():
    llm = FakeLLM(response=ABSTENTION_RESPONSE)  # siguió la instrucción 4
    out = asyncio.run(LastRAGEngine(FakeBackend(), FakeLastIndex(), llm)
                      .run("tratamiento de la diabetes tipo 2"))
    assert out["response"] == ABSTENTION_RESPONSE
    assert out["abstained"] is True and out["confidence"] == 0.0
    assert out["features"]["abstention"]["kind"] == "model_declared"


def test_rechazo_de_dominio_no_se_confunde_con_invencion():
    """Rehusar una consulta no médica no es inventar: no se bloquea."""
    rechazo = ("Lo siento, soy un asistente médico clínico. Mi base de datos "
               "y conocimientos están restringidos estrictamente al ámbito de "
               "la salud. No puedo responder a consultas sobre temas no médicos.")
    llm = FakeLLM(response=rechazo)
    out = asyncio.run(LastRAGEngine(FakeBackend(), FakeLastIndex(), llm)
                      .run("tratamiento de la diabetes tipo 2"))
    assert out["response"] == rechazo          # se entrega tal cual
    assert out["abstained"] is False
    assert out["confidence"] <= 0.15           # scorer honesto la capa igual


# ------------------------------------------------------------
# El gate causal también cuenta como abstención distinguible
# ------------------------------------------------------------

def test_abstencion_causal_visible_en_el_campo_abstained():
    from core.backends.base import EvidenceChunk
    corpus = [EvidenceChunk(
        text="Estudio observacional: el fármaco se asocia con menor riesgo.",
        locator="blk_obs", score=0.9)]
    out = asyncio.run(LastRAGEngine(FakeBackend(corpus), EmptyLastIndex(),
                                    FakeLLM(), build_pack=True)
                      .run("¿debo administrar el fármaco para reducir el riesgo?"))
    assert out["abstained"] is True
    assert out["features"]["abstention"]["kind"] == "causal_gate"


# ------------------------------------------------------------
# Legacy opt-in: solo si se pide, y siempre declarado
# ------------------------------------------------------------

def test_legacy_opt_in_conserva_el_aviso_declarado():
    aviso = ("⚠️ **Aviso:** No se encontró evidencia en los documentos "
             "indexados. Esta respuesta se basa en conocimiento médico general.")
    llm = FakeLLM(response=aviso)
    engine = LastRAGEngine(FakeBackend(corpus=[]), EmptyLastIndex(), llm,
                           allow_general_knowledge=True)
    out = asyncio.run(engine.run("tema sin evidencia"))
    assert out["features"]["generation_policy"] == "general_knowledge_declared"
    assert out["response"] == aviso            # comportamiento anterior
    assert out["is_general_knowledge"] is True
    assert out["confidence"] <= 0.10           # y capado, como siempre
    assert out["abstained"] is False


def test_el_prompt_por_defecto_no_invita_al_conocimiento_general():
    prompt = LastRAGEngine._prompt("q", "", "", "", "")
    assert "conocimiento médico general" not in prompt
    assert "⛔ **Abstención (grado médico)" in prompt
    legacy = LastRAGEngine._prompt("q", "", "", "", "",
                                   allow_general_knowledge=True)
    assert "conocimiento médico general" in legacy
