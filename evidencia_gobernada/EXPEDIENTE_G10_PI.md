# Expediente PI — G10 validación clínica (BORRADOR para decisión del PI)

**Estado:** BORRADOR preparado por el agente (24-oct). G10 exige panel clínico
externo por especialidad y comparadores; **sin los nombres del PI la puerta
queda UNKNOWN, que es la verdad.** Este documento es el protocolo que el
panel recibiría; nada está ejecutado.

## Propuesta de protocolo (preregistrable, ciego)

- **Diseño:** evaluación ciega por pares de clínicos externos (no implicados
  en el desarrollo) de respuestas del motor vs. comparadores, sobre las 24
  consultas congeladas de Wave 1 + ≥50 consultas nuevas muestreadas de uso
  real previsto (Atención Primaria, cardionefrometabólico).
- **Cegamiento:** cada ítem se presenta anonimizado y en orden aleatorio; el
  evaluador no sabe qué sistema lo produjo ni qué versión es.
- **Comparadores (mínimo 2):** (a) respuesta redactada por clínico con acceso
  a las mismas fuentes (techo); (b) motor con capas 1-5 (juez activo);
  opcional (c) motor sin capa 5 (para medir el valor añadido de la
  procedencia).
- **Métricas preregistradas (a fijar ANTES de ver datos):** utilidad clínica
  por ítem (Likert 1-5 con definición operativa), errores factuales por
  afirmación (sobre las SUPPORTED), abstenciones apropiadas (la abstención
  correcta puntúa, no resta), y **daño = 0 como criterio de parada**: todo
  evento de potencial daño clínico detiene la evaluación y escala al PI.
- **Tamaño:** ≥3 evaluadores por especialidad (medicina familiar, endocrino,
  nefrología, cardiología — los 6 temas del corpus), ≥200 ítems totales.
- **Firma:** preregistro sellado por sha256 ANTES del primer evaluador
  (misma regla que G6/G4), incluidas las métricas y el criterio de daño.

## Lo que el PI decide

1. **Nombres del panel** (o la vía para reclutarlo: colegios, servicios).
2. Comparadores definitivos y presupuesto de tiempo del panel.
3. Aprobación del preregistro antes de sellarlo.

## Lo que G10 NO acredita aunque pase

Capacidad clínica autónoma: es evidencia de utilidad percibida y seguridad
bajo comparación controlada, con vigencia ligada al corpus/versión medidos.
