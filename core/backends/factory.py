"""
LastRAG v2 — Configuracion y Factory de Backends
================================================
Un solo punto donde el despliegue decide QUE implementacion se inyecta.
El generico no cambia; cambia la config.

  LASTRAG_BACKEND=gemini   -> despliegue cloud / SaaS (corpus sin PHI)
  LASTRAG_BACKEND=qdrant   -> despliegue DGX / local-first (Nexthealth-OS, PHI)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .base import VectorBackend


@dataclass
class Settings:
    backend: str = os.getenv("LASTRAG_BACKEND", "gemini")

    # Gemini
    google_api_key: Optional[str] = os.getenv("GOOGLE_API_KEY")
    gemini_store_name: str = os.getenv("GEMINI_STORE_NAME", "lastrag-knowledge-base")

    # Qdrant
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "lastrag")
    qdrant_api_key: Optional[str] = os.getenv("QDRANT_API_KEY")
    qdrant_vector_size: int = int(os.getenv("QDRANT_VECTOR_SIZE", "768"))

    # Delta (Fase 2 — piloto PubMed, solo lectura, host Spark)
    delta_path: str = os.getenv("DELTA_PATH", "")

    # Neo4j (LastIndex + grafo clinico)
    neo4j_url: str = os.getenv("NEO4J_URL", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "neo4j")

    # LLM de generacion (cloud por defecto; en DGX -> modelo local)
    gen_model: str = os.getenv("LASTRAG_GEN_MODEL", "gemini-2.5-flash")

    # Politica PHI
    phi_mode: bool = os.getenv("LASTRAG_PHI_MODE", "false").lower() == "true"


def build_backend(settings: Optional[Settings] = None) -> VectorBackend:
    """Construye el backend vectorial segun configuracion."""
    settings = settings or Settings()

    if settings.backend == "qdrant":
        from .qdrant_backend import QdrantBackend
        return QdrantBackend(
            url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            api_key=settings.qdrant_api_key,
            vector_size=settings.qdrant_vector_size,
        )

    if settings.backend == "delta":
        # Fase 2 (piloto PubMed): solo lectura, local-first; requiere
        # pyspark+delta en el entorno (host Spark / contenedor).
        from .delta_backend import DeltaBackend
        return DeltaBackend(settings.delta_path)

    if settings.backend == "gemini":
        from .gemini_backend import GeminiFileSearchBackend
        backend = GeminiFileSearchBackend(
            api_key=settings.google_api_key,
            store_display_name=settings.gemini_store_name,
            model=settings.gen_model,
        )
        # Gate PHI: si el despliegue marca phi_mode, no permitir backend cloud.
        if settings.phi_mode and backend.sends_data_to_cloud:
            raise RuntimeError(
                "LASTRAG_PHI_MODE=true exige un backend local-first. "
                "Configura LASTRAG_BACKEND=qdrant."
            )
        return backend

    raise ValueError(f"Backend desconocido: {settings.backend}")
