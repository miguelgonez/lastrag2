# PREREG — Calidad de retrieval sobre corpus biomédico REAL (piloto)
**Sellado ANTES de descargar el primer abstract. Fecha: 2026-10-14.**

## Fase 0 — Subset controlado (NO todo PubMed)

- **Volumen piloto:** ~1.200 abstracts (4 temas × 300, últimos 5 años,
  con abstract no vacío). El salto a 50–100 k está FUERA de este prereg y
  exige expediente propio (el propio plan lo ordena: validar antes de escalar).
- **Temas (sourcing por término PubMed):**
  1. `sglt2` — inhibidores de SGLT2 (diabetes)
  2. `metformin` — metformina en diabetes (distractor CERCANO de sglt2)
  3. `heart_failure` — insuficiencia cardíaca / terapia
  4. `lung_screening` — cribado de cáncer de pulmón
- **Esquema:** `pmid, title, abstract, pub_date, mesh_terms, doi, language,
  topic` (etiqueta de sourcing), volcado a `data/pubmed_pilot.parquet` +
  `.jsonl`. Fuente: NCBI E-utilities (esearch + efetch, sin clave, ≤3 req/s).

## Gold (declaración honesta del proxy)

- **Gold = etiqueta del término de sourcing** que recuperó cada abstract
  (proxy de relevancia topical AUTOMÁTICO, sin anotación humana). Se declara
  como silver-gold: mide si el pipeline recupera el tema correcto desde una
  consulta clínica en ESPAÑOL contra abstracts en INGLÉS (test cross-lingual
  real, no anotación de relevancia clínica fina).
- **Consultas (ES, 4, una por tema):** paráfrasis clínicas sin calco léxico
  del término MeSH (p. ej. la query de sglt2 no contiene "SGLT2").
- La pareja sglt2/metformin es deliberadamente cercana: un baseline léxico
  debe confundirlas; es la dureza mínima exigible al piloto.

## Métricas y gate

- recall@1, recall@3, MRR sobre el pool completo (4 temas mezclados).
- Vías: baseline hashing-dev vs pipeline real (MiniLM ONNX → reranker clínico
  → cross-encoder ONNX si disponible, con ausencia declarada).
- **Gate de mejora:** Δ recall@1 ≥ 0.25 (más bajo que el sintético 0.3 porque
  el corpus real es más difícil y el gold es proxy) O MRR > baseline + 0.10.
- **N-verde = 2** pasadas consecutivas con mejora.
- Recibos: `cierre_brecha_real/QUALITY_CORPUS_REAL.json` + `QUALITY_STATE.json`.

## Claim limits (vinculantes)

1. Mide **recuperación** sobre abstracts públicos con gold proxy topical.
   NO mide relevancia clínica fina, NO validez clínica, NO generación.
2. Cross-lingual ES→EN declarado; el rendimiento en monolingüe EN puede diferir.
3. Nada de esto habilita uso asistencial; CausalGate/Evidence Pack intactos.
4. Escala 50–100 k y/o Apache Spark (Delta particionado) en el host Spark:
  fases siguientes con expediente propio; este prereg cubre SOLO el piloto.

## Reglas de ejecución

- Exit codes: 0 = mejora + N-verde · 75 = sin mejora o N-verde incompleto ·
  1 = error (descarga/embedder). Jamás éxito falso; ausencias declaradas.
- Si PubMed no responde (red), se declara y termina en 1 SIN inventar datos.
- Los embeddings del pool se cachean (`data/embeddings.npz`) con hash del
  corpus: si el corpus cambia, se recalculan (sin medir contra caché vieja).
