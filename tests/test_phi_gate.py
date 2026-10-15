"""
P0.5 — Control 7 del acta T3: camino PHI explícito (fail-closed, sin red).
=========================================================================
El gate PHI tiene tres capas y las tres deben fallar CERRADO:
  1. factory: LASTRAG_PHI_MODE=true + backend cloud -> RuntimeError.
  2. contrato: VectorBackend.assert_phi_allowed(True) solo pasa en backends
     con sends_data_to_cloud=False.
  3. pipeline: IngestionPipeline comprueba el gate ANTES de parsear nada.
Ninguna prueba toca la red: el gate se evalúa antes de cualquier cliente.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from core.backends.base import VectorBackend, IngestResult  # noqa: E402
from core.backends.factory import Settings, build_backend  # noqa: E402
from core.backends.qdrant_backend import QdrantBackend  # noqa: E402
from core.ingestion import IngestionPipeline  # noqa: E402


class CloudFake(VectorBackend):
    name = "cloud-fake"
    sends_data_to_cloud = True

    async def initialize(self): ...
    async def ingest(self, file_path, *, document_id, metadata=None):
        return IngestResult(document_id, "ok")
    async def search(self, query, *, top_k=5, metadata_filter=None):
        raise AssertionError("no debe llegarse a buscar con PHI en la nube")
    async def list_documents(self):
        return []


class LocalFake(CloudFake):
    name = "local-fake"
    sends_data_to_cloud = False


def test_phi_mode_factory_blocks_cloud_backend():
    with pytest.raises(RuntimeError, match="LASTRAG_PHI_MODE"):
        build_backend(Settings(backend="gemini", phi_mode=True,
                               google_api_key="dummy-key"))


def test_phi_mode_allows_local_first_backend(tmp_path):
    backend = build_backend(Settings(backend="qdrant", phi_mode=True,
                                     qdrant_url="http://localhost:6333"))
    assert backend.sends_data_to_cloud is False
    backend.assert_phi_allowed(True)  # PHI en local-first: permitido


def test_backend_contract_blocks_phi_to_cloud(tmp_path):
    cloud = CloudFake()
    with pytest.raises(PermissionError):
        cloud.assert_phi_allowed(contains_phi=True)
    cloud.assert_phi_allowed(contains_phi=False)   # sin PHI, la nube es viable
    QdrantBackend(path=str(tmp_path / "q")).assert_phi_allowed(contains_phi=True)


def test_pipeline_checks_phi_gate_before_any_work():
    calls = {"parsed": False}

    class SpyParser:
        def parse(self, *a, **k):
            calls["parsed"] = True
            raise AssertionError("el gate PHI debe saltar ANTES de parsear")

    pipeline = IngestionPipeline(SpyParser(), lastindex=None, backend=CloudFake())
    import asyncio
    with pytest.raises(PermissionError):
        asyncio.run(pipeline.ingest_pdf("x.pdf", contains_phi=True))
    assert calls["parsed"] is False


def test_pipeline_allows_phi_on_local_backend():
    import asyncio
    from unittest.mock import AsyncMock

    local = LocalFake()
    pipeline = IngestionPipeline(parser=None, lastindex=None, backend=local)
    # El gate pasa; el fallo posterior (parser None) es otro asunto.
    with pytest.raises(AttributeError):
        asyncio.run(pipeline.ingest_pdf("x.pdf", contains_phi=True))
