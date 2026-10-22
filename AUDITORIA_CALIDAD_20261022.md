# Auditoría de calidad — LastRAG 2.0 Foundation (OMEGA-MR2)

**Fecha:** 22-oct-2026 · **Alcance:** árbol master `Py_LastRAG_Index` (código `core/`, transporte `app.py`, pruebas `tests/`, documentos de estado).
**Punto de partida:** `efa7b00` (22-oct, *governance: registro de forks*), árbol limpio.
**Canon aplicable:** `OMEGA-MR2-LASTRAG-FOUNDATION-CANON v1.3.0` — `CONTRACT_VERSION 1.0`.
**Marco:** NH-ADLC-001 — *ninguna afirmación sin evidencia; ninguna evidencia sin procedencia; `UNKNOWN != PASS`*.

## 1 · Qué se revisó y cómo

| Vía | Qué cubre |
|---|---|
| Lectura íntegra de `core/` (18 módulos), `app.py`, `bench/`, `scripts/` | contratos, degradaciones, fail-closed, procedencia de citas |
| Suite completa antes de tocar nada | línea base ejecutada: **87 pass / 2 skip** (80 s) |
| Suite completa después de cada bloque de cambios | **109 pass / 3 skip** |
| Bucle de mantenimiento `scripts/cierre_brecha_loop.py` | **100 % (15/15 DONE) + N-VERDE**, exit 0 |

**Criterio de corrección aplicado:** se corrigen incumplimientos del contrato ya vigente. No se amplía alcance, no se añaden capacidades nuevas, no se toca `CONTRACT_VERSION` (ningún cambio altera firmas ni semántica pública: canon 1.1.0).

## 2 · Defectos corregidos

Severidad: **C** crítica · **A** alta · **M** media · **B** baja.

| # | Dónde | Defecto | Sev | Corrección | Regresión |
|---|---|---|---|---|---|
| A-01 | `backends/factory.py` | `Settings` evaluaba `os.getenv` al **importar**: activar `LASTRAG_PHI_MODE` en runtime no llegaba al gate (hallazgo F2 del roadmap, pendiente desde el 6-oct) | A | `default_factory`: el entorno se lee en cada construcción | `test_settings_lee_el_entorno_en_cada_construccion`, `test_phi_mode_activado_en_runtime_bloquea_backend_cloud` |
| A-02 | `backends/factory.py` | El gate PHI vivía solo en la rama `gemini`: un backend cloud futuro no quedaba cubierto | M | `_assert_local_first()` por **capacidad declarada** (`sends_data_to_cloud`) en todas las ramas | `test_gate_phi_se_aplica_por_capacidad_declarada` |
| A-03 | `backends/gemini_backend.py` | `search()` devolvía resultado vacío **sin `degraded_reason`** ante excepción del SDK o backend no inicializado: el motor leía «no hay evidencia» donde hubo un fallo | A | `GEMINI_ERROR:*` / `GEMINI_NOT_INITIALIZED:*` declarados | `test_gemini_error_del_sdk_viaja_en_degraded_reason`, `test_gemini_sin_store_declara_degradacion_no_vacio` |
| A-04 | `backends/gemini_backend.py` | `time.sleep(3)` dentro de corrutina: bloqueaba el event loop hasta 180 s durante la ingesta | M | `await asyncio.sleep(3)` | — (cambio de 1 línea, verificado por suite) |
| A-05 | `backends/qdrant_backend.py` | El embedder se invocaba **fuera** del `try`: un fallo (modelo ausente, OOM) propagaba excepción en lugar de degradación; en `hybrid` el `asyncio.gather` tumbaba la consulta entera | A | `EMBEDDER_ERROR:*` en `search()`; `IngestResult(error=…)` en `ingest()` | `test_qdrant_fallo_del_embedder_se_declara`, `test_qdrant_ingesta_con_embedder_roto_no_lanza` |
| A-06 | `backends/qdrant_backend.py` | Con el embedder por defecto los puntos se indexaban con `embedding_model="unknown"`: agujero de procedencia justo en la etiqueta que el canon exige | M | Etiqueta derivada: declarada > `model_id` del embedder > modelo por defecto | `test_etiqueta_de_embedding_se_deriva_del_embedder` |
| A-07 | `rag/engine.py` (`_grade`) | Cuando el filtro de dominio **descartaba toda la evidencia**, la decisión solo se imprimía: la respuesta era indistinguible de «no se recuperó nada» | A | Degradación `grade/DOMAIN_IRRELEVANT` + `features.grade` en la salida | `test_grade_descarta_evidencia_y_lo_declara` |
| A-08 | `rag/failure_graph.py` | Tras ese descarte, `classify_absence` decía `NO_EVIDENCE` y recomendaba «reintentar recuperación»: **remedio equivocado** | M | Nuevo caso `discarded_by_grade` → `INSUFFICIENT_EVIDENCE` con remedio correcto | mismo test (assert sobre `absence`) |
| A-09 | `rag/engine.py` (`_grade`) | `**A)**` o `«A»` se leían como veredicto ilegible | B | `_normalize_verdict()` limpia adornos y **no adivina** | `test_veredicto_tolera_adornos_pero_no_adivina` |
| A-10 | `llm/base.py` (`stream_deltas`) | Un corte a mitad de stream reintentaba la petición: el endpoint regenera desde cero y el consumidor recibía **el prefijo duplicado** | A | Sin reintento tras emitir deltas: `LocalLLMError("STREAM_INTERRUPTED")` | `test_stream_interrumpido_falla_cerrado_sin_reemitir` |
| A-11 | `llm/base.py` (`_model_len`) | La caché no distinguía «sin consultar» de «consultado y sin dato»: dos `GET /models` extra por cada generación contra endpoints que no publican la ventana | B | Centinela `_metadata_checked` | — |
| A-12 | `llm/base.py` (`GeminiLLM`) | El SDK `google-genai` es síncrono y se llamaba dentro de la corrutina: bloqueaba el loop durante toda la generación | M | `asyncio.to_thread` | `test_gemini_llm_no_bloquea_el_event_loop` |
| A-13 | `lastindex/schema.py` | `RESOLVE_CITATION` buscaba el capítulo con `(:Section {path})` **sin acotar por documento**: dos documentos con la misma ruta («1. Introducción») podían atribuir el capítulo del documento equivocado | A | Patrón acotado a `document_id` en `Chapter` y `Section` | `test_resolve_citation_acota_el_capitulo_al_documento` (verificación **estática**: sin Neo4j en este entorno) |
| A-14 | `rag/multimodal.py` | `item.prov[0].pageno` no existe en Docling (`page_no`): el `except` genérico llevaba **todas** las tablas a `page=1`, con cita a página falsa | A | `_docling_page_no()` con nombre vigente + defensivo | `test_pagina_docling_se_lee_del_nombre_vigente` |
| A-15 | `rag/temporal.py`, `rag/rerank.py` | «Ahora» fijado a `2026`: en 2027 una guía caducada se habría servido como vigente y el bonus de actualidad se habría congelado. `wants_historical` comparaba contra un `2024` fijo | M | El año sale del reloj (`date.today().year`), inyectable para pruebas | `test_vigencia_temporal_contra_el_ano_en_curso`, `test_reranker_mide_actualidad_contra_el_ano_en_curso` |
| A-16 | `rag/causal.py` | `classify_claims` prometía «locator → nivel» y devolvía «statement → nivel»: usarlo para etiquetar el Evidence Pack **no fallaba, simplemente no etiquetaba nada** (no-op silencioso en la capa que separa asociación de causa) | M | Indexado por `span.chunk_locator`, gana el nivel más alto por locator | `test_classify_claims_indexa_por_locator_y_etiqueta_el_pack` |
| A-17 | `backends/delta_backend.py` | `health()` devolvía `ok`/`error` fuera del vocabulario del contrato (`UP`/`DOWN`/`UNKNOWN`) y `search()` propagaba excepciones de Spark sin declararlas | M | Vocabulario alineado + `DELTA_ERROR:*` | `test_delta_health_usa_el_vocabulario_del_contrato` (skip declarado sin pyspark) |
| A-18 | `app.py` (`/api/upload`) | `upload_dir / file.filename` con nombre controlado por el cliente: **escritura arbitraria de ficheros** (`../../…`, rutas absolutas). Además el transporte no aplicaba el gate PHI que sí aplica el pipeline | **C** | `safe_upload_name()` (solo el componente final, rechazo explícito) + bloqueo 403 con `LASTRAG_PHI_MODE=true` sobre backend cloud | `test_nombre_de_subida_no_permite_escribir_fuera_del_directorio` |
| A-19 | `app.py` | `@app.on_event("startup")` deprecado (3 avisos por corrida) | B | `lifespan` asíncrono; contrato observable idéntico | suite de transporte existente (3 tests) |
| A-20 | `tests/doubles.py`, `tests/test_degradation.py` | Los dobles respondían prosa al prompt del `grade`, que es **MCQ desde el 15-oct**: todas las pruebas de motor atravesaban la rama `UNDECIDABLE_VERDICT` sin pretenderlo, y el camino normal del filtro de dominio **no tenía cobertura** | A | Dobles que hablan el formato (`A`/`B` configurable) + 4 pruebas del nodo `grade` | `test_grade_*`, `test_el_doble_responde_el_grade_en_su_formato` |
| A-21 | `rag/engine.py` (`_fuse`) | Implementación duplicada de la fusión por locator (motor y `rag/fusion.py`), con riesgo de divergencia | B | `_fuse` delega en `fuse_by_locator` (se conserva la firma que pinea `bench/run_wave1.py`) | `test_fuse_del_motor_delega_en_fusion_por_locator` |

## 3 · Defectos documentales corregidos

| # | Dónde | Qué decía | Qué dice ahora |
|---|---|---|---|
| D-01 | `FOUNDATION_VERSION.json` | canon v1.2.0; suite «26/26»; **FOUNDATION-T3 en `not_accredited`** | canon v1.3.0; suites fechadas (release / acta T3 / auditoría); T3 en `accredited` con su evidencia y sus commits; pendientes reales (embedder semántico, Wave 1 fase 2) |
| D-02 | `ROADMAP_FOUNDATION.md` | La sección del 6-oct afirmaba «El gate FOUNDATION-T3 **NO está superado**» junto a la del 15-oct que lo da por superado; F1 (clamp de `max_tokens`) y F2 (gate PHI no reactivo) figuraban pendientes estando ya implementado el primero | Secciones fechadas y marcadas como histórico; estado real de F1/F2/F3 con procedencia |
| D-03 | `README.md` | Mapa de módulos con «`LocalLLM` (stub DGX)»; «Wave 0 en curso»; T3 como pendiente | Estado a 22-oct con T3 acreditado, suite actual y límites de reclamación intactos |

## 4 · Escalado al PI — NO corregido aquí (veredicto histórico)

**Discrepancia de fechas de FOUNDATION-T3 en el canon.** `LASTRAG_FOUNDATION_CANON.md v1.3.0` afirma en §8 «FOUNDATION-T3 ✅ ACREDITADO 6-oct-2026 · terminal T3-T3 FOUNDATION_T3_PASS (51/51; recibo `b9b7d50f…`)», mientras su propia §6 (censo del **mismo día**) declara el E2E soberano **«no acreditado»**, y la evidencia ejecutable del repositorio sitúa el `REAL_E2E_PASS` el **15-oct** (`tests/test_e2e_sovereign.py` contra ALIA y Neo4j reales, commits `ef6f6b2` y `9cc9765`).

El canon está `frozen_active_canon`: *«cambios futuros = nueva versión con changelog, jamás edición silenciosa»*. No se edita. Queda registrada la discrepancia aquí y en `FOUNDATION_VERSION.json → verification.nota_de_procedencia`. **Decisión del PI pendiente:** emitir canon v1.3.1 que unifique la fecha y aclare si «terminal T3-T3 (51/51)» y «REAL_E2E_PASS (15-oct)» son el mismo gate o dos instrumentos distintos.

## 5 · Hallazgos abiertos (no corregidos, con razón)

| # | Hallazgo | Por qué no se corrige ahora |
|---|---|---|
| H-01 | `backends/neo4j_graph.py`: el *fallback* por ausencia de APOC se detecta comparando el **texto** de la excepción y solo se imprime; no viaja como degradación en la respuesta | Cambiar la firma de `search_related` toca la superficie que consume el motor; exige Neo4j real para verificar caso permitido y caso bloqueado (`UNKNOWN != PASS`). Requiere ventana con el Spark |
| H-02 | `neo4j_graph.search_related`: `MATCH (start) WHERE ANY(label …)` recorre todos los nodos sin índice | Optimización medible solo contra el grafo real del piloto; sin Neo4j no hay medición, y sin medición no hay reclamación |
| H-03 | Defaults de credenciales Neo4j divergentes: `factory` usa `neo4j`, `neo4j_graph.py` y `bench/run_wave1.py` usan `password` | Tocar defaults de runtime puede romper despliegues vivos (VPS/Spark); decisión de despliegue, no de calidad del código |
| H-04 | `rag/multimodal.py`: `EXTRACTOR_EVENTS` es una lista global sin cota (crece en procesos largos) | Acotarla cambia la semántica que hoy comprueban las pruebas de Ola 3; conviene decidir política (ventana o por-run) antes de tocarla |
| H-05 | `rag/engine.py`: la ruta `graph` pura devuelve contexto de grafo **sin fragmentos ni citas** (`_graph` no recupera evidencia textual) | Es diseño declarado («enganche futuro» en el encabezado del motor), no un fallo; entra en Wave 2 |
| H-06 | `core/` imprime por `print()` en lugar de usar `logging` | Un componente forkable debería dejar el canal de registro al anfitrión. Cambio transversal (≈40 llamadas) que merece su propio commit y revisión |
| H-07 | Correo personal en el historial git de ambas ramas (repo público `miguelgonez/lastrag2`) | Decisión ya tomada y documentada en el README: reescribir el historial rompería la cadena de hashes citada en los expedientes |

## 6 · Evidencia de la corrida

```
línea base (antes):   87 passed,  2 skipped  en 80.17 s
tras las correcciones: 109 passed, 3 skipped en 33.77 s
scripts/cierre_brecha_loop.py → 100% (15 DONE / 15) · N-VERDE · exit 0
```

Skips declarados (no éxitos falsos): `DELTA_PATH` sin definir · `docling` presente (no se puede simular su ausencia) · `pyspark` ausente.

**Límites de esta auditoría (declarados):** es una revisión de **código, contratos y coherencia documental** sobre el árbol master, ejecutada en el MBP. No acredita calidad clínica, ni calidad semántica sobre corpus biomédico real, ni conformidad regulatoria. No se ejecutó Neo4j ni endpoint de modelo real (no disponibles en este equipo hoy): la corrección A-13 está verificada **por inspección del Cypher**, no contra servidor. El gate FOUNDATION-T3 no se vuelve a ejercitar aquí; su acreditación sigue siendo la del 15-oct en el Spark.
