"""
LastRAG v2 — Contrato de Backend Vectorial
==========================================
Interfaz comun que TODO backend de recuperacion semantica debe cumplir.

Principio de diseno: el motor RAG (engine.py) nunca conoce la implementacion
concreta. Habla siempre contra `VectorBackend`. Esto permite que el MISMO
codigo generico corra con Gemini File Search (cloud / SaaS) o con Qdrant
(local-first / DGX / PHI) cambiando solo configuracion.

Modelos de datos:
  - Citation        : unidad atomica de trazabilidad (doc/seccion/pagina/bloque)
  - EvidenceChunk   : fragmento de texto recuperado + su Citation
  - RetrievalResult : salida normalizada de cualquier backend

Decision arquitectonica (paridad de citacion):
  La Citation canonica NO la produce el backend vectorial, sino LastIndex
  (el arbol documental en Neo4j). El backend devuelve un `locator` opaco
  (chunk_id / file_id+offset / grounding ref) que LastIndex resuelve a una
  Citation completa. Asi Gemini y Qdrant citan IGUAL: la pagina/seccion sale
  siempre de la estructura propia, no del grounding nativo del proveedor.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ============================================================
# Modelos de datos comunes
# ============================================================

@dataclass
class Citation:
    """
    Unidad atomica de trazabilidad. La resuelve LastIndex a partir del
    `locator` que entrega el backend. Es identica venga de Gemini o Qdrant.
    """
    document: str                       # nombre / id del documento fuente
    chapter: Optional[str] = None       # capitulo (si LastIndex lo conoce)
    section: Optional[str] = None       # seccion / subseccion
    page: Optional[int] = None          # pagina exacta
    block_id: Optional[str] = None      # id del EvidenceBlock en Neo4j
    confidence: float = 0.0             # confianza de la localizacion (0-1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def short(self) -> str:
        parts = [self.document]
        if self.section:
            parts.append(self.section)
        if self.page is not None:
            parts.append(f"p.{self.page}")
        return " · ".join(parts)


@dataclass
class EvidenceChunk:
    """Fragmento textual recuperado mas su localizacion trazable."""
    text: str
    locator: str                        # referencia opaca propia del backend
    citation: Optional[Citation] = None  # la rellena LastIndex (post-retrieval)
    score: float = 0.0                  # score de similaridad del backend
    kind: str = "text"                  # "text" | "table" | "figure" (Ola 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "locator": self.locator,
            "citation": self.citation.to_dict() if self.citation else None,
            "score": self.score,
            "kind": self.kind,
        }


@dataclass
class RetrievalResult:
    """Salida normalizada de cualquier backend vectorial."""
    chunks: list[EvidenceChunk] = field(default_factory=list)
    backend: str = "unknown"            # nombre del backend que respondio
    raw: Any = None                     # respuesta cruda (debug, opcional)
    # P0.5: un error del backend NUNCA se degrada en silencio. Si la busqueda
    # fallo, el resultado llega vacio pero con la razon; el motor la declara
    # en `degradations[]` de la respuesta final.
    degraded_reason: Optional[str] = None

    @property
    def text_evidence(self) -> list[str]:
        return [c.text for c in self.chunks]

    @property
    def citations(self) -> list[Citation]:
        return [c.citation for c in self.chunks if c.citation is not None]

    def is_empty(self) -> bool:
        return len(self.chunks) == 0


@dataclass
class IngestResult:
    """Resultado de indexar un documento en el backend vectorial."""
    document_id: str
    status: str                         # "ok" | "error" | "partial"
    chunks_indexed: int = 0
    message: str = ""
    error: Optional[str] = None


# ============================================================
# Contrato
# ============================================================

class VectorBackend(ABC):
    """
    Interfaz que todo backend de recuperacion semantica debe implementar.

    Implementaciones previstas:
      - GeminiFileSearchBackend  (cloud / SaaS)
      - QdrantBackend            (local-first / DGX / PHI)
      - [futuro] ChromaBackend, PgVectorBackend, ...
    """

    #: identificador estable del backend (usado en logs y en RetrievalResult)
    name: str = "base"

    #: True si el backend mantiene/expone PHI fuera del perimetro local.
    #: El hook gateCloudInferenceForPHI lo consulta para bloquear datos reales.
    sends_data_to_cloud: bool = True

    @abstractmethod
    async def initialize(self) -> None:
        """Prepara conexiones, colecciones o stores. Idempotente."""
        raise NotImplementedError

    @abstractmethod
    async def ingest(
        self,
        file_path: str,
        *,
        document_id: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> IngestResult:
        """
        Indexa un documento. `document_id` debe ser el MISMO que use LastIndex
        para el arbol documental, de modo que los `locator` sean resolubles.
        """
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        metadata_filter: Optional[dict[str, Any]] = None,
    ) -> RetrievalResult:
        """
        Recupera fragmentos semanticamente relevantes. NO genera respuesta.
        Las Citations vienen vacias aqui; LastIndex las resuelve despues.
        """
        raise NotImplementedError

    @abstractmethod
    async def list_documents(self) -> list[dict[str, Any]]:
        """Lista los documentos indexados (id + metadata minima)."""
        raise NotImplementedError

    async def close(self) -> None:
        """Libera recursos. Override opcional."""
        return None

    async def health(self) -> dict[str, Any]:
        """Diagnostico de conectividad del backend (P0.5). Sin retries:
        devuelve estado, nunca lanza. UNKNOWN si el backend no lo implementa."""
        return {"status": "UNKNOWN", "reason": "HEALTH_CHECK_NOT_IMPLEMENTED"}

    # Utilidad comun para validar el gate PHI antes de ingerir datos reales.
    def assert_phi_allowed(self, contains_phi: bool) -> None:
        if contains_phi and self.sends_data_to_cloud:
            raise PermissionError(
                f"Backend '{self.name}' envia datos a la nube; "
                f"bloqueado por gateCloudInferenceForPHI para datos con PHI."
            )
