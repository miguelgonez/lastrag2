"""
P0.5 — Control 4 del acta T3: transporte HTTP REAL de la capa FastAPI.
=======================================================================
uvicorn sirviendo app:app en un socket efímero de 127.0.0.1 y llamadas
httpx reales por la red local. GOOGLE_API_KEY se fuerza vacía para que el
arranque sea determinista (sin Gemini): el servidor arranca degradado y
DECLARADO (initialized=false), que es exactamente el comportamiento que
este control debe dejar por escrito. El cableado soberano completo del app
(factory por env + LocalLLM + LastIndex real) queda como deuda declarada
del despliegue, no del transporte.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Antes de importar app: sin clave, initialize() falla y queda declarado.
os.environ.setdefault("GOOGLE_API_KEY", "")

import httpx  # noqa: E402
import pytest  # noqa: E402
import uvicorn  # noqa: E402

pytest.importorskip("fastapi", reason="FastAPI no instalado")


@pytest.fixture(scope="module")
def live_server():
    config = uvicorn.Config("app:app", host="127.0.0.1", port=0,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline:
        if server.started and server.servers:
            port = server.servers[0].sockets[0].getsockname()[1]
            break
        time.sleep(0.1)
    else:
        pytest.fail("uvicorn no arrancó en 15 s")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_home_serves_html_over_real_socket(live_server):
    with httpx.Client(timeout=10) as client:
        response = client.get(live_server + "/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert len(response.content) > 500


def test_status_reports_initialized_state_honestly(live_server):
    with httpx.Client(timeout=10) as client:
        response = client.get(live_server + "/api/status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"initialized", "backend", "active_store", "stores"}
    # Sin clave Gemini el arranque es degradado y el estado lo DECLARA
    # (no finge inicialización ni inventa un backend).
    assert body["initialized"] is False
    assert body["backend"] is None


def test_query_rejects_empty_and_uninitialized_engine(live_server):
    with httpx.Client(timeout=10) as client:
        empty = client.post(live_server + "/api/query", json={"query": "  "})
        no_engine = client.post(live_server + "/api/query",
                                json={"query": "dosis de metformina"})
    assert empty.status_code == 400 and empty.json()["error"] == "Consulta vacía"
    assert no_engine.status_code == 503
    assert no_engine.json()["error"] == "Motor no inicializado"
