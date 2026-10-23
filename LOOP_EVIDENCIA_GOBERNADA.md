# Loop de evidencia gobernada — protocolo operativo para el agente (zcode)

**Id:** NH-EG-LOOP-001 · **Objetivo:** el mejor sistema de evidencia gobernada del mundo, definido como **las 13 puertas de `evidencia_gobernada/PLAN_GATES.json` en PASS**, no como una opinión.
**Marco:** NH-ADLC-001 (ninguna afirmación sin evidencia, ninguna evidencia sin procedencia, `UNKNOWN != PASS`) · doctrina NH-GRADO-MEDICO-001 · canon LASTRAG_FOUNDATION v1.3.0.

## El ciclo (una iteración = una puerta)

```bash
.venv/bin/python scripts/loop_evidencia_gobernada.py
```

1. **Medir.** El loop mide todas las puertas en orden congelado. `G0` (suite) y `G1` (fugas 0, léxico) se miden ejecutando; el resto se **recalcula** desde las métricas del recibo contra los umbrales sellados. Un campo `pass` en un recibo se ignora.
2. **Leer la SIGUIENTE ACCIÓN.** Es una sola puerta: la primera que no está en PASS. No se salta ninguna: el orden es la cadena de confianza (sin suite no hay fugas; sin fugas 0 no hay curación que valga; sin curación no hay afirmabilidad…).
3. **Producir el recibo** exactamente con lo que dice `produce`, en `evidencia_gobernada/receipts/<G>_*.json`:
   ```json
   {"gate": "G2", "measured_at": "2026-10-24T10:00:00Z", "by": "zcode@spark-3de7",
    "inputs_sha256": {"corpus_manifest": "…", "script": "…"},
    "metrics": {"corpus_docs": 48399, "checked_docs": 48399, "unknown": 0,
                "retracted": 12, "concern": 3, "max_check_age_days": 1,
                "sources": ["pubmed", "rwdb"], "source_meta_path": "…"}}
   ```
   Las métricas son **contables** y salen de la ejecución real. `inputs_sha256` ancla qué se midió. Si no se puede medir, **no se escribe recibo**: la puerta queda UNKNOWN, que es la verdad.
4. **Commit** por iteración: código + recibo + nota en `ROADMAP_FOUNDATION.md` con fecha y procedencia. Un recibo sin commit no existe.
5. **Re-ejecutar el loop.** Si la puerta pasa, la siguiente acción cambia. Si no, se corrige la causa, nunca el umbral.

## Códigos de salida y qué hacer

| rc | Significa | Acción del agente |
|---|---|---|
| **75** | verde hasta aquí, queda UNKNOWN | ejecutar la SIGUIENTE ACCIÓN impresa |
| **1** | FAIL, regresión (PASS→FAIL), recibo desaparecido o plan alterado | **parar** todo lo demás; arreglar la causa raíz; si es `G0`/`G1`, nada por encima es creíble |
| **0** | 13/13 PASS | re-ejecutar hasta 3 pasadas verdes consecutivas; después, el claim queda habilitado **con sus límites** (ver abajo) |

## Prohibiciones (la garantía depende de ellas)

- **No tocar `PLAN_GATES.json`.** Está sellado por sha256 en `STATE.json`; si cambia, el loop para. Cambiar un umbral exige versión nueva del plan + decisión escrita del PI + re-sellado deliberado (borrar `STATE.json`), y queda en el historial.
- **No escribir `pass` a mano, no bajar umbrales, no usar mocks** para un recibo. Un recibo producido con dobles es fabricación de evidencia.
- **No tocar recibos de puertas anteriores.** Si una medición anterior era errónea, se añade un recibo nuevo con fecha posterior y se anota la discrepancia; el loop usa el fichero del nombre canónico, así que renombrar el viejo a `<G>_<fecha>_superseded.json` deja el rastro.
- **No tocar producción** (VPS de UrbaLex, AESPLA en el Spark) ni árboles sellados (`omega_evidence_v07`) desde este loop.
- **No afirmar lo no medido.** El informe de cada iteración distingue preparado / integrado / publicado / verificado.

## Puertas que necesitan al PI antes de poder medirse

| Puerta | Decisión que falta |
|---|---|
| G5 cobertura | embedder + disco para la escala (PLAN_ESCALA A/B) |
| G10 validación clínica | panel de clínicos externos por especialidad y comparadores |
| G11 regulatorio | uso previsto firmado; clase MDR y riesgo AI Act |
| G12 auditoría externa | auditor independiente |

Cuando la SIGUIENTE ACCIÓN es una de estas, el agente **no la inventa**: deja la puerta UNKNOWN, prepara el expediente que el PI necesita para decidir (opciones, coste, evidencia) y pasa a trabajar en lo que no dependa de ella —solo si una puerta posterior puede medirse sin la anterior, cosa que el orden congelado ya decide.

## Parada por repetición

Tres iteraciones consecutivas con la misma puerta en FAIL = escalado al PI con el expediente de las tres (qué se midió, qué falló, qué se cambió). No se intenta una cuarta "a ver si".

## Qué significa exit 0 (y qué no)

Con 13/13 PASS y 3 pasadas verdes, el sistema puede sostener: *cada afirmación que entrega está respaldada por evidencia congelada, verificada frase a frase, de fuente cualificada a fecha, con cero fugas reproducidas por un tercero, latencia y cobertura medidas, y validación clínica ciega preregistrada*. Lo que **no** puede sostener ni con exit 0: capacidad clínica o conformidad regulatoria por sí mismo — G10 y G11 son evidencia de terceros y firmas, y su vigencia caduca con el corpus, el modelo y la norma. El loop se re-ejecuta tras cada cambio de cualquiera de los tres.
