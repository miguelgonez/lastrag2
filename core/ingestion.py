"""
LastRAG v2 — Pipeline de Ingesta Unificada
==========================================
Garantiza que el `block_id` sea EL MISMO en LastIndex (Neo4j) y en el backend
vectorial. Esa coincidencia es lo que da paridad de citacion.

Flujo:
  PDF ─> StructuralParser ─> ParsedDocument (bloques con block_id)
                                  │
            ┌─────────────────────┼─────────────────────┐
       LastIndex.ingest_tree   backend.ingest(blocks)   (mismo block_id)
       (estructura + paginas)  (vectores + payload)
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from .lastindex.parser import StructuralParser, ParsedDocument
from .lastindex.navigator import LastIndex
from .backends.base import VectorBackend, IngestResult


class IngestionPipeline:
    def __init__(
        self,
        parser: StructuralParser,
        lastindex: LastIndex,
        backend: VectorBackend,
    ):
        self.parser = parser
        self.lastindex = lastindex
        self.backend = backend

    async def ingest_pdf(
        self,
        file_path: str,
        *,
        specialty: Optional[str] = None,
        doc_type: Optional[str] = None,
        contains_phi: bool = False,
    ) -> dict[str, Any]:
        # Gate PHI antes de tocar cualquier servicio
        self.backend.assert_phi_allowed(contains_phi)

        # 1) Parseo estructural (genera block_id deterministas)
        parsed: ParsedDocument = self.parser.parse(
            file_path, specialty=specialty, doc_type=doc_type
        )

        # 2) Arbol documental -> Neo4j (estructura, paginas, secciones)
        tree_stats = await self.lastindex.ingest_tree(parsed)

        # 3) Vectores -> backend. Pasamos los bloques para que el locator
        #    sea exactamente el block_id de LastIndex.
        blocks_payload = [asdict(b) for b in parsed.blocks]
        vec_result: IngestResult = await self.backend.ingest(
            file_path,
            document_id=parsed.document_id,
            metadata={
                "blocks": blocks_payload,
                "specialty": specialty,
                "doc_type": doc_type,
            },
        )

        return {
            "document_id": parsed.document_id,
            "title": parsed.title,
            "lastindex": tree_stats,
            "vector": {
                "backend": self.backend.name,
                "status": vec_result.status,
                "chunks_indexed": vec_result.chunks_indexed,
                "error": vec_result.error,
            },
        }
