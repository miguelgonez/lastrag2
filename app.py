"""
LastRAG v2 — Aplicación Web (FastAPI)
=====================================
Interfaz web para interactuar con el motor RAG.
Conecta con Gemini File Search y los stores existentes.

Ejecutar:
    source .venv/bin/activate
    python app.py
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.backends.base import (
    VectorBackend, RetrievalResult, EvidenceChunk, Citation, IngestResult,
)
from core.rag.engine import LastRAGEngine, route_query
from core.llm.base import LLMClient, GeminiLLM
from core.backends.neo4j_graph import Neo4jGraphManager


# ============================================================
# Stub de LastIndex (sin Neo4j — usa citación básica del grounding)
# ============================================================

class PassthroughLastIndex:
    """
    LastIndex ligero que funciona sin Neo4j.
    Resuelve citaciones a partir de lo que trae el backend (grounding metadata).
    Cuando Neo4j esté disponible, se sustituye por el LastIndex real.
    """
    async def enrich_chunks(self, chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
        for c in chunks:
            if c.citation is None and c.locator:
                c.citation = Citation(
                    document=c.locator,
                    confidence=0.6,
                )
        return chunks

    async def structural_search(self, query: str, *, top_k: int = 5) -> list[EvidenceChunk]:
        # Sin Neo4j no hay búsqueda estructural
        return []


# ============================================================
# Inicialización
# ============================================================

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Arranque: intenta inicializar y, si no puede, lo DECLARA en el estado
    (`initialized=false`) en lugar de fingir un sistema operativo.
    (`on_event` está deprecado en FastAPI; el contrato observable no cambia.)"""
    try:
        await initialize()
    except Exception as e:
        print(f"⚠️ Error al inicializar: {e}")
        state["initialized"] = False
    yield


app = FastAPI(title="LastRAG v2", version="2.0.0", lifespan=lifespan)

# Estado global
state: dict[str, Any] = {
    "backend": None,
    "neo4j": None,
    "engine": None,
    "llm": None,
    "stores": [],
    "active_store": None,
    "initialized": False,
}


async def initialize():
    """Inicializa backend Gemini y motor RAG."""
    from core.backends.gemini_backend import GeminiFileSearchBackend

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY no configurada en .env")

    model = os.getenv("LASTRAG_GEN_MODEL", "gemini-2.5-flash")

    # Listar stores existentes
    from google import genai
    client = genai.Client(api_key=api_key)
    stores = list(client.file_search_stores.list())
    state["stores"] = [
        {"name": s.name, "display_name": s.display_name}
        for s in stores
    ]

    # Usar el primer store disponible
    if stores:
        store = stores[0]
        backend = GeminiFileSearchBackend(
            api_key=api_key,
            store_display_name=store.display_name,
            model=model,
        )
        backend.client = client
        backend.store = store
        state["backend"] = backend
        state["active_store"] = store.display_name

    # LLM
    llm = GeminiLLM(api_key=api_key, model=model)
    state["llm"] = llm

    # Neo4j
    neo4j = Neo4jGraphManager()
    state["neo4j"] = neo4j

    # Engine (con PassthroughLastIndex porque Neo4j no está corriendo para índices, pero sí el neo4j_graph)
    if state["backend"]:
        state["engine"] = LastRAGEngine(
            backend=state["backend"],
            lastindex=PassthroughLastIndex(),
            llm=llm,
            neo4j_graph=neo4j,
        )

    state["initialized"] = True
    print(f"✅ LastRAG inicializado — store: {state['active_store']}")
    print(f"   Stores disponibles: {len(state['stores'])}")


# ============================================================
# API Endpoints
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_PAGE


@app.get("/api/status")
async def api_status():
    return {
        "initialized": state["initialized"],
        "active_store": state["active_store"],
        "stores": state["stores"],
        "backend": state["backend"].name if state["backend"] else None,
    }


@app.post("/api/query")
async def api_query(request: Request):
    data = await request.json()
    query = data.get("query", "").strip()
    if not query:
        return JSONResponse({"error": "Consulta vacía"}, status_code=400)

    if not state["engine"]:
        return JSONResponse({"error": "Motor no inicializado"}, status_code=503)

    start = time.time()
    try:
        result = await state["engine"].run(query)
        elapsed = time.time() - start
        result["elapsed_ms"] = int(elapsed * 1000)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/switch-store")
async def switch_store(request: Request):
    data = await request.json()
    store_name = data.get("display_name", "")

    if not store_name:
        return JSONResponse({"error": "Nombre de store requerido"}, status_code=400)

    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    model = os.getenv("LASTRAG_GEN_MODEL", "gemini-2.5-flash")

    for s in client.file_search_stores.list():
        if s.display_name == store_name:
            from core.backends.gemini_backend import GeminiFileSearchBackend
            backend = GeminiFileSearchBackend(
                api_key=api_key,
                store_display_name=s.display_name,
                model=model,
            )
            backend.client = client
            backend.store = s
            state["backend"] = backend
            state["active_store"] = s.display_name
            state["engine"] = LastRAGEngine(
                backend=backend,
                lastindex=PassthroughLastIndex(),
                llm=state["llm"],
                neo4j_graph=state["neo4j"],
            )
            return {"status": "ok", "active_store": s.display_name}

    return JSONResponse({"error": f"Store '{store_name}' no encontrado"}, status_code=404)


def safe_upload_name(raw: Optional[str]) -> Optional[str]:
    """Nombre de fichero seguro para el directorio de subidas.

    El nombre llega del cliente: `upload_dir / file.filename` permitia
    `../../…` y rutas absolutas, es decir ESCRITURA ARBITRARIA en el disco del
    servidor. Se conserva solo el componente final y se rechaza lo que no sea
    un nombre utilizable.
    """
    if not raw:
        return None
    name = PurePosixPath(str(raw).replace("\\", "/")).name
    name = name.strip().strip(".")
    if not name or name in {".", ".."} or "/" in name:
        return None
    return name[:180]


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not state["backend"]:
        return JSONResponse({"error": "Backend no inicializado"}, status_code=503)

    # Gate PHI del transporte: la capa HTTP no puede ser la puerta trasera del
    # control que el pipeline aplica. Con LASTRAG_PHI_MODE=true no se sube
    # nada a un backend que declare salida a la nube.
    if (os.getenv("LASTRAG_PHI_MODE", "false").lower() == "true"
            and getattr(state["backend"], "sends_data_to_cloud", True)):
        return JSONResponse(
            {"error": "LASTRAG_PHI_MODE=true: backend cloud bloqueado para ingesta"},
            status_code=403)

    filename = safe_upload_name(file.filename)
    if not filename:
        return JSONResponse({"error": "Nombre de fichero no válido"}, status_code=400)

    # Guardar temporalmente
    upload_dir = Path("mnt/user-data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / filename
    content = await file.read()
    dest.write_bytes(content)

    try:
        result = await state["backend"].ingest(
            str(dest), document_id=f"doc_{Path(filename).stem}"
        )
        return {
            "status": result.status,
            "document_id": result.document_id,
            "message": result.message or result.error,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/documents")
async def list_documents():
    if not state["backend"]:
        return []
    try:
        return await state["backend"].list_documents()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# HTML / CSS / JS — Single-page application
# ============================================================

HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LastRAG v2 — Hybrid Knowledge Retrieval</title>
<meta name="description" content="Motor RAG híbrido con citación trazable para documentos médicos">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg-primary:#0a0e1a;
  --bg-secondary:#111827;
  --bg-card:#1a2035;
  --bg-card-hover:#1e2642;
  --bg-input:#0d1220;
  --text-primary:#e8ecf4;
  --text-secondary:#8b95a8;
  --text-muted:#5a6577;
  --accent:#6366f1;
  --accent-glow:rgba(99,102,241,.25);
  --accent-soft:rgba(99,102,241,.12);
  --green:#10b981;
  --green-soft:rgba(16,185,129,.12);
  --amber:#f59e0b;
  --amber-soft:rgba(245,158,11,.12);
  --red:#ef4444;
  --red-soft:rgba(239,68,68,.12);
  --cyan:#06b6d4;
  --cyan-soft:rgba(6,182,212,.12);
  --border:rgba(255,255,255,.06);
  --border-hover:rgba(255,255,255,.12);
  --radius:12px;
  --radius-sm:8px;
  --shadow:0 4px 24px rgba(0,0,0,.4);
  --font:'Inter',system-ui,-apple-system,sans-serif;
  --mono:'JetBrains Mono',monospace;
}
html{font-size:15px}
body{
  font-family:var(--font);
  background:var(--bg-primary);
  color:var(--text-primary);
  min-height:100vh;
  line-height:1.6;
  -webkit-font-smoothing:antialiased;
}

/* Layout */
.app{max-width:920px;margin:0 auto;padding:2rem 1.5rem 4rem}

/* Header */
.header{text-align:center;margin-bottom:2.5rem;position:relative}
.header::after{
  content:'';position:absolute;bottom:-1.2rem;left:50%;
  transform:translateX(-50%);width:60px;height:2px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);
  border-radius:2px;
}
.logo{
  font-size:1.8rem;font-weight:700;letter-spacing:-.03em;
  background:linear-gradient(135deg,#818cf8,#6366f1,#4f46e5);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:.3rem;
}
.logo span{font-weight:300;opacity:.7}
.subtitle{color:var(--text-secondary);font-size:.85rem;font-weight:400}

/* Status bar */
.status-bar{
  display:flex;align-items:center;gap:.75rem;
  background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius);padding:.7rem 1rem;margin-bottom:1.5rem;
  font-size:.8rem;flex-wrap:wrap;
}
.status-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.status-dot.online{background:var(--green);box-shadow:0 0 8px rgba(16,185,129,.5)}
.status-dot.offline{background:var(--red)}
.status-label{color:var(--text-secondary)}
.status-value{color:var(--text-primary);font-weight:500}
.store-select{
  margin-left:auto;background:var(--bg-input);color:var(--text-primary);
  border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:.35rem .6rem;font-size:.78rem;font-family:var(--font);
  cursor:pointer;outline:none;
}
.store-select:focus{border-color:var(--accent)}

/* Query box */
.query-box{
  background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius);padding:1.25rem;margin-bottom:1.5rem;
  transition:border-color .2s;
}
.query-box:focus-within{border-color:rgba(99,102,241,.4)}
.query-input{
  width:100%;background:transparent;border:none;outline:none;
  color:var(--text-primary);font-size:1.05rem;font-family:var(--font);
  resize:none;line-height:1.5;min-height:48px;
}
.query-input::placeholder{color:var(--text-muted)}
.query-actions{display:flex;align-items:center;justify-content:space-between;margin-top:.8rem}
.query-hints{display:flex;gap:.4rem;flex-wrap:wrap}
.hint{
  font-size:.7rem;color:var(--text-muted);background:var(--bg-input);
  padding:.2rem .5rem;border-radius:4px;cursor:pointer;
  transition:all .15s;border:1px solid transparent;
}
.hint:hover{color:var(--text-secondary);border-color:var(--border)}
.btn-send{
  background:linear-gradient(135deg,#6366f1,#4f46e5);
  color:#fff;border:none;border-radius:var(--radius-sm);
  padding:.55rem 1.4rem;font-size:.85rem;font-weight:600;
  cursor:pointer;font-family:var(--font);
  transition:all .2s;position:relative;overflow:hidden;
}
.btn-send:hover{transform:translateY(-1px);box-shadow:0 4px 16px var(--accent-glow)}
.btn-send:active{transform:translateY(0)}
.btn-send:disabled{opacity:.5;cursor:not-allowed;transform:none;box-shadow:none}
.btn-send .spinner{
  display:none;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);
  border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;
}
.btn-send.loading .label{display:none}
.btn-send.loading .spinner{display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}

/* Results */
.result-card{
  background:var(--bg-card);border:1px solid var(--border);
  border-radius:var(--radius);padding:1.5rem;margin-bottom:1rem;
  animation:fadeUp .35s ease;
}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

.result-meta{
  display:flex;gap:.6rem;flex-wrap:wrap;margin-bottom:1rem;
}
.meta-tag{
  font-size:.72rem;font-weight:500;padding:.25rem .6rem;
  border-radius:20px;display:flex;align-items:center;gap:.3rem;
}
.meta-tag.route{background:var(--accent-soft);color:#a5b4fc}
.meta-tag.conf-high{background:var(--green-soft);color:var(--green)}
.meta-tag.conf-med{background:var(--amber-soft);color:var(--amber)}
.meta-tag.conf-low{background:var(--red-soft);color:var(--red)}
.meta-tag.time{background:var(--cyan-soft);color:var(--cyan)}
.meta-tag.general{background:var(--amber-soft);color:var(--amber)}

.result-text{
  color:var(--text-primary);line-height:1.75;font-size:.92rem;
  white-space:pre-wrap;
}
.result-text strong{color:#a5b4fc;font-weight:600}
.result-text h1,.result-text h2,.result-text h3{
  color:#c7d2fe;margin:1rem 0 .4rem;font-size:1rem;
}
.result-text ul,.result-text ol{padding-left:1.2rem;margin:.4rem 0}
.result-text code{
  background:var(--bg-input);padding:.15rem .4rem;border-radius:4px;
  font-family:var(--mono);font-size:.82rem;
}

/* Graph Container */
#graphContainer {
  width: 100%;
  height: 350px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 1rem;
  display: none;
}
.graph-title {
  font-size: .8rem;
  font-weight: 600;
  color: #a5b4fc;
  margin-bottom: .5rem;
  display: flex;
  align-items: center;
  gap: .4rem;
}


/* Citations */
.citations{margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)}
.citations-title{
  font-size:.75rem;font-weight:600;color:var(--text-muted);
  text-transform:uppercase;letter-spacing:.06em;margin-bottom:.5rem;
}
.cite{
  display:flex;align-items:flex-start;gap:.5rem;
  padding:.4rem .6rem;background:var(--bg-input);
  border-radius:var(--radius-sm);margin-bottom:.35rem;
  font-size:.78rem;color:var(--text-secondary);
  border-left:2px solid var(--accent);
}
.cite-icon{color:var(--accent);flex-shrink:0;margin-top:1px}

/* Upload section */
.upload-section{
  background:var(--bg-card);border:1px dashed var(--border);
  border-radius:var(--radius);padding:1.2rem;text-align:center;
  margin-bottom:1.5rem;transition:all .2s;cursor:pointer;
}
.upload-section:hover{border-color:var(--accent);background:var(--bg-card-hover)}
.upload-section.dragover{border-color:var(--accent);background:rgba(99,102,241,.08)}
.upload-icon{font-size:1.8rem;margin-bottom:.3rem}
.upload-text{font-size:.82rem;color:var(--text-secondary)}
.upload-text strong{color:var(--text-primary)}
#fileInput{display:none}
.upload-status{
  margin-top:.6rem;font-size:.78rem;padding:.4rem .7rem;
  border-radius:var(--radius-sm);display:none;
}
.upload-status.success{display:block;background:var(--green-soft);color:var(--green)}
.upload-status.error{display:block;background:var(--red-soft);color:var(--red)}

/* Documents list */
.docs-toggle{
  font-size:.8rem;color:var(--text-muted);cursor:pointer;
  padding:.4rem 0;margin-bottom:.5rem;
  display:flex;align-items:center;gap:.3rem;
}
.docs-toggle:hover{color:var(--text-secondary)}
.docs-list{display:none;margin-bottom:1rem}
.docs-list.open{display:block}
.doc-item{
  font-size:.78rem;color:var(--text-secondary);
  padding:.3rem .6rem;background:var(--bg-input);
  border-radius:4px;margin-bottom:.25rem;
  display:flex;align-items:center;gap:.4rem;
}

/* Empty state */
.empty-state{
  text-align:center;padding:3rem 1rem;color:var(--text-muted);
}
.empty-state .icon{font-size:2.5rem;margin-bottom:.8rem;opacity:.5}
.empty-state p{font-size:.88rem;max-width:400px;margin:0 auto}

/* Responsive */
@media(max-width:640px){
  .app{padding:1.2rem 1rem 3rem}
  .header{margin-bottom:2rem}
  .logo{font-size:1.5rem}
  .status-bar{flex-direction:column;align-items:flex-start;gap:.4rem}
  .store-select{margin-left:0;width:100%}
  .query-actions{flex-direction:column;gap:.6rem;align-items:stretch}
  .query-hints{justify-content:center}
  .btn-send{width:100%}
}
</style>
</head>
<body>
<div class="app">

  <!-- Header -->
  <header class="header">
    <div class="logo">LastRAG <span>v2</span></div>
    <p class="subtitle">Hybrid Knowledge Retrieval · Citación trazable</p>
  </header>

  <!-- Status -->
  <div class="status-bar" id="statusBar">
    <span class="status-dot" id="statusDot"></span>
    <span class="status-label">Backend:</span>
    <span class="status-value" id="statusBackend">cargando…</span>
    <span class="status-label">│ Store:</span>
    <select class="store-select" id="storeSelect" title="File Search Store activo"></select>
  </div>

  <!-- Upload -->
  <div class="upload-section" id="uploadZone" onclick="document.getElementById('fileInput').click()">
    <div class="upload-icon">📄</div>
    <div class="upload-text"><strong>Arrastra un PDF</strong> o haz clic para subir al store activo</div>
    <input type="file" id="fileInput" accept=".pdf">
    <div class="upload-status" id="uploadStatus"></div>
  </div>

  <!-- Documents toggle -->
  <div class="docs-toggle" id="docsToggle" onclick="toggleDocs()">
    <span>▸</span> Documentos indexados
  </div>
  <div class="docs-list" id="docsList"></div>

  <!-- Query -->
  <div class="query-box">
    <textarea class="query-input" id="queryInput" rows="2"
              placeholder="Haz una pregunta sobre los documentos…"
              onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendQuery()}"></textarea>
    <div class="query-actions">
      <div class="query-hints">
        <span class="hint" onclick="setQuery('¿Cuál es el tratamiento de primera línea para diabetes tipo 2?')">💊 Tratamiento DM2</span>
        <span class="hint" onclick="setQuery('¿En qué página aparece la dosificación de metformina?')">📑 Localizar sección</span>
        <span class="hint" onclick="setQuery('¿Qué relación hay entre ERC y diabetes?')">🔗 Relaciones</span>
      </div>
      <button class="btn-send" id="btnSend" onclick="sendQuery()">
        <span class="label">Consultar</span>
        <span class="spinner"></span>
      </button>
    </div>
  </div>

  <!-- Results -->
  <div id="results">
    <div class="empty-state">
      <div class="icon">🔍</div>
      <p>Escribe una consulta para buscar en tus documentos médicos con citación trazable</p>
    </div>
  </div>

</div>

<script>
const $ = s => document.querySelector(s);
const API = '';

// Init
async function init() {
  try {
    const r = await fetch(API + '/api/status');
    const d = await r.json();
    const dot = $('#statusDot');
    const backend = $('#statusBackend');
    const select = $('#storeSelect');

    if (d.initialized) {
      dot.className = 'status-dot online';
      backend.textContent = d.backend || 'gemini';
      select.innerHTML = d.stores.map(s =>
        `<option value="${s.display_name}" ${s.display_name === d.active_store ? 'selected' : ''}>${s.display_name}</option>`
      ).join('');
      select.onchange = () => switchStore(select.value);
      loadDocs();
    } else {
      dot.className = 'status-dot offline';
      backend.textContent = 'error';
    }
  } catch(e) {
    $('#statusDot').className = 'status-dot offline';
    $('#statusBackend').textContent = 'desconectado';
  }
}

// Switch store
async function switchStore(name) {
  try {
    const r = await fetch(API + '/api/switch-store', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({display_name: name})
    });
    if (r.ok) { loadDocs(); }
  } catch(e) { console.error(e); }
}

// Query
async function sendQuery() {
  const input = $('#queryInput');
  const query = input.value.trim();
  if (!query) return;

  const btn = $('#btnSend');
  btn.classList.add('loading');
  btn.disabled = true;

  try {
    const r = await fetch(API + '/api/query', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({query})
    });
    const d = await r.json();

    if (d.error) {
      showError(d.error);
    } else {
      showResult(query, d);
    }
  } catch(e) {
    showError(e.message);
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
}

function showResult(query, d) {
  const confClass = d.confidence >= 0.7 ? 'conf-high' : d.confidence >= 0.4 ? 'conf-med' : 'conf-low';
  const confLabel = Math.round(d.confidence * 100) + '%';

  let citesHtml = '';
  if (d.citations && d.citations.length > 0) {
    citesHtml = `
      <div class="citations">
        <div class="citations-title">📋 Citaciones (${d.citations.length})</div>
        ${d.citations.map(c => `
          <div class="cite">
            <span class="cite-icon">›</span>
            <span>${c.document || ''}${c.section ? ' · ' + c.section : ''}${c.page ? ' · p.' + c.page : ''}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  const uniqueId = Date.now().toString();

  const html = `
    <div class="result-card">
      <div class="result-meta">
        <span class="meta-tag route">🧭 ${d.route}</span>
        <span class="meta-tag ${confClass}">⚡ ${confLabel} confianza</span>
        <span class="meta-tag time">⏱ ${d.elapsed_ms || '?'}ms</span>
        ${d.evidence_count ? `<span class="meta-tag route">📄 ${d.evidence_count} fragmentos</span>` : ''}
        ${d.active_graph && d.active_graph.length > 0 ? `<span class="meta-tag route" style="background:var(--accent-soft);color:var(--accent)">🕸️ Grafo Clínico</span>` : ''}
        ${d.is_general_knowledge ? '<span class="meta-tag general">⚠️ Conocimiento general</span>' : ''}
      </div>
      
      ${d.active_graph && d.active_graph.length > 0 ? `
        <div class="graph-title">🕸️ Grafo de Conocimiento Médico</div>
        <div id="graphContainer_${uniqueId}" style="width: 100%; height: 350px; background: var(--bg-input); border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 1rem;"></div>
      ` : ''}

      <div class="result-text">${formatResponse(d.response)}</div>
      ${citesHtml}
    </div>
  `;
  $('#results').innerHTML = html + $('#results').innerHTML.replace(/<div class="empty-state">.*?<\\/div>/s, '');
  
  if (d.active_graph && d.active_graph.length > 0) {
     renderGraph(d.active_graph, `graphContainer_${uniqueId}`);
  }
}

  const confClass = d.confidence >= 0.7 ? 'conf-high' : d.confidence >= 0.4 ? 'conf-med' : 'conf-low';
  const confLabel = Math.round(d.confidence * 100) + '%';

  let citesHtml = '';
  if (d.citations && d.citations.length > 0) {
    citesHtml = `
      <div class="citations">
        <div class="citations-title">📋 Citaciones (${d.citations.length})</div>
        ${d.citations.map(c => `
          <div class="cite">
            <span class="cite-icon">›</span>
            <span>${c.document || ''}${c.section ? ' · ' + c.section : ''}${c.page ? ' · p.' + c.page : ''}</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  const uniqueId = Date.now().toString();

  const html = `
    <div class="result-card">
      <div class="result-meta">
        <span class="meta-tag route">🧭 ${d.route}</span>
        <span class="meta-tag ${confClass}">⚡ ${confLabel} confianza</span>
        <span class="meta-tag time">⏱ ${d.elapsed_ms || '?'}ms</span>
        ${d.evidence_count ? `<span class="meta-tag route">📄 ${d.evidence_count} fragmentos</span>` : ''}
        ${d.active_graph && d.active_graph.length > 0 ? `<span class="meta-tag route" style="background:var(--accent-soft);color:var(--accent)">🕸️ Grafo Clínico</span>` : ''}
        ${d.is_general_knowledge ? '<span class="meta-tag general">⚠️ Conocimiento general</span>' : ''}
      </div>
      
      ${d.active_graph && d.active_graph.length > 0 ? `
        <div class="graph-title">🕸️ Grafo de Conocimiento Médico</div>
        <div id="graphContainer_${uniqueId}" style="width: 100%; height: 350px; background: var(--bg-input); border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 1rem;"></div>
      ` : ''}

      <div class="result-text">${formatResponse(d.response)}</div>
      ${citesHtml}
    </div>
  `;
  $('#results').innerHTML = html + $('#results').innerHTML.replace(/<div class="empty-state">.*?<\\/div>/s, '');
  
  if (d.active_graph && d.active_graph.length > 0) {
     renderGraph(d.active_graph, `graphContainer_${uniqueId}`);
  }
}

function renderGraph(graphData, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  
  let nodesData = [];
  let edgesData = [];
  let nodeIds = new Set();
  let edgeIds = new Set();

  graphData.forEach(node => {
    if (!nodeIds.has(node.name)) {
      // Define colors based on type
      let color = { background: '#4f46e5', border: '#818cf8' }; // Default
      if (node.type === 'Disease') color = { background: '#ef4444', border: '#f87171' };
      else if (node.type === 'Treatment') color = { background: '#10b981', border: '#34d399' };
      else if (node.type === 'Drug') color = { background: '#f59e0b', border: '#fbbf24' };
      else if (node.type === 'Symptom') color = { background: '#8b5cf6', border: '#a78bfa' };
      else if (node.type === 'Biomarker') color = { background: '#06b6d4', border: '#22d3ee' };

      nodesData.push({ 
        id: node.name, 
        label: node.name, 
        group: node.type, 
        title: node.desc || node.type,
        color: color,
        font: { color: '#ffffff' },
        shape: 'box',
        margin: 10,
        borderWidth: 2
      });
      nodeIds.add(node.name);
    }
    
    if (node.targets && Array.isArray(node.targets)) {
      node.targets.forEach(target => {
        if (!nodeIds.has(target)) {
           nodesData.push({ 
             id: target, 
             label: target,
             font: { color: '#ffffff' },
             color: { background: '#374151', border: '#4b5563' },
             shape: 'box',
             margin: 10
           });
           nodeIds.add(target);
        }
        let edgeId = node.name + '-' + target;
        if (!edgeIds.has(edgeId)) {
          edgesData.push({ 
            from: node.name, 
            to: target, 
            arrows: 'to',
            color: { color: 'rgba(255,255,255,0.2)', highlight: 'rgba(255,255,255,0.6)' },
            smooth: { type: 'continuous' }
          });
          edgeIds.add(edgeId);
        }
      });
    }
  });

  const data = {
    nodes: new vis.DataSet(nodesData),
    edges: new vis.DataSet(edgesData)
  };
  const options = {
    physics: {
      forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.01, springLength: 100, springConstant: 0.08 },
      maxVelocity: 50,
      solver: 'forceAtlas2Based',
      timestep: 0.35,
      stabilization: { iterations: 150 }
    },
    interaction: { hover: true, tooltipDelay: 200 }
  };
  
  new vis.Network(container, data, options);
}

function showError(msg) {
  $('#results').innerHTML = `
    <div class="result-card" style="border-color:var(--red)">
      <div class="result-meta"><span class="meta-tag conf-low">❌ Error</span></div>
      <div class="result-text">${escapeHtml(msg)}</div>
    </div>
  ` + $('#results').innerHTML;
}

function formatResponse(text) {
  // Markdown básico
  let h = escapeHtml(text);
  h = h.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  h = h.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  h = h.replace(/^# (.+)$/gm, '<h2>$1</h2>');
  h = h.replace(/^- (.+)$/gm, '• $1');
  h = h.replace(/^(\\d+)\\. (.+)$/gm, '$1. $2');
  return h;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function setQuery(q) {
  $('#queryInput').value = q;
  $('#queryInput').focus();
}

// Upload
const uploadZone = $('#uploadZone');
const fileInput = $('#fileInput');

['dragenter','dragover'].forEach(e => uploadZone.addEventListener(e, ev => {
  ev.preventDefault(); uploadZone.classList.add('dragover');
}));
['dragleave','drop'].forEach(e => uploadZone.addEventListener(e, ev => {
  ev.preventDefault(); uploadZone.classList.remove('dragover');
}));
uploadZone.addEventListener('drop', ev => {
  const file = ev.dataTransfer.files[0];
  if (file) uploadFile(file);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

async function uploadFile(file) {
  const status = $('#uploadStatus');
  status.className = 'upload-status';
  status.style.display = 'block';
  status.textContent = '⏳ Subiendo e indexando ' + file.name + '…';
  status.className = 'upload-status';
  status.style.display = 'block';
  status.style.background = 'var(--cyan-soft)';
  status.style.color = 'var(--cyan)';

  const fd = new FormData();
  fd.append('file', file);

  try {
    const r = await fetch(API + '/api/upload', {method:'POST', body:fd});
    const d = await r.json();
    if (d.status === 'ok') {
      status.className = 'upload-status success';
      status.textContent = '✅ ' + file.name + ' indexado correctamente';
      loadDocs();
    } else {
      status.className = 'upload-status error';
      status.textContent = '❌ ' + (d.error || d.message || 'Error');
    }
  } catch(e) {
    status.className = 'upload-status error';
    status.textContent = '❌ ' + e.message;
  }
}

// Documents
async function loadDocs() {
  try {
    const r = await fetch(API + '/api/documents');
    const docs = await r.json();
    const list = $('#docsList');
    if (docs.length) {
      list.innerHTML = docs.map(d =>
        `<div class="doc-item">📄 ${d.id || d.name}${d.chunks ? ' · ' + d.chunks + ' chunks' : ''}</div>`
      ).join('');
    } else {
      list.innerHTML = '<div class="doc-item" style="color:var(--text-muted)">Sin documentos</div>';
    }
  } catch(e) {}
}

function toggleDocs() {
  const list = $('#docsList');
  const toggle = $('#docsToggle');
  list.classList.toggle('open');
  toggle.querySelector('span').textContent = list.classList.contains('open') ? '▾' : '▸';
}

init();
</script>
</body>
</html>"""


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print("🚀 LastRAG v2 — http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
