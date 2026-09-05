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
│   └── base.py            # LLMClient (interfaz) + GeminiLLM (cloud) + LocalLLM (stub DGX)
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

## Estado actual

Implementado y verificado (test de humo en verde):
- Interfaz `VectorBackend` + modelos de citación.
- LastIndex: esquema Neo4j, parser estructural, navigator (ingesta + resolución + retriever estructural).
- Backends Gemini y Qdrant tras la interfaz.
- Motor RAG agnóstico con router Hermes y scoring honesto.
- Pipeline de ingesta unificado con `block_id` común.

Pendiente (siguiente iteración):
1. Nodo `graph` real (relaciones clínicas Neo4j) — hoy cae a `hybrid`.
2. `LocalLLM` para DGX (vLLM/TGI) — stub.
3. Benchmark de 20 preguntas como contrato de medición (Fase 5 del roadmap, adelantada).
4. Capa FastAPI + persistencia (SQLite genérico / Postgres en despliegue).
5. Reranking en modo híbrido (hoy fusión por locator con prioridad estructural).
