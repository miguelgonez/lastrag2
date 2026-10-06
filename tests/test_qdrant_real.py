"""
P0.5 — Qdrant REAL (modo local persistente del motor qdrant, sin mocks).
========================================================================
Evidencia del gate FOUNDATION-T3 para el control "Qdrant real": ingesta con
embeddings, busqueda, filtros, top-k, persistencia entre reinicios (cold-start)
y comportamiento ante fallo (degradacion declarada, nunca silenciosa).

Embedder: HashingEmbedder de DESARROLLO (local-hash-ngram-256-v1), declarado en
el payload de cada punto. No mide calidad semantica; mide el camino real.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

qdrant_client = pytest.importorskip(
    "qdrant_client", reason="QDRANT_CLIENT_NOT_INSTALLED (instalar en el venv)"
)

from core.backends.qdrant_backend import QdrantBackend  # noqa: E402
from core.embedding import HashingEmbedder  # noqa: E402

EMB = HashingEmbedder()

DOC_A_BLOCKS = [
    {"block_id": "blk_docA_1", "text": "La metformina es primera linea en diabetes tipo 2 segun la guia.", "page": 1, "section_path": "Tratamiento"},
    {"block_id": "blk_docA_2", "text": "En fallo renal se ajusta la dosis de metformina con cautela.", "page": 2, "section_path": "Precauciones"},
]
DOC_B_BLOCKS = [
    {"block_id": "blk_docB_1", "text": "El ibuprofeno se asocia a gastrolesion en tratamiento prolongado.", "page": 1, "section_path": "AINE"},
]


def make_backend(tmp_path, collection="lastrag_test"):
    return QdrantBackend(
        path=str(tmp_path / "qdrant"),
        collection=collection,
        embedder=EMB,
        vector_size=HashingEmbedder.dim,
        embedding_model=HashingEmbedder.model_id,
    )


async def _ingest_both(backend):
    a = await backend.ingest("docA.pdf", document_id="docA", metadata={"blocks": DOC_A_BLOCKS})
    b = await backend.ingest("docB.pdf", document_id="docB", metadata={"blocks": DOC_B_BLOCKS})
    return a, b


def test_qdrant_real_lifecycle(tmp_path):
    async def scenario():
        backend = make_backend(tmp_path)
        await backend.initialize()

        health = await backend.health()
        assert health["status"] == "UP" and health["collection_ready"]

        a, b = await _ingest_both(backend)
        assert (a.status, a.chunks_indexed) == ("ok", 2)
        assert (b.status, b.chunks_indexed) == ("ok", 1)

        result = await backend.search("dosis metformina diabetes", top_k=5)
        assert not result.degraded_reason
        assert result.chunks, "la busqueda real debe recuperar el documento indexado"
        top = result.chunks[0]
        assert top.locator in {"blk_docA_1", "blk_docA_2"}  # locator == block_id (paridad de cita)
        assert "metformina" in top.text.lower()
        assert 0.0 < top.score <= 1.0               # similitud coseno real

        filtered = await backend.search(
            "metformina", top_k=5, metadata_filter={"document_id": "docB"})
        assert all(c.locator.startswith("blk_docB") for c in filtered.chunks), \
            "el filtro por documento debe excluir docA aunque la query no coincida"

        limited = await backend.search("metformina", top_k=1)
        assert len(limited.chunks) <= 1              # top-k respetado

        docs = await backend.list_documents()
        ids = {d["id"] for d in docs}
        assert ids == {"docA", "docB"}
        await backend.close()
        return True

    assert asyncio.run(scenario())


def test_qdrant_restart_persistence_and_cold_start(tmp_path):
    async def scenario():
        first = make_backend(tmp_path)
        await first.initialize()
        await _ingest_both(first)
        await first.close()                          # apagon total

        second = make_backend(tmp_path)              # arranque en frio sobre disco
        await second.initialize()                    # coleccion YA existente
        cold = await second.health()
        assert cold["status"] == "UP" and cold["collection_ready"]

        result = await second.search("ibuprofeno gastrolesion", top_k=3)
        assert result.chunks and result.chunks[0].locator == "blk_docB_1", \
            "los puntos deben sobrevivir al reinicio del proceso"
        await second.close()
        return True

    assert asyncio.run(scenario())


def test_qdrant_failure_degrades_loudly_not_silently(tmp_path):
    async def scenario():
        uninitialized = make_backend(tmp_path)
        health = await uninitialized.health()
        assert health["status"] == "DOWN" and health["reason"] == "NOT_INITIALIZED"

        result = await uninitialized.search("metformina", top_k=3)
        assert result.chunks == []
        assert result.degraded_reason, \
            "un fallo de Qdrant debe viajar en degraded_reason, no en un print"

        dead_server = QdrantBackend(url="http://127.0.0.1:9", embedder=EMB,
                                    vector_size=HashingEmbedder.dim)
        with pytest.raises(Exception):
            await dead_server.initialize()           # sin servidor: initialize falla cerrado
        return True

    assert asyncio.run(scenario())


def test_qdrant_rejects_path_and_url_at_once(tmp_path):
    with pytest.raises(ValueError):
        QdrantBackend(path=str(tmp_path), url="http://elsewhere:6333")
