"""
Regresiones de la auditoría de calidad del 22-oct-2026.
=======================================================
Una prueba por defecto corregido (expediente: `AUDITORIA_CALIDAD_20261022.md`).
Cada una fija el comportamiento CORRECTO para que el defecto no pueda volver
en silencio. Alcance declarado: son pruebas de contrato y de lógica con dobles
y servidores reales en proceso; no acreditan calidad clínica ni semántica, ni
sustituyen al gate FOUNDATION-T3.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from core.backends.base import (  # noqa: E402
    Citation, EvidenceChunk, IngestResult, RetrievalResult, VectorBackend,
)
from core.backends.factory import Settings, build_backend  # noqa: E402
from core.backends.qdrant_backend import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL, QdrantBackend,
)
from core.embedding import HashingEmbedder  # noqa: E402
from core.lastindex import schema as lastindex_schema  # noqa: E402
from core.llm.base import LLMClient, LocalLLM, LocalLLMError  # noqa: E402
from core.rag.causal import CAUSAL_SUPPORTED, classify_claims  # noqa: E402
from core.rag.engine import LastRAGEngine  # noqa: E402
from core.rag.failure_graph import INSUFFICIENT_EVIDENCE  # noqa: E402
from core.rag.fusion import fuse_by_locator  # noqa: E402
from core.rag.multimodal import _docling_page_no  # noqa: E402
from core.rag.pack import extract_claims  # noqa: E402
from core.rag.rerank import ClinicalReranker  # noqa: E402
from core.rag.temporal import temporal_filter  # noqa: E402
from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM  # noqa: E402


# ============================================================
# 1 · Gate PHI: el entorno se lee al construir, no al importar
# ============================================================

def test_settings_lee_el_entorno_en_cada_construccion(monkeypatch):
    """F2 del roadmap post-T3: los defaults se evaluaban en el import, así que
    activar el modo PHI después no llegaba al gate."""
    monkeypatch.setenv("LASTRAG_PHI_MODE", "true")
    monkeypatch.setenv("LASTRAG_BACKEND", "qdrant")
    assert Settings().phi_mode is True
    assert Settings().backend == "qdrant"
    monkeypatch.setenv("LASTRAG_PHI_MODE", "false")
    assert Settings().phi_mode is False


def test_phi_mode_activado_en_runtime_bloquea_backend_cloud(monkeypatch):
    monkeypatch.setenv("LASTRAG_PHI_MODE", "true")
    monkeypatch.setenv("LASTRAG_BACKEND", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key")
    with pytest.raises(RuntimeError, match="LASTRAG_PHI_MODE"):
        build_backend()          # sin pasar Settings: el gate lee el entorno vivo


def test_gate_phi_se_aplica_por_capacidad_declarada(monkeypatch):
    """El gate mira `sends_data_to_cloud`, no el nombre del backend."""
    from core.backends import factory

    class CloudFake(VectorBackend):
        name = "cloud-fake"
        sends_data_to_cloud = True
        async def initialize(self): ...
        async def ingest(self, file_path, *, document_id, metadata=None):
            return IngestResult(document_id, "ok")
        async def search(self, query, *, top_k=5, metadata_filter=None):
            return RetrievalResult(backend=self.name)
        async def list_documents(self):
            return []

    with pytest.raises(RuntimeError, match="sends_data_to_cloud"):
        factory._assert_local_first(CloudFake(), Settings(phi_mode=True))


# ============================================================
# 2 · Ningún backend devuelve "sin evidencia" cuando falló
# ============================================================

def test_gemini_sin_store_declara_degradacion_no_vacio():
    from core.backends.gemini_backend import GeminiFileSearchBackend

    backend = GeminiFileSearchBackend(api_key=None)
    result = asyncio.run(backend.search("dosis de metformina"))
    assert result.chunks == []
    assert result.degraded_reason.startswith("GEMINI_NOT_INITIALIZED")


def test_gemini_error_del_sdk_viaja_en_degraded_reason():
    from core.backends.gemini_backend import GeminiFileSearchBackend

    class BoomModels:
        def generate_content(self, **kwargs):
            raise TimeoutError("sdk caído")

    class BoomClient:
        models = BoomModels()

    backend = GeminiFileSearchBackend(api_key="x")
    backend.client = BoomClient()
    backend.store = type("S", (), {"name": "stores/demo"})()
    result = asyncio.run(backend.search("dosis de metformina"))
    assert result.chunks == []
    assert result.degraded_reason == "GEMINI_ERROR:TimeoutError"


def test_qdrant_fallo_del_embedder_se_declara(tmp_path):
    def boom(texts):
        raise RuntimeError("modelo de embeddings ausente")

    backend = QdrantBackend(path=str(tmp_path / "q"), embedder=boom,
                            embedding_model="boom-v0")
    result = asyncio.run(backend.search("metformina"))
    assert result.chunks == []
    assert result.degraded_reason == "EMBEDDER_ERROR:RuntimeError"


def test_qdrant_ingesta_con_embedder_roto_no_lanza(tmp_path):
    def boom(texts):
        raise RuntimeError("modelo de embeddings ausente")

    backend = QdrantBackend(path=str(tmp_path / "q2"), embedder=boom,
                            embedding_model="boom-v0")
    out = asyncio.run(backend.ingest(
        "x.pdf", document_id="doc_x",
        metadata={"blocks": [{"block_id": "b1", "text": "t"}]}))
    assert out.status == "error" and "EMBEDDER_ERROR" in out.error


# ============================================================
# 3 · Procedencia del embedding: nunca "unknown" por omisión
# ============================================================

def test_etiqueta_de_embedding_se_deriva_del_embedder(tmp_path):
    inyectado = QdrantBackend(path=str(tmp_path / "a"), embedder=HashingEmbedder())
    por_defecto = QdrantBackend(path=str(tmp_path / "b"))
    declarado = QdrantBackend(path=str(tmp_path / "c"), embedder=HashingEmbedder(),
                              embedding_model="pubmedbert-es-v2")
    assert inyectado.embedding_model == HashingEmbedder.model_id
    assert por_defecto.embedding_model == DEFAULT_EMBEDDING_MODEL
    assert declarado.embedding_model == "pubmedbert-es-v2"  # lo declarado manda


# ============================================================
# 4 · Nodo grade: descartar evidencia es una decisión declarada
# ============================================================

class _GradeLLM(LLMClient):
    name = "grade-fake"

    def __init__(self, verdict: str):
        self.verdict = verdict

    async def generate(self, prompt, *, max_tokens=8192):
        if "Pregunta de examen" in prompt:
            return self.verdict
        return "Respuesta con la evidencia proporcionada."


def _run(verdict: str) -> dict:
    engine = LastRAGEngine(FakeBackend(), FakeLastIndex(), _GradeLLM(verdict))
    return asyncio.run(engine.run("tratamiento de la diabetes tipo 2"))


def test_grade_descarta_evidencia_y_lo_declara():
    out = _run("B")
    assert out["evidence"] == []
    assert any(d.get("component") == "grade"
               and d.get("reason") == "DOMAIN_IRRELEVANT"
               for d in out["degradations"]), \
        "descartar evidencia sin declararlo es indistinguible de no recuperarla"
    assert out["features"]["grade"]["discarded"] >= 1
    # Taxonomía de la ausencia: NO es un fallo de recuperación
    assert out["absence"]["type"] == INSUFFICIENT_EVIDENCE
    assert "grade" in out["absence"]["detail"]


def test_grade_valida_evidencia_sin_degradacion_espuria():
    out = _run("A")
    assert out["evidence"], "con veredicto A la evidencia se conserva"
    assert out["features"]["grade"]["verdict"] == "A"
    assert not [d for d in out["degradations"]
                if d.get("reason") == "UNDECIDABLE_VERDICT"]


def test_grade_indecible_conserva_evidencia_y_lo_declara():
    out = _run("quizá sí, quizá no")
    assert out["evidence"], "un veredicto ilegible no descarta evidencia válida"
    assert any(d.get("reason") == "UNDECIDABLE_VERDICT"
               for d in out["degradations"])
    assert out["features"]["grade"]["verdict"] is None


def test_veredicto_tolera_adornos_pero_no_adivina():
    assert LastRAGEngine._normalize_verdict("**A)**").startswith("A")
    assert LastRAGEngine._normalize_verdict(" «B» ").startswith("B")
    indecible = LastRAGEngine._normalize_verdict("La opción correcta es la A")
    assert not indecible.startswith(("A", "B"))


# ============================================================
# 5 · Streaming: un corte a mitad no duplica lo ya entregado
# ============================================================

class _TruncatedSSEServer:
    """Anuncia más bytes de los que escribe y cierra: el cliente ve el stream
    roto DESPUÉS de haber recibido deltas."""

    def __init__(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"data": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                self.rfile.read(length)
                outer.calls += 1
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", "4096")  # miente: cierra antes
                self.end_headers()
                for piece in ("La ", "metformina "):
                    chunk = {"choices": [{"delta": {"content": piece}}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *args):
                pass

        self.calls = 0
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_stream_interrumpido_falla_cerrado_sin_reemitir():
    srv = _TruncatedSSEServer().start()
    try:
        llm = LocalLLM(srv.endpoint, max_retries=3, backoff=0.01, timeout=5.0)

        async def consume():
            out = []
            with pytest.raises(LocalLLMError) as excinfo:
                async for delta in llm.stream_deltas("¿Tratamiento DM2?"):
                    out.append(delta)
            return out, excinfo.value

        deltas, error = asyncio.run(consume())
        assert error.reason == "STREAM_INTERRUPTED"
        assert deltas == ["La ", "metformina "], "lo entregado no se repite"
        assert srv.calls == 1, "tras emitir deltas no puede haber reintento"
    finally:
        srv.stop()


# ============================================================
# 6 · Jerarquía causal: el mapa se indexa por locator
# ============================================================

def test_classify_claims_indexa_por_locator_y_etiqueta_el_pack():
    chunks = [EvidenceChunk(
        text=("Ensayo aleatorizado doble ciego: la metformina reduce la "
              "hemoglobina glucosilada frente a placebo."),
        locator="blk_rct", score=1.0)]
    niveles = classify_claims(extract_claims(chunks))
    assert niveles == {"blk_rct": CAUSAL_SUPPORTED}
    # El mapa alimenta de verdad el Evidence Pack (antes no casaba ninguna clave)
    etiquetados = extract_claims(chunks, causal_levels=niveles)
    assert etiquetados and etiquetados[0].causal_level == CAUSAL_SUPPORTED


# ============================================================
# 7 · El "ahora" sale del reloj, no de una constante
# ============================================================

def test_vigencia_temporal_contra_el_ano_en_curso():
    ahora = date.today().year
    chunks = [EvidenceChunk(text="guía caducada", locator="vieja"),
              EvidenceChunk(text="guía vigente", locator="nueva")]
    meta = {"vieja": {"valid_until": ahora - 1},
            "nueva": {"valid_from": ahora - 2}}
    dec = temporal_filter(chunks, meta, "¿qué recomienda la guía?")
    assert {c.locator for c in dec.kept} == {"nueva"}
    assert dec.dropped[0]["reason"] == f"EXPIRED:{ahora - 1}"


def test_reranker_mide_actualidad_contra_el_ano_en_curso():
    assert ClinicalReranker().now_year == date.today().year


# ============================================================
# 8 · Procedencia de la cita: página real y documento correcto
# ============================================================

def test_pagina_docling_se_lee_del_nombre_vigente():
    class Prov:
        page_no = 7

    class Item:
        prov = [Prov()]

    assert _docling_page_no(Item()) == 7
    assert _docling_page_no(type("X", (), {"prov": []})()) == 1


def test_resolve_citation_acota_el_capitulo_al_documento():
    """Verificación ESTÁTICA del Cypher (no hay Neo4j en este entorno): el
    capítulo debe buscarse dentro del mismo document_id, porque `path` solo es
    único por (document_id, path)."""
    cypher = lastindex_schema.RESOLVE_CITATION
    seccion = cypher.split("OPTIONAL MATCH (ch:Chapter")[1]
    assert seccion.count("document_id: b.document_id") >= 2


# ============================================================
# 9 · Fusión: una sola implementación
# ============================================================

def test_fuse_del_motor_delega_en_fusion_por_locator():
    sem = [EvidenceChunk(text="semantico", locator="blk_a", score=0.9)]
    struct = [EvidenceChunk(text="estructural", locator="blk_a", score=2.0,
                            citation=Citation(document="d", page=3))]
    fundido = LastRAGEngine._fuse(sem, struct)
    assert [c.text for c in fundido] == [c.text for c in fuse_by_locator(struct, sem)]
    assert fundido[0].citation is not None, "gana la vía con citación exacta"


# ============================================================
# 10 · Transporte: el nombre de fichero no es una ruta
# ============================================================

def test_nombre_de_subida_no_permite_escribir_fuera_del_directorio():
    pytest.importorskip("fastapi", reason="FastAPI no instalado")
    from app import safe_upload_name

    assert safe_upload_name("../../../etc/passwd") == "passwd"
    assert safe_upload_name("/tmp/absoluto.pdf") == "absoluto.pdf"
    assert safe_upload_name("..\\..\\windows\\system32\\x.pdf") == "x.pdf"
    assert safe_upload_name("guia.pdf") == "guia.pdf"
    for malo in ("", "   ", "..", "../", None):
        assert safe_upload_name(malo) is None


# ============================================================
# 11 · Backend Delta: vocabulario del contrato de salud
# ============================================================

def test_delta_health_usa_el_vocabulario_del_contrato():
    pytest.importorskip("pyspark", reason="pyspark no instalado (skip declarado)")
    from core.backends.delta_backend import DeltaBackend

    backend = DeltaBackend.__new__(DeltaBackend)   # sin SparkSession
    backend.delta_path = "/no/existe"
    backend._df = type("DF", (), {"count": lambda self: (_ for _ in ()).throw(
        RuntimeError("delta ausente"))})()
    estado = asyncio.run(backend.health())
    assert estado["status"] == "DOWN"
    assert estado["reason"].startswith("DELTA_ERROR")


# ============================================================
# 12 · Generación cloud: no se bloquea el bucle de eventos
# ============================================================

def test_gemini_llm_no_bloquea_el_event_loop():
    from core.llm.base import GeminiLLM

    hilos: list[int] = []

    class FakeModels:
        def generate_content(self, **kwargs):
            hilos.append(threading.get_ident())
            return type("R", (), {"text": "respuesta"})()

    llm = GeminiLLM(api_key="x")
    llm._client = type("C", (), {"models": FakeModels()})()

    async def run():
        principal = threading.get_ident()
        texto = await llm.generate("hola")
        return principal, texto

    principal, texto = asyncio.run(run())
    assert texto == "respuesta"
    assert hilos and hilos[0] != principal, \
        "el SDK síncrono debe ejecutarse fuera del hilo del loop"


# ============================================================
# 13 · El doble del LLM habla el formato del grade
# ============================================================

def test_el_doble_responde_el_grade_en_su_formato():
    llm = FakeLLM(grade="B")
    out = asyncio.run(LastRAGEngine(FakeBackend(), FakeLastIndex(), llm)
                      .run("tratamiento de la diabetes tipo 2"))
    assert out["features"]["grade"]["verdict"] == "B"
    assert any("Pregunta de examen" in p for p in llm.prompts)
