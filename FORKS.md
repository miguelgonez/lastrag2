# Registro de forks — lastrag-foundation (master)

**Ubicación maestra:** `/Users/yeye/Documents/06_DESARROLLO_TECNOLÓGICO/Entorno_Desarrollo/py/Py_LastRAG_Index`
**Qué es esto:** la instalación maestra de LastRAG 2.0 Foundation, componente horizontal de OMEGA-MR2. No pertenece a ningún proyecto concreto y ningún proyecto consume este árbol directamente en producción.
**Política:** canon `OMEGA-MR2-LASTRAG-FOUNDATION-CANON` v1.3.0 — *forkable but contract-compatible*.
**Release anclado:** `v2.0.0` = commit `22519f48` (6-oct-2026, suite 26/26). Identidad completa en `FOUNDATION_VERSION.json`.

## Procedimiento de fork (proyecto nuevo)

1. **Crear el fork:** `scripts/fork.sh /ruta/al/proyecto/lastrag-foundation NombreProyecto`
   Clona el master completo (historia incluida, para poder comparar/difuminar con upstream) y estampa `FORK.json` con la procedencia exacta: commit y tree del master, fecha, canon y política.
2. **El master es intocable desde los forks.** Las necesidades del proyecto se desarrollan en el fork (canon 1.3.0: la integración no modifica el árbol sellado in situ; v2.0.0 queda como baseline inmutable).
3. **Divergencia hacia arriba:** si una mejora desarrollada en un fork es horizontal (sirve a todos), se propone como commit a este master con changelog explícito. Jamás edición silenciosa del master.
4. **Compatibilidad por contratos, no por implementación** (canon 1.1.0): un fork sigue siendo compatible mientras mantenga la superficie de `CONTRACT_VERSION 1.0` (ver `FOUNDATION_VERSION.json`). Cambios internos no rompen el contrato; cambiar firmas/estructuras de la superficie o su semántica contractual sí, y exige declararlo.
5. **Registrar el fork** en la tabla de abajo (append; no reescribir filas existentes).

## Política de grado médico (obligatoria para todo fork)

`NH-GRADO-MEDICO-001` (22-oct-2026) — *«si no lo sabe, lo dice, antes de
inventar»*. Tres capas por **código**, heredadas del master por defecto:
(1) sin evidencia el LLM no se invoca; (2) una salida «desde conocimiento
general» no se entrega; (3) anclaje claim↔evidencia congelada — lo no anclado
no se entrega. Desactivarlas (`grounding="off"`,
`allow_general_knowledge=True`) es explícito, viaja en cada respuesta
(`features.generation_policy`) y exige justificación en el expediente del
fork. Doctrina y estado por producto:
`~/Documents/01_PROYECTOS_ACTIVOS/Pyto. NextHealth Ecosistema. 2026/03_Tecnico_y_Producto/NEXTHEALTH_ADLC_20261005/framework/NEXTHEALTH_GRADO_MEDICO.md`

Procedencia honesta: la capa 3 NO nació aquí. Operaba ya en AESPLA-PRL
(`lastrag2.py`) y FIMABIS (`sovereign.py`); el upstream era la pieza más débil
de la familia. Se porta al master como mejora horizontal (regla 3 del
procedimiento de fork) para que ningún producto futuro tenga que reinventarla.

## Registro de forks y consumidores

| Fork / consumidor | Tipo | Derivado de | Estado | Evidencia de procedencia |
|---|---|---|---|---|
| omega-sovereign-evidence | dependencia lógica (integración I1) | v2.0.0 | integración abierta por el PI (canon 1.3.0) | `FOUNDATION_VERSION.json` → `consumers_declared` |
| AESPLA-PRL (Laboral.IA) | adaptación de la capa de doctrina (`lastrag2.py`: congelación, anclaje, citas fail-closed) | era v2.0.0 (oct-2026) | producción | sha256 `af3303f1…e3ac8` · `~/ZCodeProject/aespla-prl/backend/app/lastrag2.py` |
| UrbaLex | solución sovereign (decide/conversacional sobre el contrato) | era v2.0.0 (oct-2026) | producción en VPS (`/opt/nexthealth/urbanal/runtime/api`) | batería de contrato 6-oct · `~/Documents/New project/URBALEX_GLINER_20260929/tests/test_lastrag2_contract.py` · ref `~/ZCodeProject/urbalex_lastrag2_ref/` |
| FIMABIS gemelo | solución sovereign (`sovereign.py`) | era v2.0.0 (oct-2026) | gemelo de QA (cumplimiento FastAnswer + lastRAG2) | sha256 `b456840a…f9040b` · `~/ZCodeProject/fimabis_gemelo/backend/sovereign.py` |
| `foundation_release_test` (omega_i2) | clon de verificación del release — **no es fork** | `22519f48` exacto | evidencia congelada de I2 | `~/ZCodeProject/omega_i2_20261011/evidence/foundation_release_test/` |

**Nota honesta de procedencia:** los tres consumidores existentes nacieron antes de este registro (22-oct-2026). Su columna «derivado de» es la mejor atribución verificable por fecha y contenido (era del release v2.0.0), no un estampado mecánico con `fork.sh`. Los forks creados a partir de ahora llevan `FORK.json` y quedan registrados aquí en el momento de su creación.
