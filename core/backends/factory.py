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
from dataclasses import dataclass, field
from typing import Optional

from .base import VectorBackend


def _env(name: str, default: Optional[str] = None):
    """Lectura PEREZOSA del entorno (hallazgo F2 del roadmap post-T3).

    Los defaults se evaluaban al IMPORTAR el modulo, de modo que un cambio de
    entorno posterior (p. ej. activar LASTRAG_PHI_MODE en runtime) no llegaba
    al gate: el control quedaba fijado al estado del proceso en el import.
    Con default_factory cada `Settings()` lee el entorno vigente.
    """
    return field(default_factory=lambda: os.getenv(name, default))


@dataclass
class Settings:
    backend: str = _env("LASTRAG_BACKEND", "gemini")

    # Gemini
    google_api_key: Optional[str] = _env("GOOGLE_API_KEY")
    gemini_store_name: str = _env("GEMINI_STORE_NAME", "lastrag-knowledge-base")

    # Qdrant
    qdrant_url: str = _env("QDRANT_URL", "http://localhost:6333")
    qdrant_collection: str = _env("QDRANT_COLLECTION", "lastrag")
    qdrant_api_key: Optional[str] = _env("QDRANT_API_KEY")
    qdrant_vector_size: int = field(
        default_factory=lambda: int(os.getenv("QDRANT_VECTOR_SIZE", "768")))

    # Delta (Fase 2 — piloto PubMed, solo lectura, host Spark)
    delta_path: str = _env("DELTA_PATH", "")

    # Neo4j (LastIndex + grafo clinico)
    neo4j_url: str = _env("NEO4J_URL", "bolt://localhost:7687")
    neo4j_user: str = _env("NEO4J_USERNAME", "neo4j")
    neo4j_password: str = _env("NEO4J_PASSWORD", "neo4j")

    # LLM de generacion (cloud por defecto; en DGX -> modelo local)
    gen_model: str = _env("LASTRAG_GEN_MODEL", "gemini-2.5-flash")

    # Politica PHI (se evalua en construccion, no en el import)
    phi_mode: bool = field(
        default_factory=lambda: os.getenv("LASTRAG_PHI_MODE", "false").lower() == "true")


def build_backend(settings: Optional[Settings] = None) -> VectorBackend:
    """Construye el backend vectorial segun configuracion."""
    settings = settings or Settings()

    if settings.backend == "qdrant":
        from .qdrant_backend import QdrantBackend
        return _assert_local_first(QdrantBackend(
            url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            api_key=settings.qdrant_api_key,
            vector_size=settings.qdrant_vector_size,
        ), settings)

    if settings.backend == "delta":
        # Fase 2 (piloto PubMed): solo lectura, local-first; requiere
        # pyspark+delta en el entorno (host Spark / contenedor).
        from .delta_backend import DeltaBackend
        return _assert_local_first(DeltaBackend(settings.delta_path), settings)

    if settings.backend == "gemini":
        from .gemini_backend import GeminiFileSearchBackend
        backend = GeminiFileSearchBackend(
            api_key=settings.google_api_key,
            store_display_name=settings.gemini_store_name,
            model=settings.gen_model,
        )
        # Gate PHI: si el despliegue marca phi_mode, no permitir backend cloud.
        return _assert_local_first(backend, settings)

    raise ValueError(f"Backend desconocido: {settings.backend}")


def _assert_local_first(backend: VectorBackend, settings: Settings) -> VectorBackend:
    """Gate PHI del factory: ningun backend que saque datos del perimetro
    puede construirse con LASTRAG_PHI_MODE=true. Se aplica por CAPACIDAD
    declarada del backend (`sends_data_to_cloud`), no por su nombre, para que
    un backend cloud futuro quede cubierto sin tocar este gate."""
    if settings.phi_mode and backend.sends_data_to_cloud:
        raise RuntimeError(
            f"LASTRAG_PHI_MODE=true exige un backend local-first; "
            f"'{backend.name}' declara sends_data_to_cloud=True. "
            "Configura LASTRAG_BACKEND=qdrant."
        )
    return backend
