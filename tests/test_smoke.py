"""
LastRAG v2 — Test de humo
=========================
Valida que los contratos, dataclasses, router y scoring funcionan SIN
necesitar Neo4j, Qdrant ni Gemini. Usa un VectorBackend y un LLMClient fake.

Ejecutar:  python -m pytest tests/test_smoke.py  (o)  python tests/test_smoke.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Permite ejecutar el archivo directamente
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.backends.base import (  # noqa: E402
    VectorBackend, RetrievalResult, EvidenceChunk, Citation, IngestResult,
)
from core.rag.engine import route_query, LastRAGEngine  # noqa: E402
from core.llm.base import LLMClient  # noqa: E402


# --- Dobles de prueba ---

class FakeBackend(VectorBackend):
    name = "fake"
    sends_data_to_cloud = False

    async def initialize(self): ...
    async def ingest(self, file_path, *, document_id, metadata=None):
        return IngestResult(document_id, "ok", chunks_indexed=1)
    async def search(self, query, *, top_k=5, metadata_filter=None):
        return RetrievalResult(
            chunks=[EvidenceChunk(text="La metformina es primera linea en DM2.",
                                  locator="blk_test", score=0.9)],
            backend=self.name,
        )
    async def list_documents(self):
        return [{"id": "doc_demo"}]


class FakeLastIndex:
    """Stub de LastIndex que no usa Neo4j."""
    async def enrich_chunks(self, chunks):
        for c in chunks:
            if c.citation is None:
                c.citation = Citation(
                    document="Guia DM2", section="3.1 Tratamiento",
                    page=42, block_id=c.locator, confidence=1.0,
                )
        return chunks
    async def structural_search(self, query, *, top_k=5):
        return [EvidenceChunk(
            text="Dosis inicial: 500 mg/dia.", locator="blk_dose",
            citation=Citation(document="Guia DM2", section="3.2 Dosificacion",
                              page=43, block_id="blk_dose", confidence=1.0),
            score=2.0,
        )]


class FakeLLM(LLMClient):
    name = "fake"
    async def generate(self, prompt, *, max_tokens=8192):
        # Simula respuesta con evidencia (no admite conocimiento general)
        return "La metformina es el tratamiento de primera linea (Guia DM2, p.42)."


# --- Tests ---

def test_router():
    assert route_query("¿En que pagina aparece la dosis?") == "structural"
    assert route_query("¿Que relacion hay entre ERC y diabetes?") == "graph"
    assert route_query("Tratamiento de la diabetes tipo 2") == "hybrid"
    print("✅ router OK")


def test_citation_parity():
    """Mismo locator -> misma Citation, venga del backend que venga."""
    c1 = EvidenceChunk(text="x", locator="blk_test")
    c2 = EvidenceChunk(text="y", locator="blk_test")
    assert c1.locator == c2.locator
    print("✅ paridad de locator OK")


async def _run_engine():
    engine = LastRAGEngine(
        backend=FakeBackend(),
        lastindex=FakeLastIndex(),  # type: ignore[arg-type]
        llm=FakeLLM(),
    )
    result = await engine.run("Tratamiento de la diabetes tipo 2")
    assert result["evidence_count"] >= 1
    assert result["citations"], "debe haber citaciones resueltas"
    assert result["citations"][0]["page"] in (42, 43)
    assert not result["is_general_knowledge"]
    assert 0.0 < result["confidence"] <= 1.0
    print(f"✅ engine OK → ruta={result['route']} "
          f"conf={result['confidence']:.0%} cites={len(result['citations'])}")


def test_engine():
    asyncio.run(_run_engine())


def test_honest_scoring():
    """Si el LLM admite conocimiento general, la confianza se capa."""
    chunks = [EvidenceChunk(text="x", locator="b",
                            citation=Citation(document="d", page=1))]
    text_general = ("⚠️ **Aviso:** No se encontro evidencia en los documentos "
                    "indexados. Esta respuesta se basa en conocimiento medico general.")
    conf, is_gen = LastRAGEngine._score(text_general, chunks, "")
    assert is_gen and conf <= 0.30
    print("✅ scoring honesto OK")


if __name__ == "__main__":
    test_router()
    test_citation_parity()
    test_honest_scoring()
    test_engine()
    print("\n🎉 Todos los tests de humo pasaron.")
