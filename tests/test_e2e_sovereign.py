"""
P0.5 — E2E SOBERANO (sin mocks en el camino medido).
====================================================
Cadena medida: Query → Router → Recuperacion real (Qdrant local persistente,
embedder de desarrollo declarado) → LastIndex (Neo4j real si
LASTRAG_TEST_NEO4J_URI, degradacion declarada si no) → grade/generación
(LocalLLM real; fail-closed si no hay endpoint).

Verificado 15-oct-2026 contra el Spark: ALIA (vLLM :8024) + lastrag-t3-neo4j
(:17687) → REAL_E2E_PASS. Requisitos de infraestructura: todos los
componentes asíncronos (driver Neo4j, httpx) se crean DENTRO del mismo
asyncio.run que ejecuta la consulta; compartirlos entre bucles de eventos
rompe el driver (lección del 15-oct).

Variables: LASTRAG_E2E_LLM_ENDPOINT, LOCAL_LLM_MODEL,
LASTRAG_E2E_LLM_TIMEOUT, LASTRAG_TEST_NEO4J_URI, LASTRAG_TEST_NEO4J_USER,
LASTRAG_TEST_NEO4J_PASSWORD.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

fitz = pytest.importorskip("fitz", reason="PyMuPDF no disponible")
pytest.importorskip("qdrant_client", reason="QDRANT_CLIENT_NOT_INSTALLED")

from core.backends.qdrant_backend import QdrantBackend  # noqa: E402
from core.embedding import HashingEmbedder  # noqa: E402
from core.lastindex.navigator import LastIndex  # noqa: E402
from core.lastindex.parser import StructuralParser  # noqa: E402
from core.rag.engine import LastRAGEngine  # noqa: E402
from core.llm.base import LocalLLM, LocalLLMError  # noqa: E402

E2E_LLM_ENDPOINT = os.getenv("LASTRAG_E2E_LLM_ENDPOINT")
E2E_NEO4J_URI = os.getenv("LASTRAG_TEST_NEO4J_URI")
E2E_NEO4J_USER = os.getenv("LASTRAG_TEST_NEO4J_USER", "neo4j")
E2E_NEO4J_PASSWORD = os.getenv("LASTRAG_TEST_NEO4J_PASSWORD", "neo4j")
# Sin endpoint: timeout minimo (se espera fail-closed rapido). Con endpoint
# real (vLLM en carga fria): margen generoso.
E2E_LLM_TIMEOUT = float(os.getenv("LASTRAG_E2E_LLM_TIMEOUT",
                                  "120.0" if E2E_LLM_ENDPOINT else "3.0"))

PDF_TEXT_PAGE1 = (
    "Guia sintetica de farmacovigilancia\n"
    "La sepranolona es un neuroesteroide en investigacion para el trastorno "
    "disforico premenstrual. Los ensayos clinicos de fase dos muestran "
    "reduccion de la puntuacion total de sintomas premenstruales frente a "
    "placebo en tratamientos de ciclo corto.\n"
)
PDF_TEXT_PAGE2 = (
    "Seguridad\n"
    "El perfil de seguridad de la sepranolona en los ensayos incluyo somnolencia "
    "transitoria y cefalea leve. No se registraron eventos hepaticos graves "
    "en las poblaciones estudiadas durante los ciclos de tratamiento.\n"
)

QUERY = "que interaccion y seguridad tiene la sepranolona en el tdpm"


@pytest.fixture(scope="module")
def fixture_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("e2e") / "guia_sepranolona.pdf"
    doc = fitz.open()
    for text in (PDF_TEXT_PAGE1, PDF_TEXT_PAGE2):
        page = doc.new_page()
        # insert_textbox envuelve las lineas; insert_text las trunca en el
        # borde de la pagina (los bloques salian cortados a mitad de frase y
        # el grade razonablemente los rechazaba).
        page.insert_textbox(fitz.Rect(50, 60, 545, 780), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture()
def real_stack(fixture_pdf, tmp_path):
    """Parseo real + Qdrant real persistente. Los componentes async (LastIndex,
    LocalLLM) se construyen dentro de cada escenario: un driver compartido
    entre bucles de eventos distintos se rompe."""
    parsed = StructuralParser().parse(fixture_pdf)
    assert parsed.blocks, "el parser real debe producir bloques del PDF real"

    backend = QdrantBackend(
        path=str(tmp_path / "qdrant"), collection="lastrag_e2e",
        embedder=HashingEmbedder(), vector_size=HashingEmbedder.dim,
        embedding_model=HashingEmbedder.model_id,
    )

    def make_lastindex():
        if E2E_NEO4J_URI:
            return LastIndex(E2E_NEO4J_URI, E2E_NEO4J_USER, E2E_NEO4J_PASSWORD)
        return LastIndex("bolt://127.0.0.1:9", "neo4j", "neo4j",
                         connection_timeout=1.5)

    def make_llm():
        return LocalLLM(E2E_LLM_ENDPOINT or "http://127.0.0.1:9/v1",
                        model=os.getenv("LOCAL_LLM_MODEL", "alia-nexthealth"),
                        max_retries=0, timeout=E2E_LLM_TIMEOUT)

    return parsed, backend, make_lastindex, make_llm


def test_sovereign_e2e_chain(real_stack):
    parsed, backend, make_lastindex, make_llm = real_stack

    async def scenario():
        await backend.initialize()
        result = await backend.ingest(
            parsed.source_path, document_id=parsed.document_id,
            metadata={"blocks": [asdict(b) for b in parsed.blocks]},
        )
        assert result.status == "ok" and result.chunks_indexed == len(parsed.blocks)
        lastindex = make_lastindex()
        if E2E_NEO4J_URI:
            await lastindex.setup_schema()
            await lastindex.ingest_tree(parsed)
        engine = LastRAGEngine(backend, lastindex, make_llm())
        try:
            return await engine.run(QUERY)
        finally:
            await lastindex.close()

    if E2E_LLM_ENDPOINT:
        out = asyncio.run(scenario())
        assert out["response"].strip(), "respuesta generada por el LLM real"
        assert out["evidence"], "la respuesta debe apoyarse en evidencia recuperada real"
        for chunk in out["evidence"]:
            assert chunk["locator"].startswith("blk_"), "locator = block_id del arbol"
        if E2E_NEO4J_URI:
            lastindex_degraded = [d for d in out["degradations"]
                                  if d.get("component") == "lastindex"]
            assert not lastindex_degraded, \
                f"con Neo4j real no cabe degradacion de LastIndex: {lastindex_degraded}"
            assert out["citations"], "las citas deben resolverse desde el arbol real"
            assert all(c.get("page") is not None or c.get("section")
                       for c in out["citations"])
    else:
        # Sin endpoint: la cadena llega hasta generacion y FALLA CERRADO
        with pytest.raises(LocalLLMError) as excinfo:
            asyncio.run(scenario())
        assert excinfo.value.reason in {"ENDPOINT_UNREACHABLE", "HTTP_ERROR"}


def test_sovereign_retrieval_real_before_generation(real_stack):
    """La recuperacion real funciona aunque el LLM no exista: se mide por
    debajo del motor, contra Qdrant real, y su salud es UP."""
    parsed, backend, make_lastindex, make_llm = real_stack

    async def scenario():
        await backend.initialize()
        await backend.ingest(
            parsed.source_path, document_id=parsed.document_id,
            metadata={"blocks": [asdict(b) for b in parsed.blocks]},
        )
        result = await backend.search("seguridad sepranolona ensayos", top_k=3)
        health = await backend.health()
        assert result.chunks, "Qdrant real debe recuperar el bloque indexado"
        assert result.chunks[0].locator.startswith("blk_")
        assert health["status"] == "UP"

    asyncio.run(scenario())


def test_engine_degrades_graph_and_lastindex_loudly(real_stack):
    """Con route=graph y sin Neo4j graph manager: hybrid ejecutado y declarado;
    con Neo4j ausente ademas, la degradacion de LastIndex se declara."""
    parsed, backend, make_lastindex, make_llm = real_stack

    async def probe():
        await backend.initialize()
        await backend.ingest(
            parsed.source_path, document_id=parsed.document_id,
            metadata={"blocks": [asdict(b) for b in parsed.blocks]},
        )
        engine = LastRAGEngine(backend, make_lastindex(), make_llm())
        state = {"query": QUERY, "route": "", "route_effective": "",
                 "degradations": [], "chunks": [], "active_graph": [],
                 "resurrected_nodes": [], "external_context": "",
                 "response": "", "confidence": 0.0, "is_general_knowledge": False}
        routed = await engine._route(state)
        state.update(routed)
        graph_out = await engine._graph(state)
        return routed, graph_out

    routed, graph_out = asyncio.run(probe())
    assert routed["route"] == "graph"
    assert graph_out["route_effective"] == "hybrid"
    reasons = {str(d.get("reason")) for d in graph_out["degradations"]}
    assert any("NOT_CONFIGURED" in r for r in reasons) or E2E_NEO4J_URI
    if not E2E_NEO4J_URI:
        assert any(d.get("from_route") == "graph" for d in graph_out["degradations"])
    assert graph_out["chunks"], "hybrid real entrega fragmentos de Qdrant real"
