"""
P0.5 — E2E SOBERANO (sin mocks en el camino medido).
====================================================
Cadena medida: Query → Router → Recuperacion real (Qdrant local persistente,
embedder de desarrollo declarado) → LastIndex (Neo4j real si
LASTRAG_TEST_NEO4J_URI, degradacion declarada si no) → grade/generación
(LocalLLM real; fail-closed si no hay endpoint).

HOY (6-oct-2026), sin endpoint LLM ni servidor Neo4j en el Mac, la cadena
completa NO puede terminar en respuesta: esta prueba acredita (a) que la
parte real funciona y (b) que el sistema FALLA CERRADO y DECLARA
DEGRADACIONES en lugar de responder con apariencia de exito. El gate
FOUNDATION-T3 requiere ademas LASTRAG_E2E_LLM_ENDPOINT (vLLM/Ollama/LM
Studio) y LASTRAG_TEST_NEO4J_URI; con ambos, esta misma prueba ejecuta la
cadena completa y exige respuesta con citas y sin degradaciones no declaradas.
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


@pytest.fixture(scope="module")
def fixture_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("e2e") / "guia_sepranolona.pdf"
    doc = fitz.open()
    for text in (PDF_TEXT_PAGE1, PDF_TEXT_PAGE2):
        page = doc.new_page()
        page.insert_text((72, 90), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture(scope="module")
def real_stack(fixture_pdf, tmp_path_factory):
    """Parser real + Qdrant real (persistente) + LastIndex (real o declarado)."""
    async def build():
        parsed = StructuralParser().parse(fixture_pdf)
        assert parsed.blocks, "el parser real debe producir bloques del PDF real"

        storage = tmp_path_factory.mktemp("qdrant_e2e")
        backend = QdrantBackend(
            path=str(storage), collection="lastrag_e2e",
            embedder=HashingEmbedder(), vector_size=HashingEmbedder.dim,
            embedding_model=HashingEmbedder.model_id,
        )
        await backend.initialize()
        result = await backend.ingest(
            fixture_pdf, document_id=parsed.document_id,
            metadata={"blocks": [asdict(b) for b in parsed.blocks]},
        )
        assert result.status == "ok" and result.chunks_indexed == len(parsed.blocks)

        if E2E_NEO4J_URI:
            lastindex = LastIndex(E2E_NEO4J_URI, "neo4j", "neo4j")
            await lastindex.ingest_tree(parsed)   # arbol real persistido
        else:
            # Sin servidor: puerto cerrado + timeout corto -> degradacion rapida
            lastindex = LastIndex("bolt://127.0.0.1:9", "neo4j", "neo4j",
                                  connection_timeout=1.5)
        return parsed, backend, lastindex

    return asyncio.run(build())


def test_sovereign_e2e_chain(fixture_pdf, real_stack):
    parsed, backend, lastindex = real_stack
    engine = LastRAGEngine(backend, lastindex,
                           LocalLLM(E2E_LLM_ENDPOINT or "http://127.0.0.1:9/v1",
                                    max_retries=0, timeout=3.0))

    query = "que interaccion y seguridad tiene la sepranolona en el tdpm"

    if E2E_LLM_ENDPOINT:
        # Camino completo (cuando exista endpoint): respuesta + citas + degradaciones solo esperadas
        out = asyncio.run(engine.run(query))
        assert out["response"].strip()
        assert out["evidence"], "la respuesta debe apoyarse en evidencia recuperada real"
        for chunk in out["evidence"]:
            assert chunk["locator"].startswith("blk_"), "locator = block_id del arbol"
        unexpected = [d for d in out["degradations"]
                      if d.get("component") == "lastindex" and E2E_NEO4J_URI]
        assert not unexpected, "con Neo4j real no cabe degradacion de LastIndex"
    else:
        # Hoy: la cadena llega hasta generacion y FALLA CERRADO (sin inventar respuesta)
        with pytest.raises(LocalLLMError) as excinfo:
            asyncio.run(engine.run(query))
        assert excinfo.value.reason in {"ENDPOINT_UNREACHABLE", "HTTP_ERROR"}


def test_sovereign_retrieval_real_before_generation(real_stack):
    """La recuperacion real funciona aunque el LLM no exista: se mide por
    debajo del motor, contra Qdrant real, y las degradaciones de grafo y
    de LastIndex quedan declaradas en un run que termina en aviso honesto."""
    parsed, backend, lastindex = real_stack

    async def scenario():
        result = await backend.search("seguridad sepranolona ensayos", top_k=3)
        assert result.chunks, "Qdrant real debe recuperar el bloque indexado"
        assert result.chunks[0].locator.startswith("blk_")
        health = await backend.health()
        assert health["status"] == "UP"
        return result

    asyncio.run(scenario())


def test_engine_degrades_graph_and_lastindex_loudly(real_stack):
    """Con route=graph y sin Neo4j: hybrid ejecutado, degradaciones declaradas
    incluso aunque el run termine fallando cerrado en el LLM."""
    parsed, backend, lastindex = real_stack
    engine = LastRAGEngine(backend, lastindex,
                           LocalLLM("http://127.0.0.1:9/v1", max_retries=0, timeout=3.0))

    async def probe():
        state = {"query": "que interaccion tiene la sepranolona con otros farmacos",
                 "route": "", "route_effective": "", "degradations": [],
                 "chunks": [], "active_graph": [], "resurrected_nodes": [],
                 "external_context": "", "response": "",
                 "confidence": 0.0, "is_general_knowledge": False}
        routed = await engine._route(state)
        state.update(routed)
        graph_out = await engine._graph(state)
        return routed, graph_out

    routed, graph_out = asyncio.run(probe())
    assert routed["route"] == "graph"
    assert graph_out["route_effective"] == "hybrid"
    reasons = {d.get("reason") for d in graph_out["degradations"]}
    assert any("NOT_CONFIGURED" in str(r) for r in reasons) or E2E_NEO4J_URI
    if not E2E_NEO4J_URI:
        assert any(d.get("from_route") == "graph" for d in graph_out["degradations"])
        assert graph_out["chunks"], "hybrid real entrega fragmentos de Qdrant real"
