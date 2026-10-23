# Expediente PI — G5 (cobertura de corpus): escala y embedder

**Para:** decisión del PI (la puerta G5 del loop NH-EG-LOOP-001 queda UNKNOWN
hasta esta decisión + ejecución). **De:** zcode, 23-oct-2026.
**Fuente:** `~/lastrag_pubmed_pilot/PLAN_ESCALA.md` (Spark) + mediciones propias.

## Decisión 1 — Oleada de escala (bloquea G5; condiciona G6)

| Opción | Tamaño | Descarga | Coste real | Qué habilita |
|---|---|---|---|---|
| **OLEADA A — dominio prioritario** (cardio-renal-metabólico) | ~2-5M abstracts | 3-7 h/millón (con key gratuita del PI: paso humano único) | Moderado: Delta particionado; embeddings 6-15 GB cuantizados | Corpus real para Wave 1 fase 2 y G5/G6 con muestra ≥200 preguntas reales |
| OLEADA B — histórico completo | ~30M (~30M con abstract) | 42-70 h repartidas | Alto: Delta 15-25 GB · embeddings 46-92 GB (12-23 cuantizados) · Neo4j ~40 h de ingesta · Qdrant del Spark solo cuantizado/por dominios | Cobertura máxima; prerrequisito de producto, no del loop actual |

**Recomendación: OLEADA A ahora.** G5 exige ≥200 preguntas reales con <10%
«sin evidencia por corpus» — el dominio prioritario basta para medirlo; B
multiplica ×10 el coste sin cambiar la decisión del gate. B se decide tras
G6 medido con A. El block_id determinista ya soporta re-ingesta idempotente:
escalar después no invalida lo medido antes.

## Decisión 2 — Embedder definitivo (condiciona G6; hoy dev-hash declarado)

| Candidato | Evidencia medida | Veredicto |
|---|---|---|
| Hash dev (256d) | baseline rec@1 0.167 escala 48.399 | No semántico — solo baseline |
| PubMedBERT (biomed EN) | 0.667 EN pero **0.0 cross-lingual** (consultas ES) — medido en B200 | **Descartado** (negativo honesto, commits 3e2892c/0178f18) |
| **MiniLM multilingüe 384d (ONNX/CPU)** | **rec@1 0.833 · p@3 0.889 · MRR 0.917** sobre 48.399 con gold MeSH-estricto; método semántico del verificador APPLIED | **Recomendado como embedder de trabajo** |

**Recomendación:** MiniLM multilingüe cuantizado como embedder de trabajo en
Oleada A. Su calidad específica sobre corpus biomédico ES no se reclama sin
benchmark (`scripts/benchmark_fusion.py` con él = parte de G6); si un
embedder definitivo (p. ej. biomed multilingüe futuro) llega después, el
corpus se re-embebe — la decisión NO atrapa.

## Paso humano único que habilita la descarga

Key gratuita de E-utilities (NCBI) a nombre del PI → 10 req/s (sin key, el
barrido de G2 ya demostró que 3 req/s bastan para curar, pero la descarga de
millones lo agradece).

---

## Anexo — las otras puertas que esperan nombres del PI (permanecen UNKNOWN, que es la verdad)

| Puerta | Qué falta | Slot |
|---|---|---|
| G4 (falsos bloqueos) | Tu anotación humana de las 10 frases retiradas: `evidencia_gobernada/G4_ANOTACION_HUMANA.json` (marcar cada frase RESPALDADA/NO_RESPALDADA + tu nombre como anotador) | PI o clínico designado |
| G10 (validación clínica) | Panel de clínicos externos por especialidad + comparadores, evaluación ciega preregistrada | Nombre del panel/responsable |
| G11 (regulatorio) | Uso previsto firmado; clase MDR y riesgo AI Act | Firmante |
| G12 (auditoría externa) | Auditor independiente que reproduzca fugas 0 | Nombre del auditor |
