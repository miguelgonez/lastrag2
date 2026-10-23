# Release notes — lastrag-foundation

## v2.1.0 (2026-10-23) — capas de grado médico 3-5 + instrumentos de curación

Empaqueta: política de abstención grado médico (`223f981`) · capa 3 anclaje
claim↔evidencia congelada (`d4d6a18`) · capa 4 verificador con métodos
léxico/semántico/juez (`d947e21`) · capa 5 cualificación de la fuente
(`b1ea6a6`) · auditoría de calidad 21 defectos + 22 regresiones (`e0c10fd`) ·
instrumentos de curación: 48 sociedades acreditadas del catálogo GuíaSalud +
proceso de retractaciones PubMed/RWDB (`2ec4fe2`) · acta de la ventana del
23-oct: E2E capas 3-5 con juez ALIA real 3 PASS + benchmark con juez real
(`26b1830`) · suite ejecutable (`82cd1af`).

### ⚠️ CAMBIO DE COMPORTAMIENTO POR DEFECTO — decidido por el PI (22/23-oct)

**Esta release NO «preserva el comportamiento»: lo cambia a propósito.**
Quien rebase desde v2.0.0 debe saber que sus respuestas cambian:

- Sin evidencia → **abstención**, no conocimiento general.
- Frases no respaldadas por la evidencia congelada → **retiradas con marca**;
  contradicciones → respuesta retenida.
- Toda respuesta sale **`affirmable=false`** hasta que la curación del corpus
  estampe `source_meta` (tier + retraction_status + retraction_checked_at).
  Es el estado correcto y declarado, no un fallo.

### Compatibilidad de contrato

`CONTRACT_VERSION` **sigue en 1.0** — superficie pública intacta
(`VectorBackend`/`EvidenceChunk`/`RetrievalResult`/`health()`, `block_id →
Citation`, `LLMClient`/`LocalLLM` fail-closed, router, embedder inyectable
etiquetado, contrato de degradación). Las capas 3-5 añaden parámetros al
engine (`verification`, `source_policy`, `source_meta`) y campos de salida
aditivos; refuerzan la semántica que un consumidor puede asumir (cita
verificable, fallback declarado), jamás la debilitan. Validado por el
arquitecto el 23-oct con esta condición de redacción (canon 1.1.0:
compatibilidad por contratos, no por implementación).

### Evidencia de la release

- E2E soberano real con capas 3-5 y juez ALIA (Spark, 23-oct): **3 passed**.
- Verificador: **fugas 0** con juez real (y léxico solo); falsos bloqueos
  2/6 **declarados** — el error va siempre hacia el bloqueo, nunca hacia la
  fuga. Puerta a producción: medir tasa sobre las 24 consultas Wave 1 con
  umbral fijado ANTES (gate inicial propuesto ≤20% de claims respaldados
  retirados, arquitecto 23-oct).
- Suite: **172 pass / 3 skip** (ejecutada y verificada, 23-oct).
- Curación: instrumentos listos; ejecución sobre el piloto pendiente (dato,
  no motor — no bloquea I1, arquitecto 23-oct).

## v2.0.0 (2026-10-06)

Release definitivo del foundation: commit limpio `22519f48`, tree
`3182506b`, suite 26/26 desde checkout limpio. Identidad completa en
`FOUNDATION_VERSION.json` (state_pin). SUPERADO en su núcleo por T3
REAL_E2E_PASS (15-oct) — ver ROADMAP.
