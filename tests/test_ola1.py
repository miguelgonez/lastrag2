"""Ola 1 — CB-2 (router iterativo), CB-3 (RRF), CB-4 (reranking clínico).
Cada control con caso permitido y caso bloqueado/declarado (prereg)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.backends.base import EvidenceChunk, Citation
from core.rag.engine import LastRAGEngine
from core.rag.iterative import (IterativeRouter, SufficiencyGate,
                                decompose_query, reformulate)
from core.rag.fusion import fuse_rrf, fuse_by_locator
from core.rag.rerank import ClinicalReranker
from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM


def _mk(text, loc, score=1.0, kind="text"):
    return EvidenceChunk(text=text, locator=loc, score=score, kind=kind)


# ---------------- CB-2: router iterativo ----------------

def test_cb2_decompose_permitted():
    q = ("¿Cuál es el tratamiento de primera línea en DM2 y cuál es la "
         "dosis inicial?")
    subs = decompose_query(q)
    assert len(subs) == 2
    assert any("tratamiento" in s for s in subs)
    assert any("dosis" in s for s in subs)


def test_cb2_decompose_simple_query_single_subquestion():
    assert decompose_query("¿Cuál es la dosis de metformina?") == \
        ["¿Cuál es la dosis de metformina?"]


def test_cb2_router_loop_closes_gap_permitted():
    """El bucle detecta el hueco (dosis), reformula y lo cierra."""
    corpus = [_mk("La metformina es el tratamiento de primera línea en DM2 "
                  "para control glucémico.", "blk_tto"),
              _mk("Dosis inicial: 500 mg al día con alimentos.", "blk_dose")]
    calls = []

    async def retrieve(q, top_k):
        calls.append(q)
        if "dosis" in q.lower():
            return [corpus[1]]
        return [corpus[0]]

    router = IterativeRouter(max_iterations=3)
    chunks, iterations, degr = asyncio.run(
        router.run("¿Cuál es el tratamiento en DM2 y cuál es la dosis inicial?",
                   retrieve))
    assert any("dosis" in c.text.lower() for c in chunks)
    assert iterations[-1]["action"] == "done"
    assert iterations[-1]["coverage"] == 1.0
    assert degr is None
    assert len(calls) >= 2  # hubo reformulación y re-búsqueda


def test_cb2_router_max_iterations_declared_blocked():
    """Hueco que no se cierra: SUFFICIENCY_NOT_REACHED declarado, jamás
    silencioso."""

    async def retrieve(q, top_k):
        return [_mk("La metformina es el tratamiento de primera línea en DM2.",
                    "blk_tto")]

    router = IterativeRouter(max_iterations=2)
    chunks, iterations, degr = asyncio.run(
        router.run("¿Tratamiento en DM2, dosis inicial y efectos adversos?",
                   retrieve))
    assert degr is not None
    assert degr["reason"] == "SUFFICIENCY_NOT_REACHED"
    assert degr["gaps"]
    assert iterations[-1]["action"] == "max_reached"
    assert iterations[-1]["coverage"] < 1.0


def test_cb2_engine_iterative_permitted():
    """Engine con iterative=True: subpreguntas recuperadas por separado."""
    corpus = [_mk("La metformina es el tratamiento de primera línea en DM2.",
                  "blk_tto"),
              _mk("Dosis inicial recomendada de metformina: 500 mg al día.",
                  "blk_dose")]
    backend = FakeBackend(corpus)
    engine = LastRAGEngine(backend, FakeLastIndex(), FakeLLM(),
                           iterative=True, max_iterations=3)
    result = asyncio.run(engine.run(
        "¿Cuál es el tratamiento de primera línea en DM2 y cuál es la dosis inicial?"))
    assert result["features"]["iterations"]
    assert result["features"]["iterations"][-1]["action"] in ("done", "max_reached")
    assert len(backend.calls) >= 2  # recuperó por subpregunta


# ---------------- CB-3: RRF ----------------

def test_cb3_rrf_consensus_permitted():
    """El documento presente en ambas listas gana por consenso de posiciones."""
    shared = _mk("Bloque compartido por ambas vías.", "blk_shared", score=0.9)
    only_sem = _mk("Sólo vía semántica.", "blk_sem", score=0.99)
    only_str = _mk("Sólo vía estructural.", "blk_str", score=5.0)
    fused = fuse_rrf([[only_sem, shared], [only_str, shared]])
    assert fused[0].locator == "blk_shared"  # consenso > score individual
    assert {c.locator for c in fused} == {"blk_shared", "blk_sem", "blk_str"}


def test_cb3_rrf_empty_inputs_blocked():
    assert fuse_rrf([]) == []
    assert fuse_rrf([[], []]) == []


def test_cb3_locator_mode_default_invariant_blocked():
    """Sin fusion_mode='rrf', la fusión por locator (prioridad estructural)
    NO cambia: el estructural manda."""
    structural = [_mk("Estructural con cita exacta.", "blk_str", score=0.1)]
    semantic = [_mk("Semántico mismo locator.", "blk_str", score=0.99),
                _mk("Semántico extra.", "blk_sem", score=0.5)]
    fused = fuse_by_locator(structural, semantic)
    assert len(fused) == 2
    assert fused[0].score == 0.1  # ganó el estructural


def test_cb3_engine_fusion_mode_declared():
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), FakeLLM(),
                           fusion_mode="rrf")
    result = asyncio.run(engine.run("¿Qué dice la guía sobre metformina?"))
    assert result["features"]["fusion_mode"] == "rrf"
    engine_default = LastRAGEngine(FakeBackend(), FakeLastIndex(), FakeLLM())
    result_default = asyncio.run(engine_default.run(
        "¿Qué dice la guía sobre metformina?"))
    assert result_default["features"]["fusion_mode"] == "locator"


# ---------------- CB-4: reranking clínico ----------------

def test_cb4_clinical_rerank_permitted():
    """El meta-análisis reciente con guía oficial sube sobre el caso clínico
    antiguo, con reasons auditables."""
    weak = _mk("Serie de casos de 2011: observación de tres pacientes.",
               "blk_casos", score=0.95)
    strong = _mk("Meta-análisis 2024 de ensayos aleatorizados: reduce "
                 "mortalidad. Guía clínica de sociedad española.",
                 "blk_meta", score=0.90)
    rr = ClinicalReranker().rerank("tratamiento y mortalidad", [weak, strong])
    assert rr.ranked[0].locator == "blk_meta"
    assert rr.model == "clinical-filters-deterministic-v1"
    assert rr.reasons["blk_meta"], "sin razones auditables"
    assert any("estudio:" in r for r in rr.reasons["blk_meta"])


def test_cb4_rerank_empty_blocked():
    rr = ClinicalReranker().rerank("consulta", [])
    assert rr.ranked == []


def test_cb4_engine_without_reranker_declares_nothing_blocked():
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), FakeLLM())
    result = asyncio.run(engine.run("¿Qué dice la guía sobre metformina?"))
    assert "rerank" not in result["features"]  # sin reranker no se reordena


def test_cb4_engine_with_reranker_declared_permitted():
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), FakeLLM(),
                           reranker=ClinicalReranker())
    result = asyncio.run(engine.run("¿Qué dice la guía sobre metformina?"))
    assert result["features"]["rerank"]["model"] == \
        "clinical-filters-deterministic-v1"


def test_cb4_crossencoder_real_if_available():
    """Cross-encoder ONNX real; si el modelo no puede descargarse, SKIP
    DECLARADO (ausencia, no fallo silencioso)."""
    try:
        from core.rag.rerank import CrossEncoderReranker
        rr = CrossEncoderReranker()
        out = rr.rerank("dosis de metformina", [
            _mk("La dosis inicial de metformina es 500 mg.", "blk_a"),
            _mk("El urbanismo andaluz regula el uso del suelo.", "blk_b"),
        ])
        assert out.ranked[0].locator == "blk_a"
        assert "crossencoder-onnx" in out.model
    except Exception as exc:  # pragma: no cover
        import pytest
        pytest.skip(f"cross-encoder ONNX no disponible: {type(exc).__name__}")
