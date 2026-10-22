"""
P0.5 — Registro de degradaciones del motor (logica, con dobles declarados).
===========================================================================
Estas pruebas validan la REGLA "no fallback silencioso" del motor usando
dobles (FakeBackend/FakeLLM/FakeLastIndex). No son la evidencia E2E (esa
vive en test_e2e_sovereign.py); son el control unitario del registry.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.backends.base import (  # noqa: E402
    VectorBackend, RetrievalResult, EvidenceChunk, IngestResult, Citation,
)
from core.rag.engine import LastRAGEngine  # noqa: E402
from core.llm.base import LLMClient  # noqa: E402


class FakeBackend(VectorBackend):
    name = "fake"
    sends_data_to_cloud = False

    def __init__(self, degraded_reason=None):
        self.degraded_reason = degraded_reason

    async def initialize(self): ...
    async def ingest(self, file_path, *, document_id, metadata=None):
        return IngestResult(document_id, "ok", chunks_indexed=1)
    async def search(self, query, *, top_k=5, metadata_filter=None):
        return RetrievalResult(
            chunks=[EvidenceChunk(text="La metformina es primera linea en DM2.",
                                  locator="blk_test", score=0.9)],
            backend=self.name, degraded_reason=self.degraded_reason)
    async def list_documents(self):
        return []


class FakeLastIndex:
    def __init__(self, fail=False):
        self.fail = fail

    async def enrich_chunks(self, chunks):
        if self.fail:
            raise ConnectionError("neo4j down")
        for c in chunks:
            if c.citation is None:
                c.citation = Citation(document="doc", section="Tratamiento",
                                      page=1, block_id=c.locator)
        return chunks

    async def structural_search(self, query, *, top_k=5):
        if self.fail:
            raise ConnectionError("neo4j down")
        return []


class GradingLLM(LLMClient):
    """Responde al grade EN SU FORMATO (MCQ: A = evidencia relevante) y texto
    normal al resto. El marcador antiguo ("evaluador estricto") ya no existe
    en el prompt desde el cambio a MCQ del 15-oct-2026, así que este doble
    nunca llegaba a validar: todas estas pruebas pasaban por la rama
    UNDECIDABLE_VERDICT sin pretenderlo."""
    name = "fake"

    async def generate(self, prompt, *, max_tokens=8192):
        if "Pregunta de examen" in prompt:
            return "A"
        return "Respuesta basada en la evidencia proporcionada."


def run_engine(query, *, backend=None, lastindex=None, graph=None):
    engine = LastRAGEngine(
        backend or FakeBackend(),
        lastindex or FakeLastIndex(),
        GradingLLM(),
        neo4j_graph=graph,
    )
    return asyncio.run(engine.run(query))


def test_graph_route_degrades_to_hybrid_and_declares_it():
    out = run_engine("¿que interaccion tiene la metformina con otros farmacos?")
    assert out["route"] == "graph"
    assert out["route_effective"] == "hybrid", \
        "sin Neo4j graph la ruta ejecutada debe ser hybrid y VISIBLE"
    entries = {(d.get("component"), d.get("reason")) for d in out["degradations"]}
    assert ("neo4j_graph", "NOT_CONFIGURED") in entries
    declared = [d for d in out["degradations"]
                if d.get("from_route") == "graph" and d.get("to_route") == "hybrid"]
    assert declared, "la caida graph->hybrid debe quedar declarada con from/to"


def test_hybrid_declares_graph_unavailable_even_without_graph_route():
    out = run_engine("dosis de metformina en diabetes")
    assert out["route_effective"] == "hybrid"
    assert any(d.get("component") == "neo4j_graph" for d in out["degradations"]), \
        "hybrid tambien declara que el contexto de grafo no esta disponible"


def test_backend_failure_is_declared_not_silent():
    out = run_engine("dosis de metformina", backend=FakeBackend(degraded_reason="QDRANT_ERROR:X"))
    assert any(d.get("component") == "backend:fake" and d.get("reason") == "QDRANT_ERROR:X"
               for d in out["degradations"])


def test_lastindex_unreachable_declares_citation_degradation():
    out = run_engine("dosis de metformina", lastindex=FakeLastIndex(fail=True))
    assert any(d.get("component") == "lastindex" and "NEO4J_UNREACHABLE" in d.get("reason", "")
               for d in out["degradations"])
    assert out["evidence"], "los fragmentos siguen llegando (con cita sin resolver)"


def test_run_output_exposes_evidence_pack_fields():
    out = run_engine("dosis de metformina")
    assert out["evidence"][0]["locator"] == "blk_test"
    assert "degradations" in out and "route_effective" in out
    assert out["confidence"] > 0 and not out["is_general_knowledge"]
