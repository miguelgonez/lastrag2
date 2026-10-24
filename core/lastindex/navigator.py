"""
LastRAG v2 — LastIndex: Navigator
=================================
Dos responsabilidades:
  1. INGESTA   : persistir un ParsedDocument como arbol en Neo4j.
  2. RESOLUCION: convertir `locator` (block_id) -> Citation completa.
  3. ESTRUCTURAL: retriever por palabras clave con localizacion exacta.

Es la capa que da PARIDAD de citacion: tanto Gemini como Qdrant entregan
`locator = block_id`, y aqui se resuelve a documento/seccion/pagina identicos.
"""

from __future__ import annotations

from typing import Optional

from .schema import (
    SCHEMA_STATEMENTS,
    UPSERT_DOCUMENT,
    UPSERT_BLOCK,
    RESOLVE_CITATION,
    STRUCTURAL_SEARCH,
)
from .parser import ParsedDocument
from ..backends.base import Citation, EvidenceChunk


class LastIndex:
    """Capa de navegacion documental sobre Neo4j."""

    def __init__(self, uri: str, user: str, password: str, **driver_kwargs):
        from neo4j import AsyncGraphDatabase
        # driver_kwargs (p. ej. connection_timeout) permite fallar rapido contra
        # un Neo4j ausente: la degradacion debe declararse pronto, no colgar.
        self.driver = AsyncGraphDatabase.driver(uri, auth=(user, password), **driver_kwargs)

    async def setup_schema(self) -> None:
        async with self.driver.session() as session:
            for stmt in SCHEMA_STATEMENTS:
                try:
                    await session.run(stmt)
                except Exception as e:  # constraint ya existe, etc.
                    print(f"⚠️ schema stmt: {e}")
        print("✅ LastIndex schema listo")

    async def close(self) -> None:
        await self.driver.close()

    # --- Ingesta ---
    async def ingest_tree(self, parsed: ParsedDocument) -> dict:
        async with self.driver.session() as session:
            await session.run(
                UPSERT_DOCUMENT,
                document_id=parsed.document_id,
                title=parsed.title,
                source_path=parsed.source_path,
                specialty=parsed.specialty,
                doc_type=parsed.doc_type,
            )
            for b in parsed.blocks:
                await session.run(
                    UPSERT_BLOCK,
                    document_id=parsed.document_id,
                    chapter=b.chapter,
                    section_path=b.section_path,
                    section_title=b.section_title,
                    block_id=b.block_id,
                    text=b.text,
                    page=b.page,
                    order=b.order,
                )
        return {
            "document_id": parsed.document_id,
            "blocks_indexed": len(parsed.blocks),
        }

    # --- Resolucion de citaciones (paridad entre backends) ---
    async def resolve_citation(self, locator: str) -> Optional[Citation]:
        async with self.driver.session() as session:
            result = await session.run(RESOLVE_CITATION, block_id=locator)
            record = await result.single()
            if not record:
                return None
            return Citation(
                document=record["document"],
                document_id=record["document_id"],
                chapter=record["chapter"],
                section=record["section"],
                page=record["page"],
                block_id=record["block_id"],
                confidence=1.0,  # localizacion exacta desde el arbol
            )

    async def enrich_chunks(
        self, chunks: list[EvidenceChunk]
    ) -> list[EvidenceChunk]:
        """Rellena la Citation de cada chunk usando su locator. In-place."""
        for chunk in chunks:
            if chunk.citation is None and chunk.locator:
                chunk.citation = await self.resolve_citation(chunk.locator)
                # Si el locator no es un block_id conocido, dejamos una
                # citacion minima para no perder trazabilidad.
                if chunk.citation is None:
                    chunk.citation = Citation(
                        document=chunk.locator, confidence=0.2
                    )
        return chunks

    # --- Retriever estructural (localizacion exacta sin vectores) ---
    async def structural_search(
        self, query: str, *, top_k: int = 5
    ) -> list[EvidenceChunk]:
        lucene = self._to_lucene(query)
        async with self.driver.session() as session:
            result = await session.run(
                STRUCTURAL_SEARCH, lucene_query=lucene, top_k=top_k
            )
            chunks: list[EvidenceChunk] = []
            async for r in result:
                chunks.append(
                    EvidenceChunk(
                        text=r["text"],
                        locator=r["block_id"],
                        score=float(r["score"]),
                        citation=Citation(
                            document=r["document"] or r["block_id"],
                            document_id=r["document_id"],
                            section=r["section"],
                            page=r["page"],
                            block_id=r["block_id"],
                            confidence=1.0,
                        ),
                    )
                )
            return chunks

    @staticmethod
    def _to_lucene(query: str) -> str:
        # Tokenizacion simple para el indice full-text de Neo4j.
        import re
        terms = re.findall(r"\w{3,}", query.lower())
        return " OR ".join(terms) if terms else query
