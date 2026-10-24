# G12 — Paquete reproducible del banco del verificador (para el auditor independiente)

**Qué es:** el paquete mínimo con el que un tercio reproduce la medición de
**fugas 0** (G1) sin acceso a nada interno del equipo. G12 exige ese tercero;
su nombre lo nombra el PI.

## Instrucciones para el auditor

1. Clonar el repo público en el tag indicado (hoy: `v2.1.1`):
   ```bash
   git clone -b v2.1.1 https://github.com/miguelgonez/lastrag2.git
   cd lastrag2
   python3 -m venv .venv && .venv/bin/pip install -e . pytest
   ```
2. Ejecutar el banco sintético (14 casos con ground truth, léxico puro —
   no necesita LLM ni red):
   ```bash
   .venv/bin/python evidencia_gobernada/G12_AUDITOR_PACKAGE/run_bank.py
   ```
   Salida esperada si nada se ha tocado: **fugas 0** (ningún claim NO
   respaldado pasa como SUPPORTED). Los falsos bloqueos se REPORTAN, no se
   ocultan: son el coste declarado del fail-closed.
3. Auditoría del propio criterio: leer `core/rag/verifier.py`
   (`synthetic_verifier_cases` = los 14 casos literales con su ground truth;
   `run_verifier_benchmark` = la medición). Cualquier reto a un caso se
   documenta y escala — el banco es versión: cambiarlo exige commit y nueva
   medición de G1.
4. (Opcional, con LLM local) reproducir también el recibo con juez real
   siguiendo `evidencia_gobernada/produce_G1.py`.

## Qué acredita y qué no

Acredita: la propiedad *fugas = 0* del verificador léxico sobre el banco
sellado, reproducible por un tercero. NO acredita: calidad semántica, idoneidad
clínica, ni el comportamiento con juez (eso va en el recibo G1 firmado por
la ejecución, no en este banco).
