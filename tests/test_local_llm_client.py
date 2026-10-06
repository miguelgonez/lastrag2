"""
P0.5 — LocalLLM: logica de cliente contra un servidor HTTP REAL en proceso.
=============================================================================
ALCANCE DECLARADO: estas pruebas validan el CLIENTE (protocolo OpenAI,
retries, timeout, streaming, health, fail-closed) contra un servidor HTTP
local de verdad. NO constituyen la evidencia del gate FOUNDATION-T3: para
ese gate hace falta un endpoint de modelo real (vLLM/Ollama/LM Studio).
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from core.llm.base import LocalLLM, LocalLLMError  # noqa: E402


class _FakeOpenAIServer:
    """Servidor OpenAI-compatible minimo, con comportamientos programables."""

    def __init__(self, *, chat_fail_times: int = 0, status: int = 500,
                 empty_content: bool = False):
        self.chat_calls = 0
        self.chat_fail_times = chat_fail_times
        self.fail_status = status
        self.empty_content = empty_content
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code: int, payload: dict | str):
                body = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith("/models"):
                    self._send(200, {"data": [
                        {"id": "medgemma-test", "object": "model", "owned_by": "vlab"},
                        {"id": "qwen-test", "object": "model", "owned_by": "vlab"}]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.chat_calls += 1
                if outer.chat_calls <= outer.chat_fail_times:
                    self._send(outer.fail_status, {"error": f"boom {outer.chat_calls}"})
                    return
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for piece in ("La ", "metformina ", "es primera linea."):
                        chunk = {"choices": [{"delta": {"content": piece}}]}
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                content = "" if outer.empty_content else "La metformina es primera linea."
                self._send(200, {"choices": [{"message": {"content": content}}]})

            def log_message(self, *args):
                pass

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


@pytest.fixture
def server():
    srv = _FakeOpenAIServer().start()
    yield srv
    srv.stop()


def test_health_up_and_model_list(server):
    llm = LocalLLM(server.endpoint, model="medgemma-test", max_retries=0)
    health = asyncio.run(llm.health())
    assert health["status"] == "UP"
    assert health["model_available"] is True
    assert "qwen-test" in health["models"]


def test_model_metadata(server):
    llm = LocalLLM(server.endpoint, model="qwen-test", max_retries=0)
    meta = asyncio.run(llm.model_metadata())
    assert meta["status"] == "UP" and meta["id"] == "qwen-test"


def test_generate_non_streaming(server):
    llm = LocalLLM(server.endpoint, max_retries=0)
    text = asyncio.run(llm.generate("¿Tratamiento DM2?"))
    assert "metformina" in text


def test_generate_streaming_aggregates_sse(server):
    llm = LocalLLM(server.endpoint, max_retries=0)
    text = asyncio.run(llm.generate_stream("¿Tratamiento DM2?"))
    assert text == "La metformina es primera linea."


def test_retry_then_success_on_5xx():
    srv = _FakeOpenAIServer(chat_fail_times=2).start()
    try:
        llm = LocalLLM(srv.endpoint, max_retries=2, backoff=0.05)
        text = asyncio.run(llm.generate("¿Tratamiento DM2?"))
        assert "metformina" in text
        assert srv.chat_calls == 3  # 2 fallos + exito: retries limitados y efectivos
    finally:
        srv.stop()


def test_fail_closed_after_exhausted_retries():
    srv = _FakeOpenAIServer(chat_fail_times=99).start()
    try:
        llm = LocalLLM(srv.endpoint, max_retries=1, backoff=0.05)
        with pytest.raises(LocalLLMError) as excinfo:
            asyncio.run(llm.generate("¿Tratamiento DM2?"))
        assert excinfo.value.reason == "HTTP_ERROR"
        assert srv.chat_calls == 2  # 1 intento + 1 retry, ni uno mas
    finally:
        srv.stop()


def test_client_error_4xx_is_not_retried():
    srv = _FakeOpenAIServer(chat_fail_times=99, status=401).start()
    try:
        llm = LocalLLM(srv.endpoint, max_retries=3, backoff=0.05)
        with pytest.raises(LocalLLMError) as excinfo:
            asyncio.run(llm.generate("¿Tratamiento DM2?"))
        assert excinfo.value.reason == "HTTP_ERROR"
        assert srv.chat_calls == 1  # 401 no es reintentable
    finally:
        srv.stop()


def test_empty_response_is_fail_closed_not_success():
    srv = _FakeOpenAIServer(empty_content=True).start()
    try:
        llm = LocalLLM(srv.endpoint, max_retries=0)
        with pytest.raises(LocalLLMError) as excinfo:
            asyncio.run(llm.generate("¿Tratamiento DM2?"))
        assert excinfo.value.reason == "EMPTY_RESPONSE"
    finally:
        srv.stop()


def test_unreachable_endpoint_fails_closed_fast():
    llm = LocalLLM("http://127.0.0.1:9/v1", max_retries=1, backoff=0.05, timeout=2.0)
    health = asyncio.run(llm.health())
    assert health["status"] == "DOWN"
    with pytest.raises(LocalLLMError) as excinfo:
        asyncio.run(llm.generate("¿Tratamiento DM2?"))
    assert excinfo.value.reason == "ENDPOINT_UNREACHABLE"


def test_invalid_endpoint_rejected_at_construction():
    with pytest.raises(LocalLLMError) as excinfo:
        LocalLLM("ftp://no-http.example")
    assert excinfo.value.reason == "INVALID_ENDPOINT"
