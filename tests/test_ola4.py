"""Ola 4 — CB-8 (Causal RAG + CausalGate) y CB-14 (validación sintética con
ground truth: mediador/confusor/colisionador). Caso permitido + bloqueado."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.backends.base import EvidenceChunk
from core.rag.engine import LastRAGEngine
from core.rag.causal import (
    ASSOCIATION, CAUSAL_CANDIDATE, CAUSAL_SUPPORTED, MECHANISTIC, TEMPORAL,
    CausalGate, classify_claim, run_causal_benchmark, synthetic_causal_scenarios,
)
from core.rag.pack import extract_claims
from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM


# ---------------- CB-8: jerarquía + gate ----------------

def test_cb8_classify_levels_permitted():
    assert classify_claim(
        "Ensayo aleatorizado doble ciego: la metformina reduce la HbA1c."
    ) == CAUSAL_SUPPORTED
    assert classify_claim(
        "Se diseñó un ensayo aleatorizado con grupo control y placebo."
    ) == CAUSAL_CANDIDATE
    assert classify_claim(
        "El alquitran media la vía entre tabaco y daño celular."
    ) == MECHANISTIC
    assert classify_claim(
        "Estudio longitudinal con seguimiento a diez años."
    ) == TEMPORAL
    assert classify_claim(
        "Estudio observacional: la anemia se asocia con mayor mortalidad."
    ) == ASSOCIATION


def test_cb8_gate_abstains_on_recommendation_with_association_blocked():
    """El caso dedos amarillos: recomendación sobre evidencia observacional
    → ABSTENCIÓN con reason. Es la frontera correlación→recomendación."""
    claims = extract_claims([
        EvidenceChunk(text="Estudio observacional: los dedos amarillos se "
                           "asocian con mayor prevalencia de cáncer de pulmón.",
                      locator="synth_confusor_0"),
    ])
    verdict = CausalGate().check(
        "¿Debo limpiar los dedos para reducir el riesgo de cáncer?", claims)
    assert verdict.allowed is False
    assert "CAUSAL_GATE" in verdict.reason
    assert verdict.abstention  # el texto de abstención existe y se explica


def test_cb8_gate_allows_rct_backed_recommendation_permitted():
    claims = extract_claims([
        EvidenceChunk(text="Ensayo aleatorizado: la metformina reduce la "
                           "mortalidad frente a placebo.",
                      locator="synth_rct_0"),
    ])
    verdict = CausalGate().check("¿Debo administrar metformina?", claims)
    assert verdict.allowed is True
    assert verdict.best_level == CAUSAL_SUPPORTED


def test_cb8_gate_no_opinion_on_descriptive_queries_blocked():
    """Consulta NO recomendativa: el gate no secuestra la respuesta."""
    claims = extract_claims([
        EvidenceChunk(text="La anemia se asocia con mayor mortalidad "
                           "observacional.", locator="x"),
    ])
    verdict = CausalGate().check(
        "¿Qué factores se asocian con mortalidad?", claims)
    assert verdict.allowed is True


def test_cb8_engine_causal_abstention_end_to_end_blocked():
    """E2E: engine con build_pack; recomendación con evidencia observacional
    → respuesta = abstención determinista, confianza 0.05, sin LLM bribón."""
    llm = FakeLLM(response="¡Sí, adminístrelo sin dudar!")
    backend = FakeBackend(corpus=[
        EvidenceChunk(text="Estudio observacional: el fármaco X se asocia con "
                           "mejoría en observaciones.", locator="blk_obs"),
    ])
    engine = LastRAGEngine(backend, FakeLastIndex(), llm, build_pack=True)
    result = asyncio.run(engine.run(
        "¿Debo administrar el fármaco X como tratamiento?"))
    assert "Abstención causal" in result["response"]
    assert result["confidence"] <= 0.05
    assert result["features"]["causal_gate"]["allowed"] is False


def test_cb8_engine_allows_intervention_evidence_permitted():
    llm = FakeLLM()
    backend = FakeBackend(corpus=[
        EvidenceChunk(text="Ensayo aleatorizado doble ciego: la metformina "
                           "reduce la HbA1c frente a placebo.", locator="blk_rct"),
    ])
    engine = LastRAGEngine(backend, FakeLastIndex(), llm, build_pack=True)
    result = asyncio.run(engine.run(
        "¿Debo administrar metformina en DM2?"))
    assert "Abstención causal" not in result["response"]
    assert result["features"]["causal_gate"]["allowed"] is True


# ---------------- CB-14: validación sintética (laboratorio OMEGA-style) ----

def test_cb14_scenarios_have_ground_truth_declared():
    for sc in synthetic_causal_scenarios():
        assert sc.ground_truth, f"{sc.name}: sin ground truth declarado"


def test_cb14_benchmark_blocked_scenarios_abstain():
    """Los tres sesgos causales clásicos DEBEN abstenerse (caso bloqueado:
    el sistema declina la trampa de la asociación espuria)."""
    results = run_causal_benchmark()
    by_name = {r["scenario"]: r for r in results}
    for name in ("confusor", "mediador", "colisionador"):
        assert by_name[name]["actual"] == "ABSTAIN", \
            f"{name}: esperaba ABSTAIN, obtuvo {by_name[name]['actual']}"


def test_cb14_benchmark_permitted_scenarios_allow():
    results = run_causal_benchmark()
    by_name = {r["scenario"]: r for r in results}
    assert by_name["causa_real"]["actual"] == "ALLOW"
    assert by_name["consulta_descriptiva"]["actual"] == "ALLOW"


def test_cb14_benchmark_all_pass_with_receipts():
    results = run_causal_benchmark()
    failed = [r for r in results if not r["pass"]]
    assert not failed, f"escenarios fallidos: {failed}"
    # cada resultado lleva esperado/real/veredicto/ground truth (recibo)
    for r in results:
        assert {"scenario", "expected", "actual", "pass", "ground_truth",
                "reason"} <= set(r)
