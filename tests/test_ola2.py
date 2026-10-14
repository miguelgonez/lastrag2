"""Ola 2 — CB-5 (Evidence Pack 2.0), CB-6 (Conflict Engine),
CB-7 (Temporal RAG). Caso permitido + bloqueado por control."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.backends.base import EvidenceChunk, Citation
from core.rag.engine import LastRAGEngine
from core.rag.pack import build_pack, extract_claims
from core.rag.conflict import ConflictEngine
from core.rag.temporal import temporal_filter
from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM


def _mk(text, loc, score=1.0):
    return EvidenceChunk(
        text=text, locator=loc, score=score,
        citation=Citation(document="Guia DM2", section="3.1", page=42,
                          block_id=loc, confidence=1.0),
    )


# ---------------- CB-5: Evidence Pack 2.0 ----------------

def test_cb5_spans_verifiable_permitted():
    chunk = _mk("La metformina reduce la hemoglobina glucosilada. "
                "La dosis se ajusta por función renal.", "blk_a")
    claims = extract_claims([chunk])
    assert claims, "no extrajo claims"
    for c in claims:
        for sp in c.spans:
            assert sp.verify(chunk.text), "span NO verificable"


def test_cb5_pack_render_is_object_not_chunk_cloud_permitted():
    chunks = [_mk("La metformina reduce la HbA1c en pacientes con DM2.", "blk_a")]
    pack = build_pack("¿Tratamiento DM2?", chunks, gaps=["efectos adversos"])
    rendered = pack.render_for_prompt()
    assert "Evidence Pack 2.0" in rendered
    assert "C1:" in rendered
    assert "efectos adversos" in rendered  # gap declarado al LLM


def test_cb5_engine_llm_receives_pack_permitted():
    llm = FakeLLM()
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), llm, build_pack=True)
    result = asyncio.run(engine.run("¿Qué dice la guía sobre metformina?"))
    assert result["features"]["pack"]["claims"] >= 1
    assert any("Evidence Pack 2.0" in p for p in llm.prompts), \
        "el LLM recibió la nube de chunks, no el objeto"


def test_cb5_no_evidence_no_pack_blocked():
    class EmptyLastIndex(FakeLastIndex):
        async def structural_search(self, query, *, top_k=5):
            return []
    engine = LastRAGEngine(FakeBackend(corpus=[]), EmptyLastIndex(),
                           FakeLLM(), build_pack=True)
    result = asyncio.run(engine.run("¿Qué dice sobre otro tema?"))
    assert result["features"].get("pack") is None  # sin evidencia no hay pack


# ---------------- CB-6: Conflict Engine ----------------

def _claims(*texts):
    chunks = [_mk(t, f"blk_{i}") for i, t in enumerate(texts)]
    return extract_claims(chunks)


def test_cb6_contradiction_permitted():
    claims = _claims(
        "La metformina aumenta el riesgo de acidosis láctica.",
        "La metformina disminuye el riesgo de acidosis láctica.",
    )
    groups = ConflictEngine().detect(claims)
    assert groups, "no agrupó claims comparables"
    assert groups[0]["relation"] == "CONTRADICTION"
    assert "direcciones opuestas" in groups[0]["reason"]


def test_cb6_methodological_difference_permitted():
    claims = _claims(
        "Ensayo aleatorizado: la metformina reduce la HbA1c frente a placebo.",
        "Estudio observacional: la metformina reduce la HbA1c en la práctica.",
    )
    groups = ConflictEngine().detect(claims)
    assert groups[0]["relation"] == "METHODOLOGICAL_DIFFERENCE"


def test_cb6_unresolved_declared_blocked():
    claims = _claims(
        "La metformina se administra con dieta en DM2.",
        "La metformina con dieta es segura en insuficiencia renal.",
    )
    groups = ConflictEngine().detect(claims)
    assert groups, "no agrupó claims comparables"
    assert groups[0]["relation"] == "UNRESOLVED"


def test_cb6_never_averages_blocked():
    summary = ConflictEngine.summarize([{"relation": "CONTRADICTION"}])
    assert summary["silent_averaging"] is False  # promediar está proscrito


# ---------------- CB-7: Temporal RAG ----------------

_META = {
    "gui_2018": {"valid_from": 2018, "valid_until": 2023,
                 "guideline_version": "2018", "superseded_by": "gui_2024"},
    "gui_2024": {"valid_from": 2024, "guideline_version": "2024"},
    "sin_fecha": {},
}


def _tchunks():
    return [
        _mk("Recomendación antigua de 2018: sulfonilureas.", "gui_2018"),
        _mk("Recomendación vigente 2024: metformina primera línea.", "gui_2024"),
        _mk("Nota sin fecha del comité.", "sin_fecha"),
    ]


def test_cb7_superseded_not_served_as_current_blocked():
    dec = temporal_filter(_tchunks(), _META, "¿qué recomienda la guía actualmente?")
    kept = {c.locator for c in dec.kept}
    assert "gui_2018" not in kept
    dropped = [d for d in dec.dropped if d["locator"] == "gui_2018"]
    assert dropped and "SUPERSEDED_BY:gui_2024" in dropped[0]["reason"]


def test_cb7_historical_window_permitted():
    dec = temporal_filter(_tchunks(), _META,
                          "¿qué recomendaba la guía en 2018?")
    assert dec.mode == "historical:2018"
    kept = {c.locator for c in dec.kept}
    assert "gui_2018" in kept
    assert "gui_2024" not in kept


def test_cb7_undated_declared_never_invented_blocked():
    dec = temporal_filter(_tchunks(), _META, "¿qué recomienda la guía?")
    assert dec.undated_kept == 1
    for d in dec.dropped:
        assert "2018" in d["reason"] or "SUPERSEDED" in d["reason"]


def test_cb7_engine_temporal_declared_permitted():
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), FakeLLM(),
                           temporal_meta={
                               "blk_tto": {"valid_from": 2020,
                                           "superseded_by": "blk_new"}})
    result = asyncio.run(engine.run("¿Qué dice la guía sobre metformina?"))
    assert result["features"]["temporal"]["mode"] == "current"
    assert result["features"]["temporal"]["dropped"]
