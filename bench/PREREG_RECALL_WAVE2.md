# PREREGISTRO — G6 recuperación (recall@20 ≥ 0,9 · p50 < 1 s) — WAVE 2

**Congelado ANTES del primer run de medición** (regla del proyecto; gate G6
del plan sellado). Harness: `bench/run_recall.py`. Sello: el sha256 de este
fichero queda registrado en el commit que lo publica; cambiar una consulta o
el oro exige re-sellar con nueva fecha.

## Pregunta

¿Qué embedder (MiniLM multilingüe vs bge-m3) sobre Qdrant local alcanza
**recall@20 ≥ 0,9 con p50 < 1 s** en el corpus de escala, y cuál es el mejor
candidato declarado?

## Oro (preregistrado, silver temático declarado)

- Corpus: escala 48.399 abstracts (6 temas; `MANIFEST_SCALE.json`).
- **Positivos por tema** = documentos cuyo `mesh_terms` contiene el
  descriptor canónico MeSH-estricto del tema (los mismos de
  `calidad_scale_loop.py`: sglt2 'Sodium-Glucose Transporter 2 Inhibitors',
  metformin 'Metformin', heart_failure 'Heart Failure', lung_screening el
  descriptor de cribado, t2d_general 'Diabetes Mellitus, Type 2',
  hypertension 'Hypertension').
- **Oro por consulta** = **10 PMIDs muestreados SIN REPOSICIÓN de los
  positivos del tema, con seed fija 20261024 y orden lexicográfico de PMIDs**
  (reproducible sin ambigüedad). Si un tema tuviera <10 positivos, el oro es
  todos sus positivos (se declara).
- **Límite declarado:** es oro temático silver — espacios clínicos
  solapados (metformin/t2d comparten positivos potenciales); el recall aquí
  mide cobertura del TEMA, no pertinencia fina.

## Métricas (fijas antes de medir)

- `recall@20` = |top-20 ∩ oro| / |oro|, promediado sobre las 108 consultas.
  **Gate: ≥ 0,9.**
- `p50_ms` por consulta (embeddeo de la consulta + búsqueda Qdrant, sin LLM).
  **Gate: < 1.000 ms.**
- Por candidato: MiniLM (`paraphrase-multilingual-minilm-onnx-v1`, fastembed,
  CPU) y `BAAI/bge-m3` (sentence-transformers, torch). Colecciones Qdrant
  locales SEPARADAS por embedder (ninguna reutiliza índices del otro).
- Reranker (`CrossEncoderReranker`): opcional, se reporta aparte como
  `alternatives`; NO entra en el gate principal.

## Las 108 consultas congeladas (18 por tema, español clínico)

La lista literal vive en `bench/run_recall.py` (`FROZEN_QUERIES_G6`); se
congela junto a este documento en el mismo commit. Cambiar una consulta
exige re-sellar este prereg.

## Prohibido

Mocks · medir con un subconjunto del corpus sin declararlo · tocar los
umbrales del plan · «tunar» consultas tras ver resultados (cualquier cambio
de consulta = nuevo prereg). El candidato declarado como mejor es el que
midieron estas consultas y este oro, nada más.
