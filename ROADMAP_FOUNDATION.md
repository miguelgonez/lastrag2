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
| 4 | FastAPI PASS | **PASS transporte** (uvicorn en socket real: HTML, /api/status honesto sin clave, 400/503 declarados; cableado soberano del app = deuda de despliegue) |
| 5 | Evidence Pack PASS | **PASS** (evidence[] + citations[] + degradations[] en la salida del run real) |
| 6 | Citation provenance PASS | **PASS** (locator=block_id; citas documento/sección/página desde el árbol Neo4j) |
| 7 | PHI/local path PASS | **PASS** (factory LASTRAG_PHI_MODE bloquea cloud; contrato assert_phi_allowed; pipeline comprueba ANTES de parsear; 5 tests) |
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

## Estado de ejecución Wave 0 — HISTÓRICO del 6-oct-2026 (verificado ese día)

> **Lectura:** esta sección es la foto del 6-oct y se conserva tal cual por
> procedencia. Sus `UNKNOWN` y su «el gate FOUNDATION-T3 NO está superado»
> describen el estado **de esa fecha**; quedaron resueltos el 15-oct (ver
> «Gate — FOUNDATION-T3» arriba y «Acta completa T3» abajo). No es una
> contradicción del documento: es su cronología.

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

UNKNOWN declarados **a 6-oct** (no simulados): servidor Neo4j (sin
Docker/OrbStack ese día), endpoint de modelo real, Docling, embedder
biomédico real, HTTP de FastAPI en transporte. El gate FOUNDATION-T3 **no
estaba superado en esa fecha** (lo fue el 15-oct; el único UNKNOWN que
sobrevive hoy es el embedder biomédico real).

## Acta completa T3 (15-oct-2026, tarde)

Los 9 controles del gate quedan cubiertos: transporte FastAPI real
(`tests/test_fastapi_transport.py`, uvicorn socket efímero, arranque degradado
DECLARADO sin clave) y camino PHI explícito (`tests/test_phi_gate.py`, tres
capas fail-closed sin red). Suites: MBP 87 pass/2 skip; Spark 89+ pass tras
instalar fastapi en su venv. Commit del acta + bench en el historial.

## Wave 1 — Fase 1 ejecutada (15-oct-2026)

Protocolo congelado en `bench/BENCHMARK_WAVE1.md` ANTES de medir; harness
`bench/run_wave1.py` (hash registrado en el resultado). Corpus: los 1.095
abstracts del piloto ingeridos COMPLETOS en Qdrant (colección wave1) y en el
árbol Neo4j T3 (cierra el 406→1.095). 24 consultas congeladas (6/tema):

| modo | prec_temática@5 | MRR_1er_acierto | citas@5 | p50 | p95 | vacío |
|---|---|---|---|---|---|---|
| vector_only (hash dev) | 0.467 | 0.616 | 1.00 | 1.1 ms | 5.7 ms | 0% |
| index_only (Neo4j FT) | 0.400 | 0.417 | 0.708* | 4.4 ms | 11.4 ms | 29.2% |
| hybrid (fusión locator) | **0.517** | 0.604 | **1.00** | 6.4 ms | 12.5 ms | **0%** |

(*index_only cita 100% cuando devuelve algo; el 0.708 incluye sus 7/24
consultas vacías.) Lecturas honestas: (1) la fusión híbrida suma precisión y
ELIMINA la abstención del estructural; (2) paridad de citación 100% a escala
piloto — todo resultado cita el árbol propio; (3) la recuperación NO es el
cuello de botella (ms): lo es el QA con ALIA (~25-30 s/consulta, del E2E);
(4) la precisión ~0.5 es cota INFERIOR con embedder dev no semántico y oro
temático silver con solapamientos (metformin/sglt2/heart_failure comparten
espacio clínico); (5) grafo clínico T3 aún pobre (nodos en 6/24 consultas).
Escala de abstracts: `~/lastrag_pubmed_pilot/PLAN_ESCALA.md` (oleadas + reglas).

## Roadmap post-T3 (hallazgos FOUNDATION-T3, 6-oct-2026 — recibo b9b7d50f…)

- **F1 · max_tokens acoplado a max_model_len** — **CERRADO (15-oct-2026)**: el
  clamp vive en `LocalLLM._clamp_tokens` (consulta `model_metadata`, reserva
  ~3 chars/token del prompt y deja el ajuste en `last_token_adjust`). El
  22-oct se corrigió además la caché de la ventana, que re-consultaba
  `/models` en cada generación contra endpoints que no la publican.
- **F2 · gate PHI no reactivo a runtime** — **CERRADO (22-oct-2026)**:
  `Settings` usa `default_factory`, de modo que cada construcción lee el
  entorno vigente; el gate se aplica además por capacidad declarada
  (`sends_data_to_cloud`) en todas las ramas del factory, y el transporte
  `/api/upload` lo replica. Pruebas: `tests/test_auditoria_calidad.py`.
- **F3 · política single-owner para Qdrant path=** — **ABIERTO**: Qdrant local
  no admite dos clientes sobre el mismo path; falta documentar el ciclo de
  vida de proceso (o pasar a Qdrant servidor para concurrencia).

Nota de procedencia: estos puntos no rompen ningún gate de T3; el release acreditado permanece pineado en 22519f48 / tree 3182506b.

## Política de generación: abstención grado médico (PI, 22-oct-2026)

Decisión del PI (literal): *«el servicio debe tener grado médico, 0
alucinaciones; es la garantía que diferencia a NextHealth de la competencia.
Si no lo sabe, lo dice, antes de inventar.»*

Aplicación en el motor (commit de esta fecha): el fallback «responder desde
conocimiento general con aviso» deja de ser el default. Dos capas por CÓDIGO:
(1) sin evidencia el LLM ni se consulta → abstención determinista;
(2) una salida auto-declarada como conocimiento general se bloquea y se
sustituye por la abstención, declarada en `degradations[]` y registrada como
`UNSUPPORTED_GENERATION`. Opt-in legacy: `allow_general_knowledge=True`,
siempre visible en `features.generation_policy`. Salida nueva aditiva:
`abstained` (incluye el gate causal). `CONTRACT_VERSION` se mantiene en 1.0
(superficie intacta; el cambio de default queda declarado aquí y en
`FOUNDATION_VERSION.json`; los consumidores de FORKS.md portan copias de la
era v2.0.0 y no se ven afectados hasta que rebasen).

**Capa 3 — anclaje claim↔evidencia (añadida el mismo día):**
`core/rag/grounding.py` congela la evidencia antes de generar (sha256 por
fragmento + hash reproducible del conjunto) y verifica por CONTENIDO cada
dato duro (valor+unidad, dosis, porcentaje) y cada cita textual de la
respuesta. `grounding="block"` (default) retiene lo no anclado; `"declare"`
entrega retirando citas fabricadas y declarando el estado; `"off"` solo para
forks con verificador propio.

*Procedencia honesta:* esta capa NO nació en el upstream. Operaba ya en
AESPLA-PRL (`lastrag2.py`: `require_grounded_output` → HTTP 422) y en FIMABIS
(`sovereign.py`: shield de citas + anclaje + retirada). El master era la
pieza MÁS DÉBIL de la familia: era el único que respondía desde conocimiento
general por defecto. Se porta como mejora horizontal (regla 3 del
procedimiento de fork) para que ningún producto futuro la reinvente.

**Capa 4 — verificador claim↔evidencia (orden del PI, mismo día: «antes
debes desarrollar el verificador»):** `core/rag/verifier.py`. Cada frase
asertiva de la respuesta, con o sin cifras, se contrasta con la evidencia
congelada (misma `EvidenceFreeze` que la capa 3). Veredicto por claim con su
span: SUPPORTED · UNSUPPORTED (se retira con marca) · CONTRADICTED (retiene
la respuesta) · META (no cuenta). Métodos declarados con disponibilidad
real: léxico (siempre; solapamiento morfológico + polaridad + dirección ↑/↓),
semántico (embedder inyectado; nunca decide solo ni anula una contradicción)
y juez (LLM soberano, MCQ A/B/C; A respalda, B contradice, C/ilegible NO
fuerzan nada: decide el código).

*Medido* (`run_verifier_benchmark`, 14 casos con ground truth): **fugas 0**
con el léxico solo; **falsos bloqueos 2/6** (paráfrasis fuertes) que el juez
cierra a **0/6 sin fugas** (juez simulado por reglas en la suite). Estado de
los métodos en el MBP hoy: semántico UNAVAILABLE (sin modelo FastEmbed
multilingüe descargado; ~470 MB, requiere autorización) · juez UNAVAILABLE
(sin endpoint; ALIA vive en el Spark). Integración: `verification="block"`
por defecto; `verification_judge=True` usa el LLM del motor como juez.

**Capa 5 — cualificación de la fuente (regla del PI, mismo día):** «esto sí
se puede afirmar si se remite a una evidencia trazable respaldada por un
centro de evidencia científica, un paper validado por pares y que a la fecha
no haya sido refutado, o guías de práctica clínica por asociación científica
acreditada». `core/rag/provenance.py`: cualifica por contrato de metadatos
(`tier` · `accredited` · `retraction_status` · `retraction_checked_at`) los
fragmentos que sostienen la respuesta. Retractada ⇒ retenida; nivel no
cualificado ⇒ claims retirados; desconocida ⇒ entregada y declarada NO
afirmable (strict: retenida). «A la fecha» = comprobación fechada y vigente
(180 días). Salida nueva aditiva: `affirmable`. Lo que esta capa NO hace:
consultar registros externos (es curación del corpus, que deja su fecha en
los metadatos) ni la jerarquía clínica GRADE/PICO (canon: solución, no motor).
Pruebas: `tests/test_procedencia_fuente.py` (16; cada condición de la regla
con permitido y bloqueado). Suite: 171 pass / 3 skip.

**Deuda abierta por esta capa:** hoy NINGÚN corpus del Foundation lleva
metadatos de procedencia — los 1.095 abstracts del piloto PubMed son
peer-reviewed por construcción pero no están etiquetados ni comprobados
contra retractaciones. Hasta que la ingesta (`core/ingestion.py`,
`scripts/ingest_pubmed_delta.py`) escriba `source_meta`, toda respuesta sale
`affirmable=false` y lo dice. Es el estado honesto, no un fallo.

**Pendiente para cerrar el expediente del verificador con modelo real:**
(1) re-ejecutar `tests/test_e2e_sovereign.py` en el Spark con ALIA como
juez — el E2E del 15-oct es ANTERIOR a las capas 3-4 y su acta no las cubre;
(2) descargar FastEmbed multilingüe y medir el método semántico;
(3) tasa de falsos bloqueos sobre las 24 consultas congeladas de Wave 1.
Controles ejercitados (permitido + bloqueado por capa):
`tests/test_abstencion_grado_medico.py` (8),
`tests/test_anclaje_claim_evidencia.py` (16) y
`tests/test_verificador_claims.py` (22).

**Alcance NextHealth:** la doctrina `NH-GRADO-MEDICO-001` (marco ADLC) aplica
a todo producto, no solo a este motor, con su matriz de estado por producto
—incluidos los `UNKNOWN` sin auditar—. Ver `FORKS.md`.

## Auditoría de calidad (22-oct-2026)

Revisión completa del árbol master: **21 defectos de código corregidos**
(críticos: escritura arbitraria de ficheros por el nombre de subida; altos:
degradaciones silenciosas de backend, descarte de evidencia no declarado,
duplicación de contenido al reintentar un stream, cita con capítulo de otro
documento, página de tabla siempre 1) y **22 pruebas de regresión** nuevas.
Suite: 87/2 → **109 pass / 3 skip**; bucle de cierre de brecha en verde
(15/15 DONE, N-VERDE). `CONTRACT_VERSION` sin cambios: todas las correcciones
restauran el contrato 1.0, no lo alteran.

Expediente completo, hallazgos abiertos y el punto escalado al PI (discrepancia
de fechas de T3 en el canon, que **no** se edita por estar congelado):
`AUDITORIA_CALIDAD_20261022.md`.
