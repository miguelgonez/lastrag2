"""
LastRAG v2 — Backend: Gemini File Search (cloud / SaaS)
=======================================================
Refactor del antiguo GeminiFileSearchManager detras de VectorBackend.
Conserva lo que funcionaba (operacion atomica upload_to_file_search_store)
pero ahora:
  - devuelve RetrievalResult normalizado,
  - usa block_id como `locator` (lo emite en metadata al ingerir),
  - declara sends_data_to_cloud=True para el gate PHI.

Nota: este backend SOLO debe usarse con corpus sin PHI (guias publicas,
papers, BOE). Para datos reales de paciente -> QdrantBackend.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from google import genai
from google.genai import types

from .base import (
    VectorBackend,
    RetrievalResult,
    EvidenceChunk,
    IngestResult,
)


class GeminiFileSearchBackend(VectorBackend):
    name = "gemini_file_search"
    sends_data_to_cloud = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        store_display_name: str = "lastrag-knowledge-base",
        model: str = "gemini-2.5-flash",
    ):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.store_display_name = store_display_name
        self.model = model
        self.store = None

    async def initialize(self) -> None:
        if not self.client:
            raise ValueError("GOOGLE_API_KEY no configurada")
        for store in self.client.file_search_stores.list():
            if store.display_name == self.store_display_name:
                self.store = store
                print(f"✅ File Search Store: {store.name}")
                return
        self.store = self.client.file_search_stores.create(
            config={"display_name": self.store_display_name}
        )
        print(f"✅ File Search Store creado: {self.store.name}")

    async def ingest(
        self,
        file_path: str,
        *,
        document_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> IngestResult:
        if not self.client or not self.store:
            return IngestResult(document_id, "error", error="backend no inicializado")

        path = Path(file_path)
        if not path.exists():
            return IngestResult(document_id, "error", error="archivo no encontrado")

        # document_id viaja como metadata custom para reconstruir locators.
        custom_meta = {"document_id": document_id}
        if metadata:
            custom_meta.update({k: str(v) for k, v in metadata.items()})

        try:
            operation = self.client.file_search_stores.upload_to_file_search_store(
                file=str(path),
                file_search_store_name=self.store.name,
                config={
                    "display_name": document_id,
                    "custom_metadata": [
                        {"key": k, "string_value": v}
                        for k, v in custom_meta.items()
                    ],
                },
            )
            start = time.time()
            while not operation.done:
                if time.time() - start > 180:
                    return IngestResult(
                        document_id, "error", error="timeout indexacion (>180s)"
                    )
                # await, no time.sleep: bloquear el loop aqui congelaba todo el
                # proceso (hasta 180 s) en cualquier despliegue asincrono.
                await asyncio.sleep(3)
                operation = self.client.operations.get(operation)

            if getattr(operation, "error", None):
                return IngestResult(
                    document_id, "error", error=str(operation.error)
                )
            return IngestResult(document_id, "ok", message="indexado en File Search")
        except Exception as e:
            return IngestResult(document_id, "error", error=str(e))

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> RetrievalResult:
        if not self.client or not self.store:
            # P0.5: "sin store" NO es "sin evidencia". Si el backend no esta
            # operativo la razon viaja declarada; de lo contrario el motor
            # leeria un vacio documental que nunca se midio.
            return RetrievalResult(
                backend=self.name,
                degraded_reason="GEMINI_NOT_INITIALIZED:"
                                + ("NO_CLIENT" if not self.client else "NO_STORE"),
            )

        prompt = self._retrieval_prompt(query, top_k)
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=4096,
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                file_search_store_names=[self.store.name]
                            )
                        )
                    ],
                ),
            )
        except Exception as e:
            # Mismo contrato que QdrantBackend: el error viaja en
            # degraded_reason y el motor lo declara en degradations[].
            print(f"⚠️ Gemini search error: {e}")
            return RetrievalResult(
                backend=self.name,
                degraded_reason=f"GEMINI_ERROR:{type(e).__name__}",
            )

        chunks = self._parse_grounded(response, top_k)
        return RetrievalResult(chunks=chunks, backend=self.name, raw=response)

    async def list_documents(self) -> list[dict[str, Any]]:
        if not self.client or not self.store:
            return []
        docs = []
        try:
            for doc in self.client.file_search_stores.documents.list(
                parent=self.store.name
            ):
                docs.append({"id": doc.display_name, "name": doc.name})
        except Exception as e:
            print(f"⚠️ list_documents: {e}")
        return docs

    # --- helpers ---
    @staticmethod
    def _retrieval_prompt(query: str, top_k: int) -> str:
        return (
            "Extrae SOLO la evidencia textual relevante de los documentos para "
            "la consulta. NO generes respuesta. Devuelve hasta "
            f"{top_k} fragmentos exactos, cada uno con su documento de origen.\n\n"
            f"Consulta: {query}\n\n"
            "Formato:\n<EV>texto exacto</EV><SRC>document_id</SRC>\n"
            "Si no hay evidencia: <SIN_EVIDENCIA/>"
        )

    def _parse_grounded(self, response, top_k: int) -> list[EvidenceChunk]:
        """
        Extrae fragmentos del texto Y, si existe, del grounding_metadata
        (que trae el chunk id real -> nuestro locator). El grounding tiene
        prioridad porque permite resolver la Citation exacta via LastIndex.
        """
        chunks: list[EvidenceChunk] = []

        # 1) Grounding real (preferido): da el origen verificable.
        try:
            cand = response.candidates[0]
            gm = getattr(cand, "grounding_metadata", None)
            if gm and getattr(gm, "grounding_chunks", None):
                for gc in gm.grounding_chunks[:top_k]:
                    ctx = getattr(gc, "retrieved_context", None)
                    if not ctx:
                        continue
                    text = getattr(ctx, "text", "") or ""
                    # title suele traer el display_name = document_id
                    locator = getattr(ctx, "title", "") or ""
                    if text:
                        chunks.append(
                            EvidenceChunk(text=text.strip(), locator=locator, score=1.0)
                        )
                if chunks:
                    return chunks
        except Exception:
            pass

        # 2) Fallback: parsear el formato <EV>/<SRC> del prompt.
        raw = response.text or ""
        ev = re.findall(r"<EV>\s*(.*?)\s*</EV>", raw, re.DOTALL)
        src = re.findall(r"<SRC>\s*(.*?)\s*</SRC>", raw, re.DOTALL)
        for i, text in enumerate(ev[:top_k]):
            locator = src[i].strip() if i < len(src) else ""
            chunks.append(EvidenceChunk(text=text.strip(), locator=locator, score=0.8))
        return chunks
