"""Dobles de prueba compartidos (sin Neo4j/Qdrant/Gemini), patrón test_smoke."""

from __future__ import annotations

from core.backends.base import (
    VectorBackend, RetrievalResult, EvidenceChunk, Citation, IngestResult,
)
from core.llm.base import LLMClient


class FakeBackend(VectorBackend):
    """Backend configurable: devuelve chunks cuyo texto contenga algún término
    de la consulta (simula recuperación)."""

    name = "fake"
    sends_data_to_cloud = False

    def __init__(self, corpus: list[EvidenceChunk] | None = None):
        self.corpus = corpus if corpus is not None else [
            EvidenceChunk(text="La metformina es primera linea en DM2.",
                          locator="blk_tto", score=0.9),
        ]
        self.calls: list[str] = []

    async def initialize(self): ...
    async def ingest(self, file_path, *, document_id, metadata=None):
        return IngestResult(document_id, "ok", chunks_indexed=1)
    async def search(self, query, *, top_k=5, metadata_filter=None):
        self.calls.append(query)
        low = query.lower()
        hits = [c for c in self.corpus if any(t in c.text.lower() for t in low.split())]
        return RetrievalResult(chunks=hits or self.corpus[:1], backend=self.name)
    async def list_documents(self):
        return [{"id": "doc_demo"}]


class FakeLastIndex:
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


#: Marca del prompt del nodo `grade` (formato MCQ desde el 15-oct-2026).
GRADE_PROMPT_MARK = "Pregunta de examen"


class FakeLLM(LLMClient):
    """Doble del LLM que responde el grade EN SU FORMATO (MCQ A/B) y el texto
    configurado para la generacion.

    Antes respondia prosa tambien al grade: el motor no podia parsear el
    veredicto y TODAS las pruebas de motor atravesaban la rama
    UNDECIDABLE_VERDICT, de modo que el camino normal del filtro de dominio
    no estaba cubierto por ninguna prueba.
    """

    name = "fake"

    def __init__(self, response: str = "La metformina es el tratamiento de "
                                       "primera linea (Guia DM2, p.42).",
                 grade: str = "A"):
        self.response_text = response
        self.grade = grade
        self.prompts: list[str] = []

    async def generate(self, prompt, *, max_tokens=8192):
        self.prompts.append(prompt)
        if GRADE_PROMPT_MARK in prompt:
            return self.grade
        return self.response_text
