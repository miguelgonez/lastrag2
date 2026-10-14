"""
LastRAG v2 — Fase 2: Backend vectorial sobre Delta Lake (piloto PubMed)
========================================================================
Backend de SOLO LECTURA contra el Delta materializado en Fase 1
(topic × year). No genera embeddings: filtra por metadatos + coincidencia
léxica mínima y devuelve EvidenceChunks citados por PMID; el ranking
semántico y los rerankers siguen viviendo en el motor (como el resto de
backends). La columna de embeddings en Delta queda como evolución futura.

Soberanía: local al host Spark; sends_data_to_cloud = False. El gate PHI no
lo bloquea (es local-first).

Uso:
  LASTRAG_BACKEND=delta  DELTA_PATH=/…/delta_pubmed

Requiere pyspark + delta-spark en el entorno de ejecución (p. ej. el
contenedor apache/spark usado en la Fase 1); en el repo de desarrollo este
módulo SOLO se importa bajo esa configuración (factory lazy) o desde su
test de humo con skip declarado.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from .base import (Citation, EvidenceChunk, IngestResult, RetrievalResult,
                   VectorBackend)


class DeltaBackend(VectorBackend):
    """Solo lectura sobre el Delta del piloto; el motor re-rankea."""

    name = "delta"
    sends_data_to_cloud = False

    def __init__(self, delta_path: Optional[str] = None):
        self.delta_path = delta_path or os.getenv("DELTA_PATH", "")
        if not self.delta_path:
            raise ValueError("DELTA_PATH no definido (backend delta)")
        from pyspark.sql import SparkSession
        self._spark = (
            SparkSession.builder
            .appName("LastRAG-DeltaBackend")
            .config("spark.sql.extensions",
                    "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog",
                    "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )
        self._df = self._spark.read.format("delta").load(self.delta_path)

    # --- contrato VectorBackend ---

    async def initialize(self) -> None:
        """Ya cargado en __init__; idempotente por diseño de SparkSession."""
        self._df.count()  # fuerza la lectura real (falla aquí si Delta no sirve)

    async def ingest(self, file_path: str, *, document_id: str,
                     metadata: Optional[dict[str, Any]] = None) -> IngestResult:
        """Solo lectura en esta fase: la escritura vive en la Fase 1."""
        return IngestResult(document_id=document_id, status="error",
                            message="DeltaBackend es de solo lectura "
                                    "(la ingesta vive en ingest_pubmed_delta.py)")

    async def search(self, query: str, *, top_k: int = 5,
                     metadata_filter: Optional[dict[str, Any]] = None
                     ) -> RetrievalResult:
        """Filtro por metadatos (topic, year) + léxico mínimo. El score es
        un marcador (0.5): el orden real lo decide el motor con embedder y
        rerankers — jamás se presenta como ranking semántico."""
        from pyspark.sql.functions import col, lower
        df = self._df
        if metadata_filter:
            if metadata_filter.get("topic"):
                df = df.filter(col("topic") == metadata_filter["topic"])
            if metadata_filter.get("year") is not None:
                df = df.filter(col("year") == int(metadata_filter["year"]))

        terms = [t for t in query.lower().split() if len(t) > 3]
        cond = None
        for t in terms:
            c = lower(col("abstract")).contains(t) | lower(col("title")).contains(t)
            cond = c if cond is None else (cond | c)
        if cond is not None:
            df = df.filter(cond)

        rows = df.limit(top_k * 3).collect()  # margen para el reranker

        chunks = []
        for r in rows[:top_k]:
            text = f"{r.title or ''}\n{r.abstract or ''}".strip()
            locator = f"pmid:{r.pmid}"
            chunks.append(EvidenceChunk(
                text=text,
                locator=locator,
                citation=Citation(document=f"PMID {r.pmid}",
                                  section=r.topic or "", page=None,
                                  block_id=locator, confidence=0.8),
                score=0.5,  # marcador: el motor re-rankea
                kind="abstract",
            ))
        return RetrievalResult(chunks=chunks, backend=self.name)

    async def list_documents(self) -> list[dict[str, Any]]:
        rows = (self._df.groupBy("topic").count().collect())
        return [{"topic": r.topic, "count": r["count"]} for r in rows]

    async def close(self) -> None:
        self._spark.stop()

    async def health(self) -> dict[str, Any]:
        try:
            n = self._df.count()
            return {"status": "ok", "backend": self.name,
                    "records": n, "delta_path": self.delta_path}
        except Exception as exc:
            return {"status": "error", "reason": f"{type(exc).__name__}",
                    "delta_path": self.delta_path}
