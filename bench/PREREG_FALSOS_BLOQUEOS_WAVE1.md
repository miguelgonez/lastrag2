# PREREGISTRO — Falsos bloqueos del verificador sobre Wave 1 (puerta a)

**Congelado ANTES de ejecutar (23-oct-2026).** Regla del proyecto: criterio
sellado antes del resultado. Condición del arquitecto (23-oct): umbral fijado
antes de medir. Harness: `bench/falsos_bloqueos_wave1.py`.

## Pregunta

¿Qué tasa de falsos bloqueos produce la capa 4 (verificador con juez ALIA
real + método semántico) sobre respuestas REALES generadas para las 24
consultas congeladas de Wave 1 — y esa tasa está por debajo del gate?

## Gate (sellado)

**APROBADO si: falsos_bloqueos / retiradas_adjudicables ≤ 0.20 (20%).**
Denominador: retiradas adjudicadas por el árbitro como A (falso bloqueo) o
B (retirada correcta). Las C (indecidibles) y las respuestas retenidas
enteras se cuentan y declaran aparte; no entran al denominador. El gate es
provisional («revisable con datos», arquitecto 23-oct).

## Montaje (idéntico al congelado de Wave 1 salvo la variable medida)

- Corpus: piloto PubMed 1.095 (parquet, Spark), Qdrant local + árbol Neo4j
  T3, **embedder de desarrollo hash para RECUPERACIÓN** — la recuperación no
  es la variable: solo cambia generación + capa 4.
- Generación: LocalLLM → ALIA real (`:8024`, `alia-nexthealth`, ventana 4096).
- Capa 4: `verification="declare"` (instrumentación: el modo block produce
  LOS MISMOS veredictos — `verify()` es el mismo — pero declare expone todos
  los claims sin redactar el texto) · `ClaimVerifier(embedder=FastEmbed
  MiniLM multilingüe 384d, judge=LocalLLM(ALIA))` — juez ACTIVO.

## Adjudicación independiente (anti-circularidad)

Cada claim con veredicto UNSUPPORTED se somete a ALIA en un prompt MCQ
**mínimo y distinto** (sin ejemplos — lección del 15-oct: el ejemplo guiado
desestabiliza), contra los fragmentos congelados de ESA consulta:

```
Afirmación: <claim>

Evidencia:
<fragmentos congelados de la consulta>

¿La afirmación está respaldada por la evidencia? Responde solo una letra.
A — Sí, respaldada
B — No respaldada
C — No se puede decidir
```

**A = falso bloqueo** (el verificador retiró algo respaldado) · **B =
retirada correcta** · **C = no adjudicable** (fuera del denominador).

**Límite declarado:** el árbitro es el mismo modelo que generó y juzgó —
posible sesgo pro-propio. Es el mejor árbitro disponible sin humano y el
gate es provisional; una auditoría humana de una muestra queda como
siguiente paso si el resultado está en la banda 15-25%.

## Métricas registradas

1. `tasa_falsos_bloqueos_adjudicables` = A / (A+B) — **la del gate**.
2. `retiradas_sobre_total_claims` = unsupported / claims_contables —
   secundaria, contexto.
3. Por consulta: claims totales, SUPPORTED/UNSUPPORTED/CONTRADICTED/META,
   método decisor de cada veredicto, adjudicaciones, respuestas retenidas.

Salida: `bench/results/falsos_bloqueos_wave1.json` + recibo con fecha,
evidence_hash por consulta y versiones (release, imagen vLLM, modelo juez).
