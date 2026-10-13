"""Ola 5 — CB-12 (Failure Graph con coste medido) y CB-13 (taxonomía de la
abstención: NO_EVIDENCE vs INSUFFICIENT_EVIDENCE distinguibles)."""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.backends.base import EvidenceChunk, RetrievalResult
from core.rag.engine import LastRAGEngine
from core.rag.failure_graph import (
    FailureGraph, classify_absence, RETRIEVAL_MISS, ABSTENTION_FAILURE,
    NO_EVIDENCE, INSUFFICIENT_EVIDENCE,
)
from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM


# ---------------- CB-12: Failure Graph ----------------

def test_cb12_measure_records_cost_permitted():
    fg = FailureGraph()
    with fg.measure(RETRIEVAL_MISS, "neo4j_down"):
        time.sleep(0.01)
    assert fg.counts()[RETRIEVAL_MISS] == 1
    costs = fg.costs_ms()[RETRIEVAL_MISS]
    assert costs["p50_ms"] >= 10.0  # coste MEDIDO, no estimado
    assert costs["n"] == 1


def test_cb12_unknown_mode_rejected_blocked():
    fg = FailureGraph()
    try:
        fg.record("MODO_INVENTADO")
        raise SystemExit("modo desconocido aceptado")
    except ValueError:
        pass  # correcto: los modos son un universo cerrado


def test_cb12_engine_records_retrieval_miss_permitted():
    class EmptyLastIndex(FakeLastIndex):
        async def structural_search(self, query, *, top_k=5):
            return []
    engine = LastRAGEngine(FakeBackend(corpus=[]), EmptyLastIndex(),
                           FakeLLM(), failure_graph=FailureGraph())
    result = asyncio.run(engine.run("tema sin evidencia"))
    assert result["evidence_count"] == 0
    assert engine.failure_graph.counts()[RETRIEVAL_MISS] >= 1


def test_cb12_abstention_failure_never_fires_on_honest_scorer_blocked():
    """Caso negativo: con el scorer honesto del motor es IMPOSIBLE responder
    con confianza alta y cero citas — ABSTENTION_FAILURE no se dispara."""
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), FakeLLM(),
                           failure_graph=FailureGraph())
    result = asyncio.run(engine.run("¿Qué dice la guía sobre metformina?"))
    if result["confidence"] > 0.5:
        assert result["citations"], "confianza alta sin citas"
    assert engine.failure_graph.counts()[ABSTENTION_FAILURE] == 0
    # y sin evidencia, la confianza queda capada
    class EmptyLastIndex(FakeLastIndex):
        async def structural_search(self, query, *, top_k=5):
            return []
    engine2 = LastRAGEngine(FakeBackend(corpus=[]), EmptyLastIndex(),
                            FakeLLM(), failure_graph=FailureGraph())
    r2 = asyncio.run(engine2.run("tema sin evidencia"))
    assert r2["confidence"] <= 0.15


# ---------------- CB-13: taxonomía de la abstención ----------------

def test_cb13_taxonomy_distinguishes_permitted():
    assert classify_absence(0, None)["type"] == NO_EVIDENCE
    ins = classify_absence(3, coverage=0.25, claims_count=0)
    assert ins["type"] == INSUFFICIENT_EVIDENCE
    assert "remedy" in ins  # cada tipo dice su remedio
    ok = classify_absence(5, coverage=0.9, claims_count=6)
    assert ok["type"] is None


def test_cb13_engine_no_evidence_declared_blocked():
    class EmptyLastIndex(FakeLastIndex):
        async def structural_search(self, query, *, top_k=5):
            return []
    engine = LastRAGEngine(FakeBackend(corpus=[]), EmptyLastIndex(), FakeLLM())
    result = asyncio.run(engine.run("tema sin evidencia"))
    assert result["absence"]["type"] == NO_EVIDENCE


def test_cb13_engine_insufficient_evidence_distinguishable_permitted():
    """3 subpreguntas, sólo 1 cubierta y sin cerrar: INSUFFICIENT, no NO_."""
    class OneTopicBackend(FakeBackend):
        async def search(self, query, *, top_k=5, metadata_filter=None):
            self.calls.append(query)
            return RetrievalResult(chunks=[EvidenceChunk(
                text="La metformina es el tratamiento de primera línea en DM2.",
                locator="blk_tto", score=0.9)], backend=self.name)

    engine = LastRAGEngine(OneTopicBackend(), FakeLastIndex(), FakeLLM(),
                           iterative=True, max_iterations=2)
    result = asyncio.run(engine.run(
        "¿Tratamiento en DM2, dosis inicial y contraindicaciones?"))
    assert result["evidence_count"] > 0
    assert result["absence"]["type"] == INSUFFICIENT_EVIDENCE
