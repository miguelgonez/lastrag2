# PREREG — Escala 50 k abstracts (expediente propio, sellado ANTES de descargar)
**Sellado:** 2026-10-14 · **Depende de:** piloto 1.095 (Fases 0–2 verificadas).
**Recurso opcional:** Picasso B200 (SCBI) para embeddings GPU; si no está
disponible o la cola no coopera, el loop corre local/ONNX (M4 Pro) y lo declara.

## Volumen y fuente
- **Objetivo: 50.000 abstracts** (tramo bajo del rango 50–100 k; ir a 100 k
  exige solo cambiar PER_TOPIC y re-sellar). 4 temas × 12.500, últimos 5 años,
  con abstract sustancial (≥200 chars), dedupe por PMID.
- Fuente: NCBI E-utilities (esearch paginado + efetch por lotes de 200,
  ≤3 req/s sin clave). Descarga **resumible** (estado por tema).
- **Gold PRIMARIO: MeSH-estricto** — un abstract es gold del tema T sólo si
  su `mesh_terms` contiene el descriptor canónico de T:
  sglt2→"Sodium-Glucose Transporter Inhibitors" · metformin→"Metformin" ·
  heart_failure→"Heart Failure" · lung_screening→"Lung Neoplasms".
  Los abstracts del sourcing SIN el descriptor quedan en el pool como
  distractores (dureza extra, declarada). **Fallback declarado:** si la
  cobertura MeSH-estricto de un tema fuera <30%, ese tema puntúa con
  silver-gold por sourcing y se etiqueta en el recibo.
- Consultas: las mismas 4 clínicas en español del piloto (cross-lingual).

## Métricas y gate
- recall@1, p@3, MRR sobre el pool completo, gold MeSH-estricto.
- Vías: baseline hashing-dev vs pipeline real (MiniLM ONNX → reranker
  clínico → cross-encoder ONNX con marcador anti-FALLBACK).
- **Gate conservador: Δ recall@1 ≥ 0.15** (volumen + gold más duro) o
  MRR > baseline + 0.08. **N-verde = 2.**
- Recibos: `cierre_brecha_real/QUALITY_SCALE.json` + `QUALITY_SCALE_STATE.json`.

## Claim limits (vinculantes)
1. Recuperación sobre abstracts públicos. NO relevancia clínica fina, NO
   validez clínica, NO generación.
2. Si se usa Picasso B200: se declara recurso y modelo; el hardware no
   aporta calidad clínica — solo cómputo.
3. CausalGate / Evidence Pack / 100 % de las 5 olas permanecen intactos;
   el loop maestro debe seguir en verde tras cada pasada de escala.

## Reglas de ejecución
- Exit: 0 = mejora + N-verde · 75 = sin mejora o N-verde incompleto · 1 = error.
- Embeddings cacheados por hash del corpus (npz); corpus distinto = recalculo.
- Descarga fallida (red/PubMed) → se declara y exit 1 sin inventar nada.
- Resumabilidad: un tema completo no se vuelve a descargar.

---

## Adenda 1 (14-oct, ANTES de cualquier medición de escala)

El acceso E-utilities está capado a ~10 k resultados accesibles por consulta
esearch (ventana de relevancia); con los términos sellados el pool filtrado
fue 24.921 (metformin 2.664). Para alcanzar el objetivo de 50 k sin tocar
métricas ni gates (intactos), la descarga se **trocea por año** (5 slices
anuales × tema, hasta 2.500 por slice, mismas restricciones de abstract).
Nada de lo ya sellado cambia: gold MeSH-estricto, gate Δ≥0.15, N-verde=2,
claim limits. El MANIFEST final declara el volumen realmente entregado.

## Adenda 2 (14-oct, antes de medir): +2 temas dentro de las áreas selladas

Los 4 términos originales agotan su pool en 27.737 (dos intentos
documentados). Para el objetivo de 50 k se añaden dos temas DENTRO de las
áreas ya declaradas (diabetes, cardiovascular):
  - t2d_general: "Diabetes Mellitus, Type 2"[MeSH] (gold MeSH idem)
  - hypertension: "Antihypertensive Agents"[MeSH] OR hipertensión/terapia
    (gold MeSH: "Hypertension")
Misma ventana 5 años, mismos filtros, mismos gates Δ≥0.15 y N-verde=2.
Queries ES añadidas al loop (paráfrasis, sin calco del descriptor).
