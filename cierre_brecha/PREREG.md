# PREREG — Bucle de cierre de brecha LastRAG 2.0 (sello ANTES de ejecutar)

**Fecha de sellado:** 2026-10-13 · **Programa:** «ejecuta un loop con autoridad plena para ejecutar todo lo que falta» (PI, orden directa).
**Rama:** `cierre-brecha-100` sobre árbol `4784462` (release pin `22519f48` INTACTO; ningún commit del historial se modifica).
**Ámbito:** los 11 ítems pendientes del compliance table de 15 (PLAN_CIERRE_BRECHA_LastRAG2_100.md v2), en el orden de olas 1→2→4→5→3.

## Reglas del bucle (vinculantes)

1. **Cero regresión:** la suite previa (26/26) debe seguir verde en CADA pasada. Cualquier test viejo roto = fallo del ítem en curso, no se avanza de ola.
2. **Caso permitido + caso bloqueado por control** (doctrina NH-ADLC-001): un ítem solo pasa a DONE con tests de ambos lados. Sin caso bloqueado, el control no existe.
3. **N-verde = 2:** el bucle termina en verde sólo con 2 pasadas completas consecutivas sin fallos ni flakes.
4. **Reanudar ANTES de elegir:** el ítem IN_PROGRESS se reanuda antes de seleccionar otro PENDING (regla de selección de loop).
5. **Declaración jamás silenciosa:** toda nueva vía (fusión RRF, rerank, iteración, temporal, causal, multimodal) queda declarada en `features[]` de la respuesta; todo recorte de funcionalidad queda como entrada explícita (estado/bloqueo), nunca como omisión.
6. **Claim limits:** NOTHING de este bucle acredita calidad clínica, calidad semántica del retrieval sobre corpus biomédico real, ni conformidad regulatoria. El embedder ONNX conectado es real pero SU calidad no se reclama sin benchmark; el benchmark de fusión corre sobre corpus sintético (declarado).
7. **Exit codes:** 0 = objetivo (2 pasadas verdes); 1 = fallos; 75 = skip con razón escrita (nunca exit 0 en skip).
8. **Objetos congelados intactos:** expedientes T3, backups lastrag-md, omega_sovereign_v06 y veredictos históricos no se tocan.

## Ítems y criterios PASS (cada uno = tests de contrato, sin servicios externos)

| ID | Ítem (ola) | PASS cuando |
|---|---|---|
| CB-2 | Router iterativo: descomposición + sufficiency gate + gap detector + reformulación acotada (1) | bucle recupera por subpregunta, detecta hueco, reformula y lo cierra; it. máx. alcanzado queda DECLARADO; query simple = 1 subpregunta sin bucle extra |
| CB-3 | RRF (1) | fusión por rangos recíprocos ordena por consenso de listas; modo por defecto (locator) invariante; modo usado declarado en features |
| CB-4 | Reranking clínico (1) | reranker determinista reordena por señales clínicas auditables (tipo de estudio, población, actualidad, autoridad) con reasons[]; cross-encoder ONNX si el modelo está disponible (etiquetado), y su ausencia se declara sin degradar |
| CB-5 | Evidence Pack 2.0 (2) | objeto claim↔evidence con spans verificables (text[start:end]==span), contradicciones etiquetadas, gaps; el LLM recibe el pack renderizado, no la nube de chunks |
| CB-6 | Conflict engine (2) | clasifica AGREEMENT/CONTRADICTION/METHODOLOGICAL_DIFFERENCE/UNRESOLVED sobre claims comparables; NUNCA promedia; respuesta declara conflictos |
| CB-7 | Temporal RAG (2) | superseded no se sirve como vigente; query histórica («en 2018») recibe la versión de esa ventana; sin fecha → UNDATED declarado, nunca inventado |
| CB-8 | Causal RAG (4) | jerarquía ASSOCIATION→CAUSAL_SUPPORTED clasificada por marcadores; recomendación clínica con mejor nivel no-intervencionista → ABSTENCIÓN con reason; benchmark sintético mediador/confusor/colisionador con ground truth (se abstiene donde debe, permite donde hay RCT) |
| CB-12 | Failure Graph (5) | modos RETRIEVAL_MISS/CONFLICT_BLINDNESS/UNSUPPORTED_GENERATION/ABSTENTION_FAILURE registrados con coste medido (ms) por modo; ABSTENTION_FAILURE nunca se dispara con scorers honestos (test negativo) |
| CB-13 | Taxonomía de abstención (5) | NO_EVIDENCE (0 recuperado) vs INSUFFICIENT_EVIDENCE (recuperado pero cobertura insuficiente) distinguibles en la respuesta |
| CB-14 | Validación sintética (4) | fixtures causales sintéticos con ground truth ejecutados en el bucle (parte de CB-8); OMEGA-I2 real queda dependencia externa declarada |
| CB-15 | Multimodalidad (3) | extracción posicional de tablas (PyMuPDF) a bloques kind=table con caption; routing prioriza bloques tabla cuando la query lo pide; SIN modelo de visión → PARTIAL declarado honesto |

**Techo declarado del bucle:** CB-15 será PARTIAL (extracción posicional sin comprensión visual). El resto aspira a DONE con evidencia. El % se recalcula con fórmula (completos + 0,5×parciales)/15 desde el script, nunca a mano.

## Registro de decisiones delegadas (autoridad plena ejercida)

1. **Embedder:** fastembed ONNX (`multilingual-e5-small`) local en Mac — soberano, sin torch, etiqueta `embedding_model` real; si la descarga falla → CB queda con embedder hashing-dev y el benchmark de fusión se acota a structural (declarado, no silencioso).
2. **Cross-encoder:** fastembed `TextCrossEncoder` (ms-marco-MiniLM ONNX) si está disponible; etiquetado con su límite (entrenado EN).
3. **Motor LangGraph intacto:** las capacidades nuevas entran como parámetros opcionales con defaults = comportamiento actual exacto.

Sello: sha256 registrado en STATE.json al iniciar el bucle.

---

## Adenda 1 (14-oct-2026) — criterio honesto del 100% para CB-15

Corrige el riesgo de 100%-falso identificado en la revisión externa (un
env-var no puede sustituir capacidad). Regla vinculante desde esta adenda:

1. CB-15 = DONE **sólo** si existe capacidad de visión REAL verificada por
   código (`vision_available()` = import efectivo de Docling/TableFormer; un
   env-var a lo sumo DESHABILITA, jamás habilita por afirmación).
2. Además, la suite debe contener tests que **ejerciten la rama de visión**
   (identificables por nombre) y que pasen sin depender del fallback. La
   cascada declara cada salto de vía en `EXTRACTOR_EVENTS` (jamás silencioso).
3. Sin capacidad o sin tests de la rama → CB-15 permanece PARTIAL y el bucle
   NO puede reportar 100% (exit 75 con bloqueo declarado).
4. Docling es la vía de visión por coherencia de proyecto (parser primario
   declarado en pyproject.toml), no una dependencia nueva para cerrar score.

Re-sellado deliberado: STATE.json actualizado con el sha del prereg
adendado; el sha anterior (5ad4308b) queda en el historial de STATE.
