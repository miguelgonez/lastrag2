"""
LastRAG v2 — Backend: Qdrant (local-first / DGX / PHI)
======================================================
Backend vectorial autoalojado. Es el que habilita Nexthealth-OS sobre DGX:
los datos (incluido PHI) no salen del perimetro local.

Pipeline:
  ingest  : ParsedDocument ya troceado en bloques -> embeddings -> upsert.
            Cada punto Qdrant lleva payload {block_id, document_id, page, ...}
            de modo que block_id es el `locator` que LastIndex resuelve.
  search  : embedding de la query -> top_k puntos -> EvidenceChunk con locator.

Embeddings: por defecto un modelo local (sentence-transformers o el embedder
del DGX). Se inyecta como callable para no acoplar el backend a un proveedor.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from .base import (
    VectorBackend,
    RetrievalResult,
    EvidenceChunk,
    IngestResult,
)

# Tipo del embedder: lista de textos -> lista de vectores.
Embedder = Callable[[Sequence[str]], list[list[float]]]


class QdrantBackend(VectorBackend):
    name = "qdrant"
    sends_data_to_cloud = False  # local-first: apto para PHI

    def __init__(
        self,
        *,
        url: str = "http://localhost:6333",
        collection: str = "lastrag",
        embedder: Optional[Embedder] = None,
        vector_size: int = 768,
        api_key: Optional[str] = None,
        path: Optional[str] = None,
        embedding_model: str = "unknown",
    ):
        # P0.5: `path` activa el modo local persistente de qdrant-client (motor
        # real de Qdrant en proceso, con almacenamiento en disco y reinicio).
        # `url` mantiene el modo servidor (DGX / despliegue). Nunca ambos.
        if path and url != "http://localhost:6333":
            raise ValueError("QdrantBackend: usa `path` (local) o `url` (servidor), no ambos")
        self.url = url
        self.path = path
        self.collection = collection
        self.vector_size = vector_size
        self.api_key = api_key
        # Etiqueta de procedencia: el embedding usado queda registrado en cada
        # punto y en cada respuesta. "unknown" solo es aceptable en desarrollo.
        self.embedding_model = embedding_model
        self._embed = embedder or self._default_embedder()
        self._client = None  # qdrant_client.QdrantClient

    async def initialize(self) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        if self.path is not None:
            self._client = QdrantClient(path=self.path)
        else:
            self._client = QdrantClient(url=self.url, api_key=self.api_key)
        existing = {c.name for c in self._client.get_collections().collections}
        if self.collection not in existing:
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(
                    size=self.vector_size, distance=Distance.COSINE
                ),
            )
            print(f"✅ Qdrant: coleccion '{self.collection}' creada ({self.mode})")
        else:
            print(f"✅ Qdrant: coleccion '{self.collection}' existente ({self.mode})")

    @property
    def mode(self) -> str:
        return "local-persistent" if self.path else f"server:{self.url}"

    async def ingest(
        self,
        file_path: str,
        *,
        document_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> IngestResult:
        """
        Para Qdrant la ingesta vectorial parte de los bloques ya parseados por
        LastIndex (para que block_id coincida). Se espera que metadata incluya
        la lista de bloques: metadata["blocks"] = [ParsedBlock-like dicts].
        Esto garantiza locator == block_id en ambos backends.
        """
        from qdrant_client.models import PointStruct

        blocks = (metadata or {}).get("blocks")
        if not blocks:
            return IngestResult(
                document_id, "error",
                error="QdrantBackend.ingest requiere metadata['blocks'] de LastIndex",
            )

        texts = [b["text"] for b in blocks]
        vectors = self._embed(texts)
        points = [
            PointStruct(
                id=self._point_id(b["block_id"]),
                vector=vec,
                payload={
                    "block_id": b["block_id"],
                    "document_id": document_id,
                    "page": b.get("page"),
                    "section_path": b.get("section_path"),
                    "text": b["text"],
                    "embedding_model": self.embedding_model,
                },
            )
            for b, vec in zip(blocks, vectors)
        ]
        try:
            self._client.upsert(collection_name=self.collection, points=points)
            return IngestResult(
                document_id, "ok", chunks_indexed=len(points),
                message="indexado en Qdrant",
            )
        except Exception as e:
            return IngestResult(document_id, "error", error=str(e))

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> RetrievalResult:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        qfilter = None
        if metadata_filter:
            qfilter = Filter(
                must=[
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in metadata_filter.items()
                ]
            )

        vector = self._embed([query])[0]
        try:
            # qdrant-client >= 1.10: query_points sustituye a search (eliminado)
            response = self._client.query_points(
                collection_name=self.collection,
                query=vector,
                limit=top_k,
                query_filter=qfilter,
                with_payload=True,
            )
            hits = response.points
        except Exception as e:
            # P0.5: sin fallback silencioso. El error viaja en degraded_reason
            # y el motor lo declara en la respuesta final.
            print(f"⚠️ Qdrant search error: {e}")
            return RetrievalResult(
                backend=self.name, degraded_reason=f"QDRANT_ERROR:{type(e).__name__}"
            )

        chunks = [
            EvidenceChunk(
                text=h.payload.get("text", ""),
                locator=h.payload.get("block_id", ""),
                score=float(h.score),
            )
            for h in hits
        ]
        return RetrievalResult(chunks=chunks, backend=self.name, raw=hits)

    async def list_documents(self) -> list[dict[str, Any]]:
        # Documentos distintos via scroll del payload (simplificado).
        if not self._client:
            return []
        seen: dict[str, int] = {}
        try:
            offset = None
            while True:
                points, offset = self._client.scroll(
                    collection_name=self.collection,
                    with_payload=True,
                    limit=256,
                    offset=offset,
                )
                for p in points:
                    did = p.payload.get("document_id")
                    if did:
                        seen[did] = seen.get(did, 0) + 1
                if offset is None:
                    break
        except Exception as e:
            print(f"⚠️ list_documents: {e}")
        return [{"id": k, "chunks": v} for k, v in seen.items()]

    async def close(self) -> None:
        if self._client:
            self._client.close()

    async def health(self) -> dict[str, Any]:
        """Diagnostico real de conectividad (P0.5). Sin retries: devuelve estado."""
        if not self._client:
            return {"status": "DOWN", "reason": "NOT_INITIALIZED", "backend": self.name,
                    "mode": self.mode}
        try:
            names = [c.name for c in self._client.get_collections().collections]
            return {"status": "UP", "backend": self.name, "mode": self.mode,
                    "collections": names,
                    "collection_ready": self.collection in names}
        except Exception as exc:
            return {"status": "DOWN", "reason": f"QDRANT_ERROR:{type(exc).__name__}",
                    "backend": self.name, "mode": self.mode}

    # --- helpers ---
    @staticmethod
    def _point_id(block_id: str) -> int:
        # Qdrant admite int o UUID. Derivamos int estable del block_id.
        import hashlib
        return int(hashlib.sha1(block_id.encode()).hexdigest()[:15], 16)

    @staticmethod
    def _default_embedder() -> Embedder:
        """Embedder local por defecto (sentence-transformers). Lazy import."""
        model_holder: dict[str, Any] = {}

        def _embed(texts: Sequence[str]) -> list[list[float]]:
            if "m" not in model_holder:
                from sentence_transformers import SentenceTransformer
                # En DGX se sustituye por el modelo biomedico local.
                model_holder["m"] = SentenceTransformer(
                    "sentence-transformers/all-mpnet-base-v2"
                )
            vecs = model_holder["m"].encode(list(texts), normalize_embeddings=True)
            return [v.tolist() for v in vecs]

        return _embed
