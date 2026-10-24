# Loop de cambios para el agente zcode — NH-EG-LOOP-001 (ciclos 3+)

**Propósito:** convertir cada SIGUIENTE ACCIÓN del loop en un paquete de cambios cerrado: qué tocar, qué probar, qué productor escribe el recibo y qué queda prohibido. El agente no decide el orden ni los umbrales: los decide `PLAN_GATES.json` (sellado). Este documento decide **cómo** se ejecuta cada puerta.

**Estado al redactar (24-oct-2026):** 3/13 PASS (G0 suite · G1 fugas 0 con juez real · G2 curación). Siguiente acción: **G3**.

---

## 0 · El ciclo, literal

```bash
M="/Users/yeye/Documents/Agentes y conocimiento/Desarrollo Tecnologico y Scripts/Entorno_Desarrollo/py/Py_LastRAG_Index"
cd "$M" && git pull --rebase -q origin master            # 1. sincronizar (nunca force-push)
.venv/bin/python scripts/loop_evidencia_gobernada.py      # 2. medir; leer SIGUIENTE ACCION (rc 75)
#   rc 1  -> PARAR: arreglar causa raiz de la puerta FAIL; nada mas hasta que vuelva a PASS
#   rc 0  -> re-ejecutar hasta 3 pasadas verdes; luego informar al PI
# 3. ejecutar el paquete de la puerta (seccion 2 de este documento)
.venv/bin/python -m pytest tests/ -q                      # 4. suite completa verde; el suelo solo sube
.venv/bin/python evidencia_gobernada/produce_G<n>.py      # 5. el RECIBO lo escribe la ejecucion
.venv/bin/python scripts/loop_evidencia_gobernada.py      # 6. re-medir: la puerta debe pasar a PASS
git add -A && git commit -F <mensaje seccion 3>           # 7. codigo + recibo + acta, un commit por ciclo
git pull --rebase -q origin master && git push origin master
```

Si la SIGUIENTE ACCIÓN es una puerta `needs_pi` (G5, G10, G11, G12): **no se inventa el recibo**. Se produce/actualiza el expediente (`EXPEDIENTE_G<n>_PI.md`), se informa al PI y se para el ciclo. Las puertas posteriores no se adelantan: el orden es la cadena de confianza.

---

## 1 · Reglas de cambio (invariantes del agente)

1. **Un ciclo = una puerta.** No se mezclan paquetes en un commit.
2. **Toda modificación de `core/` lleva prueba de caso permitido y caso bloqueado** en `tests/`, y la suite completa termina en verde con `passed >= suelo` (el loop lo mide en G0).
3. **`CONTRACT_VERSION` no se toca.** Los cambios son aditivos (campos con default, parámetros opcionales). Si un paquete exigiera romper la superficie 1.0, se para y se escala al PI con la razón.
4. **Prohibido:** mocks en productores de recibo · escribir métricas a mano · bajar umbrales · tocar `PLAN_GATES.json` · tocar recibos de puertas anteriores · `git push --force` · tocar producción (VPS UrbaLex, AESPLA en el Spark) · tocar `omega_evidence_v07`.
5. **Ventana ALIA = recurso compartido con producción AESPLA.** Receta probada: `vllm/vllm-openai:v0.22.0`, `--gpu-memory-utilization 0.62 --max-num-seqs 2 --enforce-eager --max-model-len 4096`; si el contenedor muere, reintentar con `0.63`; carga ≈ 9 min; **cerrar la ventana al terminar** (`docker rm -f alia-nexthealth-inference`) y dejar ≥ 8 GB libres. Comprobar `free -g` antes de lanzar.
6. **Los productores no copian actas.** Un recibo sale de una ejecución de la que el productor extrae métricas programáticamente y ancla con `inputs_sha256` (script, corpus/manifest, modelo, endpoint).
7. **Escalado:** 3 ciclos consecutivos con la misma puerta en FAIL ⇒ expediente al PI (qué se midió, qué falló, qué se cambió). No hay cuarto intento.

---

## 2 · Paquetes de cambio por puerta

### C-G3 · Afirmabilidad (`affirmable` real por primera vez) — SIGUIENTE

**Problema a resolver.** La capa 5 busca `source_meta` por `locator` → `citation.block_id` → `citation.document`. En Wave 1 el `document_id` es `pubmed_<pmid>`, pero `RESOLVE_CITATION` devuelve el **título** como `document` y pierde el id; el `source_meta` curado está indexado por **PMID**. Resultado hoy: ninguna clave casa ⇒ todo `UNKNOWN_TIER` ⇒ `affirmable=false` aunque el corpus esté curado.

**Cambios (todos aditivos):**
1. `core/backends/base.py` — `Citation.document_id: Optional[str] = None` (nuevo campo con default; `to_dict` lo incluye).
2. `core/lastindex/schema.py` — `RESOLVE_CITATION` y `STRUCTURAL_SEARCH` devuelven además `b.document_id AS document_id`; `core/lastindex/navigator.py` lo copia a la `Citation`.
3. `core/backends/qdrant_backend.py` — `search()` conserva `document_id` del payload: crear `EvidenceChunk(..., citation=None)` sigue igual, pero añadir `document_id` al chunk vía atributo opcional **no** (rompería dataclass pública): en su lugar, `LastIndex.enrich_chunks` ya resuelve por `block_id` y ahora trae `document_id`. Para el camino sin Neo4j (`PassthroughLastIndex` en `app.py`), poner `Citation(document=locator, document_id=payload.document_id)` cuando el backend lo exponga en `RetrievalResult.raw` — opcional, declarar si no se hace.
4. `core/rag/provenance.py` — `lookup()` prueba también `citation.document_id`, y normaliza claves: `pubmed_<pmid>` ≡ `pmid:<pmid>` ≡ `<pmid>` (función `_candidate_keys(chunk)`).
5. Nuevo `core/rag/source_meta_store.py` — `SourceMetaStore.from_curation(path)` carga `source_meta_YYYYMMDD.json` (48.399 entradas por PMID), expone `Mapping[str, dict]` con las tres formas de clave y `stamp()` del fichero (sha256 + fecha). El engine acepta `source_meta=SourceMetaStore(...)` sin cambiar la firma (es un `Mapping`).
6. **Pruebas** (`tests/test_source_meta_store.py`): permitido — chunk con `document_id="pubmed_29605144"` y store curado ⇒ `qualified`, `affirmable=true` en un `engine.run` con dobles; bloqueado — PMID retractado (hay 84 en el fichero: usar uno real) ⇒ `UNQUALIFIED_RESPONSE`; bloqueado — PMID ausente ⇒ `UNKNOWN_TIER`, `affirmable=false`; clave `pmid:`/`pubmed_`/cruda resuelven al mismo registro.

**Productor `evidencia_gobernada/produce_G3.py`** (Spark, ventana ALIA): construye el engine como `bench/run_wave1.py` (Qdrant `wave1` + Neo4j T3) con `source_meta=SourceMetaStore.from_curation(...)`, `grounding/verification/source_policy="block"`, `verification_judge=True`; corre las **24 consultas congeladas** de `bench/BENCHMARK_WAVE1.md`; escribe `receipts/G3_afirmabilidad.json` con `metrics {queries, answered, abstained, affirmable, per_query:[{query, abstained, affirmable, provenance_state}]}` e `inputs_sha256 {source_meta, queries_file, producer, llm_model, embedder_model_id}`. Umbral sellado: `affirmable/answered ≥ 0.90`, `queries ≥ 24`.

**Aviso al PI (no es una excusa, es una debilidad del plan):** en la medición del 23-oct ALIA abstuvo en 21/24. Si `answered` es muy pequeño, G3 pasa con 3 respuestas. El plan sellado no exige `answered_min`. Proponer **PLAN v1.1.0 con `answered_min: 12`** y re-sellado deliberado; hasta entonces, el recibo declara `answered` y el PI juzga.

### C-G4 · Falsos bloqueos con anotador humano

**Cambio previo obligatorio:** re-medir con el verificador **corregido** (`e21c1e4`: texto del sistema y ausencias declaradas = META). El acta `9698e5d` (10 %) se midió con el defecto y su denominador no vale.

1. Ejecutar `bench/falsos_bloqueos_wave1.py` en la **misma ventana** que G3 (ya usa `verification="declare"` + juez). Salida: `bench/results/falsos_bloqueos_wave1_<fecha>.json`. **No** sobrescribir el del 23-oct: renombrarlo `…_20261023_pre_fix.json`.
2. Generar el paquete humano `G4_ANOTACION_HUMANA_<fecha>.json` **solo con las retiradas reales** (las META ya no aparecen). Cada frase lleva `veredicto_humano: null` y `anotador: null`.
3. **Parar y entregar el paquete al PI/clínico.** El agente no anota.
4. **Productor `produce_G4.py`:** lee el resultado del arnés + el paquete anotado; **rechaza** si alguna frase tiene `veredicto_humano: null` o `anotador` vacío; `supported_claims` sale del arnés; `redacted_legitimate` = nº de `RESPALDADA` humanas; escribe `receipts/G4_falsos_bloqueos.json` con `annotator` = nombre humano. El árbitro ALIA se guarda como `consultivo`, nunca como `annotator`.

### C-G6 · Recuperación (recall@20 ≥ 0,9; p50 < 1 s; oro preregistrado)

1. **Preregistro ANTES de medir:** `bench/PREREG_RECALL_WAVE2.md` con el oro (≥ 100 consultas con PMIDs relevantes; fuente: gold MeSH-estricto de la escala 48.399 ya existente en `cierre_brecha_real/data/MANIFEST_SCALE.json`), sellado con sha256 en el propio fichero y commit **antes** del primer run.
2. Candidatos: `paraphrase-multilingual-MiniLM-L12-v2` (ya en el Spark) y `BAAI/bge-m3` (descarga ≈ 2,2 GB: **pedir autorización** al PI antes). Reranker: `CrossEncoderReranker` existente.
3. `bench/run_recall.py` mide recall@20 y p50 por candidato sobre Qdrant local; **productor `produce_G6.py`** escribe `metrics {recall_at_20, p50_ms, gold_sha256, embedder, reranker}` del **mejor candidato declarado**, con los demás en `alternatives`.

### C-G8 · Actualidad (retractación reflejada ≤ 24 h)

Simulacro, no producción: (1) elegir un PMID del corpus hoy `none`; (2) crear `curation/overrides_drill.json` que lo marca `retracted` con `retraction_source: "drill"` y timestamp `injected_at`; (3) ejecutar el barrido incremental (`curation/retractions_sweep.py --pmids <ese>`) que re-estampa `source_meta`; (4) `engine.run` de una consulta que lo recupere ⇒ debe salir `UNQUALIFIED_RESPONSE`; `reflected_at` = timestamp de esa respuesta. **Productor `produce_G8.py`** escribe `metrics {injected_at, reflected_at, hours, pmid, drill: true}`. Deshacer el override al terminar y dejarlo en el recibo.

### C-G9 · Latencia (p50 ≤ 10 s con 5 capas)

Medir primero (24 consultas, 5 capas, juez activo): **productor `produce_G9.py`** escribe `metrics {queries, p50_s, p95_s, layers_active:[1,2,3,4,5], judge: true}`. Si FAIL, optimizaciones **permitidas** en orden: (a) juez solo para claims con `lexical < umbral` (los literales no necesitan juez); (b) claims en paralelo (`asyncio.gather` con límite); (c) caché de veredictos por `(evidence_hash, sha(claim))`; (d) grade + juez en una sola llamada MCQ. **No permitido:** desactivar capas, bajar `max_judge_fragments` a 0, ni medir sin juez y declararlo con juez. Cada optimización con su prueba de equivalencia de veredictos sobre el banco de 14 casos (fugas 0 intacto).

### C-G7 · Jerarquía de evidencia (κ ≥ 0,8) — preparación en Foundation, medición en I1

Foundation solo **transporta** el dato: la curación añade `study_type` por PMID desde `PublicationType` de PubMed (RCT · meta-análisis · revisión sistemática · cohorte · caso-control · serie de casos · guía) al `source_meta`; `provenance.py` lo expone en `Qualification.study_type` **sin** que afecte a `qualified` (la jerarquía GRADE pertenece a la solución, canon §2). La medición κ contra evaluador humano es de I1: el agente prepara el **expediente** (200 ítems muestreados, hoja de anotación) y para.

### Puertas `needs_pi` — solo expediente

| Puerta | Qué prepara el agente | Qué decide el PI |
|---|---|---|
| G5 | `EXPEDIENTE_G5_PI.md` (ya existe: Oleada A + MiniLM) + estimación de disco/horas | embedder, disco, key E-utilities |
| G10 | protocolo preregistrado borrador (preguntas por especialidad, cegado, comparadores, métricas, daño=0) | panel clínico externo |
| G11 | borrador de uso previsto + clasificación MDR/AI Act con fuentes | firma |
| G12 | paquete reproducible del banco del verificador (código + 14 casos + instrucciones) | auditor independiente |

---

## 3 · Plantillas

**Recibo** (`evidencia_gobernada/receipts/G<n>_<nombre>.json`):
```json
{"gate": "G3", "measured_at": "<ISO UTC>", "by": "zcode@<host>",
 "inputs_sha256": {"producer": "…", "source_meta": "…", "queries_file": "…", "llm_model": "alia-nexthealth", "embedder_model_id": "…"},
 "metrics": {"…": "solo lo que la ejecucion devolvio"}}
```
Sin campo `pass`. Sin métricas tecleadas.

**Mensaje de commit:**
```
loop NH-EG-LOOP-001 ciclo <k>: <G> <nombre> -> <PASS|FAIL|UNKNOWN> (<x>/13)

- cambios: <ficheros y que hacen>
- pruebas: <permitido / bloqueado anadidos>; suite <n> pass / <s> skip
- recibo: <fichero>, producido por <productor> en <host>; metricas <resumen>
- limites: <que NO acredita esta puerta>
- siguiente accion del loop: <G>
```

**Acta en `ROADMAP_FOUNDATION.md`:** una entrada fechada por ciclo bajo «Expediente del verificador / Loop de evidencia gobernada», con la misma información del commit y la ruta del recibo.

---

## 4 · Lo que el agente informa al PI al final de cada ciclo

Cuatro líneas, sin adjetivos: puerta y resultado del loop (`x/13`) · qué recibo se produjo y con qué ejecución · qué quedó UNKNOWN y por qué · qué decisión del PI bloquea la siguiente acción, si alguna. Distinguir siempre **preparado / integrado / publicado / verificado**.
