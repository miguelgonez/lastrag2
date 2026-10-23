# BENCHMARK WAVE 1 — Protocolo congelado (15-oct-2026)

Preregistro del benchmark. Congelado ANTES de ejecutar (regla del proyecto:
criterio sellado antes del resultado). Harness: `bench/run_wave1.py`.

## Pregunta

¿El núcleo v2-foundation mejora la recuperación respecto a sí mismo por modos
y, en fase 2, respecto al baseline LastRAG-MD stable-v1.0 — o es una
reimplementación incompleta?

## Fase 1 (esta entrega): modos internos de v2-foundation

Corpus REAL: piloto PubMed (1.095 abstracts, 4 temas, E-utilities 5 años,
silver-gold declarado — `~/lastrag_pubmed_pilot` en el Spark; MANIFEST
2026-10-14). Se ingesta ÍNTEGRO (los 1.095; los 406 previos se re-upsertan
idempotentemente) en Qdrant local persistente (embedder de desarrollo
`local-hash-ngram-256-v1` DECLARADO) y en el árbol LastIndex del Neo4j T3.

Modos medidos (recuperación pura, sin LLM):
- `vector_only`: Qdrant real + enriquecimiento de citas por LastIndex.
- `index_only`: búsqueda estructural full-text de Neo4j.
- `hybrid`: fusión por locator (structural primero) de ambos, como el motor.
- `graph_context`: disponibilidad de nodos del grafo clínico por consulta
  (Neo4jGraphManager sobre el T3; se mide cuántas consultas obtienen contexto).

## Consultas congeladas (24, 6 por tema, español clínico)

Metolido = tema de sourcing. La lista literal vive en `bench/run_wave1.py`
(`FROZEN_QUERIES`); cualquier cambio de una sola consulta exige re-sellar
este protocolo con nueva fecha.

## Métricas

- `topical_precision@5`: fracción de los 5 resultados cuyo documento es del
  tema de la consulta.
- `first_hit_mrr`: reciprocidad del primer resultado del tema correcto.
- `citation_support@5`: fracción de resultados con cita resuelta del árbol
  (block_id → documento). Un sistema que no puede citar no puntúa.
- `latency_ms` p50/p95 por modo (recuperación; el LLM NO entra en fase 1).
- `empty_rate`: fracción de consultas sin ningún resultado (abstención de
  recuperación).

## Oro y sus límites (declarados)

El oro es TEMÁTICO (etiqueta de sourcing), no relevancia clínica adjudicada:
mide pureza temática de la recuperación, no calidad de respuesta. Con
~250-280 documentos por tema, recall@5 clásico es trivialmente pequeño y NO
se reporta como tal; la métrica primaria es `topical_precision@5`.
Ningún número de esta fase acredita calidad clínica.

## Limitaciones declaradas

1. Embedder de desarrollo (hash n-gramas, NO semántico): los números de
   `vector_only`/`hybrid` son cota inferior del camino, no del diseño.
2. LastRAG-MD stable-v1.0 NO corre en esta fase (requiere su entorno del
   Spark en backups): la comparación con el baseline es FASE 2, con su
   propio arnés y sin tocar este protocolo.
3. Latencia de QA completa (con ALIA) se reporta aparte como medición
   preliminar del E2E del 15-oct; no forma parte de la fase 1.

## Criterio de publicación de resultados

Se publican TODOS los números del harness tal cual salgan, incluidos modos
que salgan mal (p. ej. si `index_only` supera a `vector_only` con el embedder
de desarrollo, se declara y se atribuye al embedder, no se maquilla).
Resultados en `bench/results/` con fecha y hash del harness.
