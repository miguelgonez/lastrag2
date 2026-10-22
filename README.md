# LastRAG v2 — Núcleo genérico (Hybrid Knowledge Retrieval)

Versión genérica, dominio-agnóstica y desacoplada de infraestructura.
Se especializa por **configuración**, no por fork. El despliegue concreto
(p. ej. Nexthealth-OS sobre DGX) cambia el backend vectorial y el LLM sin
tocar el motor.

## Decisión arquitectónica central

**LastIndex (PageIndex propio) es la fuente ÚNICA de citación para todos los
backends.** El backend vectorial devuelve un `locator = block_id`; LastIndex lo
resuelve a `Citation` (documento → sección → página → bloque). Así Gemini File
Search y Qdrant **citan idéntico**, y la trazabilidad no depende del grounding
nativo de ningún proveedor. Esto es lo que hace viable el camino PHI: en local
(Qdrant) no hay grounding nativo, pero la citación sale igualmente del árbol
documental propio.

## Mapa de módulos

```
core/
├── backends/
│   ├── base.py            # VectorBackend (interfaz) + Citation/EvidenceChunk/RetrievalResult
│   ├── gemini_backend.py  # Gemini File Search (cloud / SaaS, sin PHI)
│   ├── qdrant_backend.py  # Qdrant (local-first / DGX / PHI)
│   └── factory.py         # selección por env: LASTRAG_BACKEND=gemini|qdrant
├── lastindex/             # PageIndex propio = LastIndex
│   ├── schema.py          # esquema Neo4j: Document/Chapter/Section/Page/EvidenceBlock
│   ├── parser.py          # Docling (primario) + PyMuPDF (fallback) → árbol con block_id
│   └── navigator.py       # ingesta del árbol + resolución locator→Citation + retriever estructural
├── llm/
│   └── base.py            # LLMClient + GeminiLLM (cloud) + LocalLLM real
│                          # (OpenAI-compatible: retries, streaming, fail-closed)
├── rag/
│   └── engine.py          # LangGraph agnóstico de backend + router Hermes + scoring honesto
├── ingestion.py           # pipeline unificado: parser → LastIndex + backend con MISMO block_id
└── tests/test_smoke.py    # valida contratos sin Neo4j/Qdrant/Gemini
```

## Las dos capas

| Capa | Qué es | Se construye |
|------|--------|--------------|
| **Producto** (este núcleo) | retriever híbrido + LastIndex + router + trazabilidad | una vez |
| **Despliegue** (Nexthealth-OS) | Qdrant local + LLM local (MedGemma) + Postgres + corpus biomédico | por config |

## Configuración (env)

```bash
# Camino cloud / SaaS (corpus sin PHI: guías públicas, papers, BOE)
LASTRAG_BACKEND=gemini
GOOGLE_API_KEY=...

# Camino DGX / local-first (Nexthealth-OS, datos con PHI)
LASTRAG_BACKEND=qdrant
LASTRAG_PHI_MODE=true        # bloquea cualquier backend cloud
QDRANT_URL=http://localhost:6333
NEO4J_URL=bolt://localhost:7687
LOCAL_LLM_ENDPOINT=...       # runtime del modelo biomédico local
```

El gate PHI (`assert_phi_allowed` + `LASTRAG_PHI_MODE`) impide ingerir datos de
paciente por un backend con `sends_data_to_cloud=True`.

## Flujo de ingesta (paridad de citación)

```
PDF → StructuralParser → ParsedDocument (bloques con block_id determinista)
                              │
        ┌──────────────────────┴──────────────────────┐
   LastIndex.ingest_tree                       backend.ingest(blocks)
   (estructura + páginas en Neo4j)             (vectores + payload, mismo block_id)
```

## Flujo de consulta

```
query → Hermes router → {semantic | structural | hybrid | graph}
                              │
                  recuperación (backend / LastIndex)
                              │
                  LastIndex.enrich_chunks  (locator → Citation)
                              │
              ¿sin evidencia? → external (PubMed/NICE/Cochrane)
                              │
                  generación (LLMClient) + scoring honesto
                              │
                  respuesta trazable + citaciones
```

## Estado actual — LastRAG 2 Foundation (22-oct-2026)

No es un producto clínico ni un sistema validado para uso sanitario: es el
motor horizontal de OMEGA-MR2 (ver `ROADMAP_FOUNDATION.md`; reorientación del
PI del 6-oct-2026: «arquitectura diseñada» ≠ «sistema validado»).

- **Gate FOUNDATION-T3 = REAL_E2E_PASS: ACREDITADO el 15-oct-2026** en el Spark
  (ALIA real por vLLM + Neo4j real, cadena completa sin mocks, los 9 controles
  cubiertos). Detalle y acta en `ROADMAP_FOUNDATION.md`.
- **Suite: 109 pass / 3 skip declarados** (22-oct, MBP) tras la auditoría de
  calidad: 21 defectos corregidos y 22 regresiones añadidas
  (`AUDITORIA_CALIDAD_20261022.md`).
- **Pendiente para la capa C («LastRAG 2.0»)**: embedder biomédico real y
  Wave 1 fase 2 (baseline `LastRAG-MD stable-v1.0` con su propio arnés).

Contratos implementados (test de humo en verde, con dobles):
- Interfaz `VectorBackend` + modelos de citación.
- LastIndex: esquema Neo4j, parser estructural, navigator (ingesta + resolución + retriever estructural).
- Backends Gemini y Qdrant tras la interfaz.
- Motor RAG agnóstico con router Hermes y scoring honesto.
- Pipeline de ingesta unificada con `block_id` común.

Wave 0 (P0.5 SOVEREIGN E2E FOUNDATION) — **completada** (T3, 15-oct-2026):
- `LocalLLM` real: cliente OpenAI-compatible (vLLM/TGI/Ollama/LM Studio) con
  timeout, retries limitados, streaming, health check, model metadata, clamp
  de `max_tokens` contra la ventana del modelo y fail-closed. **Ejercitado
  contra ALIA real** (vLLM en el Spark) en el E2E del gate T3.
- Qdrant real en modo local persistente: ingesta/búsqueda/filtros/top-k/
  reinicio verificados con embedder de desarrollo DECLARADO
  (`local-hash-ngram-256-v1`); el embedder biomédico del despliegue queda
  pendiente.
- Sin fallback silencioso: toda degradación (graph→hybrid, backend caído,
  Neo4j inalcanzable) queda en `route_effective` + `degradations[]` de la
  respuesta.

Pendiente (orden congelado en ROADMAP_FOUNDATION.md):
1. ~~Neo4j real en el camino E2E~~ · ~~endpoint LLM real~~ · ~~gate
   FOUNDATION-T3~~ — **hechos el 15-oct-2026** (acta en el roadmap).
2. Embedder biomédico real (hoy: hashing de desarrollo DECLARADO, o FastEmbed
   multilingüe sin benchmark biomédico en español).
3. Wave 1 fase 2: baseline `LastRAG-MD stable-v1.0` con su propio arnés;
   sólo después, features (Waves 2-6).
4. Cableado soberano completo del `app.py` (factory por env + LocalLLM +
   LastIndex real): hoy el transporte está acreditado, el cableado es deuda
   declarada de despliegue.

---

## Olas 1–5: cierre de brecha sobre el deck (rama `cierre-brecha-100`)

Capacidades añadidas al motor con tests de contrato (caso permitido + caso
bloqueado por control) y expediente sellado (`cierre_brecha/`):

| Ola | Módulo | Qué aporta |
|---|---|---|
| 1 | `rag/fusion.py`, `rag/iterative.py`, `rag/rerank.py` | RRF (k=60) · router iterativo (descomposición → sufficiency gate → gap → reformulación acotada) · reranking clínico determinista + cross-encoder ONNX opcional |
| 2 | `rag/pack.py`, `rag/conflict.py`, `rag/temporal.py` | Evidence Pack 2.0 (claims con spans verificables; el LLM recibe el objeto, no la nube de chunks) · Conflict Engine (4 relaciones, jamás promedia) · ventanas de validez + histórico + UNDATED |
| 4 | `rag/causal.py` | jerarquía ASSOCIATION→CAUSAL_SUPPORTED · CausalGate: recomendación sin evidencia de intervención = abstención por código · benchmark sintético confusor/mediador/colisionador |
| 5 | `rag/failure_graph.py` | modos de fallo con coste medido (ms) · taxonomía NO_EVIDENCE vs INSUFFICIENT_EVIDENCE |
| 3 | `rag/multimodal.py` | extracción posicional de tablas/figuras (PyMuPDF, sin modelo de visión — PARTIAL declarado) + routing multimodal |

**Estado (22-oct-2026):** 15/15 compromisos del deck DONE (100 % ponderado,
N-VERDE); suite 109 pass / 3 skip declarados. Bucle de mantenimiento:

```bash
.venv/bin/python scripts/cierre_brecha_loop.py   # scorecard desde tests; exit 0/1/75
.venv/bin/python scripts/benchmark_fusion.py     # recibo de fusión + coste de degradación
```

Embedder real opcional: `core.embedding.FastEmbedEmbedder`
(paraphrase-multilingual-MiniLM ONNX, 384d, sin torch), inyectable por
constructor con etiqueta `embedding_model` en cada respuesta.

**Claim limits:** nada de esto acredita calidad clínica, calidad semántica
sobre corpus biomédico real, ni conformidad regulatoria.

---

## Notas conocidas

- **Email residual en el historial**: un correo personal (Gmail) aparece
  hardcodeado en commits antiguos de ambas ramas (demo NotebookLM). Se acepta
  como exposición menor en un repositorio de código público. Eliminarlo
  exigiría reescribir el historial (`git filter-repo` + force-push), lo que
  rompería la cadena de hashes citada en los expedientes (incluido el pin T3
  `4784462`). Decisión: dejarlo documentado y no reescribir.
