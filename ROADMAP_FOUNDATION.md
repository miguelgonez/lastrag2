# ROADMAP — LastRAG 2 Foundation (reorientación 6-oct-2026)

Decisión del PI tras la auditoría del 6 de octubre de 2026: la arquitectura de LastRAG 2
sigue siendo el destino correcto; lo erróneo era asumir que el punto de partida estaba
maduro. Este documento congela el orden de ejecución corregido. Procedencia: auditoría
verificada sobre código (smoke 4/4 solo con dobles; `LocalLLM` stub; sin integración real
Qdrant/Neo4j; sin benchmark; desarrollo congelado desde 12-jun-2026).

## Tres capas, no confundibles

| Capa | Qué es | Estado |
|---|---|---|
| **A. LastRAG-MD stable-v1.0** | Baseline histórico validado (Spark, 12-jun-2026) | Referencia de medición |
| **B. Py_LastRAG_Index actual** | Prototype / core-contract v2. **No es producto.** | Pre-alpha foundation |
| **C. LastRAG 2.0 futuro** | Evolución del v2 sólo tras E2E real + benchmark | No iniciado |

Regla: «arquitectura diseñada» ≠ «sistema validado». Nada de la capa C arranca hasta
superar el gate de la capa B.

## P0 — terminal corregido

El P0 anterior apuntaba a `P0-T3 BASELINE_FROZEN`. El terminal real es **`P0-T1
PARTIAL_BASELINE`** porque: LocalLLM no funciona, no hay integración real Qdrant/Neo4j,
no hay benchmark, Neo4j no está en el camino end-to-end, no hay despliegue soberano
demostrado y el único test real era smoke con mocks.

**P1 (Router y features de vanguardia) NO arranca.**

## P0.5 — SOVEREIGN E2E FOUNDATION (obligatoria)

### Objetivo 1 — LocalLLM real
Cliente OpenAI-compatible (vLLM / endpoint local): timeout, retries limitados con
backoff, streaming opcional, health check, model metadata, **fail-closed** (sin
fallback silencioso a otro modelo o a texto vacío). Intercambiable
MedGemma/Qwen/ALIA por configuración sin tocar el resto del stack.

### Objetivo 2 — Integración Qdrant real (sin mocks)
Ingestión, embeddings, búsqueda, filtros, top-k, metadatos, latencia, fallo del
servicio, reconexión.

### Objetivo 3 — Integración Neo4j real
`Document → Section → EvidenceBlock → Citation` realmente persistido y consultado.
El modo graph **no cae silenciosamente a hybrid**: si Neo4j no está disponible, se
declara como degradación explícita en la respuesta.

### Objetivo 4 — E2E real
`Query → Router → Retriever real → LastIndex/Neo4j/Qdrant → Evidence Pack →
LocalLLM → Answer + Citation`, sin mocks.

## Gate — FOUNDATION-T3 = REAL_E2E_PASS

**SUPERADO en su núcleo el 15-oct-2026**: `tests/test_e2e_sovereign.py` 3/3
PASS en el Spark (spark-3de7) con ALIA real (vLLM `alia-nexthealth-inference`
:8024, ventana 4096) y Neo4j real (`lastrag-t3-neo4j` :17687, árbol del
piloto PubMed + fixture). Cadena completa sin mocks: pregunta → router
(graph→hybrid con degradación declarada) → Qdrant local persistente +
structural search real (el híbrido también recuperó fragmentos PubMed del
grafo de 406 documentos) → grade MCQ de ALIA (evidencia validada) →
generación real → respuesta con citas resueltas del árbol. Suites: Spark
78 pass/3 skip; MBP 79 pass/2 skip.

| # | Control | Estado 15-oct-2026 |
|---|---|---|
| 1 | Qdrant real PASS | **PASS** (local persistente en E2E; embedder desarrollo declarado) |
| 2 | Neo4j real PASS | **PASS** (lastrag-t3-neo4j: esquema + árbol + fulltext + citas en el E2E) |
| 3 | LocalLLM real PASS | **PASS contra ALIA** (grade MCQ + generación; clamp a max_model_len con reserva real de prompt) |
| 4 | FastAPI PASS | PARCIAL (import OK; HTTP en transporte pendiente para el acta completa) |
| 5 | Evidence Pack PASS | **PASS** (evidence[] + citations[] + degradations[] en la salida del run real) |
| 6 | Citation provenance PASS | **PASS** (locator=block_id; citas documento/sección/página desde el árbol Neo4j) |
| 7 | PHI/local path PASS | PARCIAL (camino 100% local ejercitado; caso PHI explícito pendiente para el acta) |
| 8 | Cold-start PASS | **PASS** (reinicio de cliente sobre almacenamiento persistente) |
| 9 | Restart persistence PASS | **PASS** (Qdrant modo local) |

Lecciones del 15-oct (andamiaje adaptado al modelo soberano): (1) ALIA no
sigue instrucciones libres pero sí formato test — el grade va en MCQ A/B;
un ejemplo guiado dentro del prompt LO DESestabiliza (prompt mínimo =
6/6 estable). (2) El clamp de max_tokens debe reservar ~3 chars/token del
prompt (con 4 el prompt real 456 tok + 3641 pedidos = 4097 > 4096).
(3) Un PDF de fixture con insert_text TRUNCA las líneas en el borde de
página y el grade con razón lo rechaza — insert_textbox envuelve. (4) El
driver async de Neo4j no puede compartirse entre bucles de eventos:
cada escenario construye el suyo.

**Regla de oro: no puede haber fallback silencioso.** Si graph falla y usa hybrid,
queda registrado como DEGRADACIÓN en la respuesta, no como PASS. El motor expone
`route_effective` + `degradations[]` en cada run.

## Olas (orden congelado)

- **Wave 0 — Recover & stabilize**: LocalLLM + Qdrant real + Neo4j real + persistencia + E2E (este documento).
- **Wave 1 — Benchmark baseline**: stable-v1.0 vs v2-foundation (vector-only / index-only / graph-only / hybrid / triple; latency, recall, citation support, unsupported claims, abstention, medical-evidence completeness). Dirá si el núcleo v2 mejora algo o es una reimplementación incompleta.
- **Wave 2 — Retrieval intelligence**: router + decomposición + iterative retrieval + reranker.
- **Wave 3 — Evidence intelligence**: Evidence Pack 2 + conflict + temporal.
- **Wave 4 — Multimodal.**
- **Wave 5 — Causal Evidence Layer.**
- **Wave 6 — Agentic orchestration.**

## Naming

Hasta superar REAL_E2E_PASS, el sistema se nombra **«LastRAG 2 Foundation / pre-alpha»**.
No se llama «LastRAG 2» a nivel de producto.

## Estado de ejecución Wave 0 (6-oct-2026, verificado)

Suite completa: **26/26 PASS** (`python -m pytest tests/`): 4 smoke (contratos,
dobles) + 9 cliente LocalLLM (contra servidor HTTP real en proceso) + 4 Qdrant
real (motor local persistente) + 5 registro de degradaciones + 3 E2E soberano.

- `LocalLLM` real implementado (httpx): OpenAI-compatible, timeout, retries
  limitados con backoff (429/5xx/transporte; 4xx no se reintenta), streaming
  SSE agregado, `health()`, `model_metadata()`, fail-closed (`LocalLLMError`;
  el motor NO captura: sin LLM no hay respuesta). **UNKNOWN contra endpoint de
  modelo real** (no hay vLLM/Ollama/LM Studio activos hoy).
- `QdrantBackend`: modo local persistente (`path=`), etiqueta
  `embedding_model` en cada punto, `health()`, errores en `degraded_reason`.
  API migrada a `query_points` (qdrant-client actual eliminó `search`).
  **PASS real**: ingesta, búsqueda, filtros, top-k, latencia implícita,
  reinicio/cold-start con persistencia, fallo declarado.
- Motor sin fallback silencioso: `route_effective` + `degradations[]` en cada
  run (graph→hybrid declarado con from/to; backend caído; Neo4j inalcanzable
  → citas sin resolver declaradas).
- E2E soberano (test real): parser PyMuPDF real (Docling no instalado,
  fallback declarado) → PDF real → Qdrant real → router → degradaciones
  declaradas → **fail-closed** al no existir endpoint LLM. Con
  `LASTRAG_E2E_LLM_ENDPOINT` (+ `LASTRAG_TEST_NEO4J_URI`) la MISMA prueba
  ejecuta la cadena completa y exige respuesta con citas (camino T3).
- Reparado: instalación editable del venv apuntaba a ruta muerta
  (`~/Documents/py/...`); reinstalada sobre la ruta real.

UNKNOWN declarados (no simulados): servidor Neo4j (sin Docker/OrbStack hoy),
endpoint de modelo real, Docling, embedder biomédico real, HTTP de FastAPI
en transporte. El gate FOUNDATION-T3 **NO está superado**.

## Roadmap post-T3 (hallazgos FOUNDATION-T3, 6-oct-2026 — recibo b9b7d50f…)

- **F1 · max_tokens acoplado a max_model_len**: el motor debe clampar/negociar `max_tokens` contra `model_metadata` del endpoint (el default 8192 provocó HTTP 400 explícito contra vLLM 4096). Estado: T3 superado con adaptador declarado; el clamp nativo es pendiente.
- **F2 · gate PHI no reactivo a runtime**: `Settings` (dataclass) captura el env al importar; el gate no reacciona a cambios de entorno en runtime tras el primer import. Pendiente: defaults lazy o validación en construcción.
- **F3 · política single-owner para Qdrant path=**: Qdrant local no admite dos clientes sobre el mismo path; documentar ciclo de vida de proceso (o Qdrant servidor para concurrencia).

Nota de procedencia: estos puntos no rompen ningún gate de T3; el release acreditado permanece pineado en 22519f48 / tree 3182506b.
