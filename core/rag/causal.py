"""
LastRAG v2 — Ola 4: Causal RAG — de la correlación a la causalidad
===================================================================
Compromiso s9 del deck: «asociado con» no es «causa». Jerarquía explícita:

  ASSOCIATION(1) → TEMPORAL(2) → MECHANISTIC(3) → CAUSAL_CANDIDATE(4)
  → CAUSAL_SUPPORTED(5)

  - ASSOCIATION: co-ocurrencia (correlación, «se relaciona»).
  - TEMPORAL: orden temporal sin intervención.
  - MECHANISTIC: mecanismo biológico propuesto (vía, mediador).
  - CAUSAL_CANDIDATE: evidencia de intervención (RCT) sin estimando claro.
  - CAUSAL_SUPPORTED: intervención + dirección del efecto medida.

CausalGate: una recomendación clínica («debo administrar…») exige evidencia
de INTERVENCIÓN. Si el mejor nivel disponible es observacional, el sistema
SE ABSTIENE con la razón escrita — la frontera entre observar y recomendar
es código, no prosa del LLM.

Benchmark sintético OMEGA-style: escenarios mediador/confusor/colisionador
con ground truth conocido (los genera el harness, no la literatura).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .pack import Claim

ASSOCIATION, TEMPORAL, MECHANISTIC, CAUSAL_CANDIDATE, CAUSAL_SUPPORTED = \
    "ASSOCIATION", "TEMPORAL", "MECHANISTIC", "CAUSAL_CANDIDATE", "CAUSAL_SUPPORTED"
LEVEL_ORDER = {ASSOCIATION: 1, TEMPORAL: 2, MECHANISTIC: 3,
               CAUSAL_CANDIDATE: 4, CAUSAL_SUPPORTED: 5}

_INTERVENTION = ("ensayo aleatorizado", "aleatorizado", "aleatorizada",
                 "randomiz", "doble ciego", "double ciego", "grupo control",
                 "placebo", "meta-análisis", "meta-analisis")
_MECHANISTIC = ("mecanismo", "vía ", "via ", "media la", "media el",
                "inhibe", "bloquea", "agonista", "antagonista",
                "regula la expresión", "regula la expresion")
_TEMPORAL = ("longitudinal", "seguimiento", "tras la exposición",
             "tras la exposicion", "posteriormente", "a lo largo de")
_ASSOCIATION = ("asociado", "asociada", "asociación", "asociacion", "se asocia",
                "correlacion", "correlación", "se relaciona", "prevalencia",
                "cohort observacional", "observacional")
_EFFECT_DIR = ("reduce", "disminuye", "mejora", "aumenta", "eleva",
               "previene", "empeora")


def classify_claim(text: str) -> Optional[str]:
    """Clasifica el nivel causal de un claim por marcadores deterministas.
    None = sin contenido causal medible."""
    low = text.lower()
    has_intervention = any(m in low for m in _INTERVENTION)
    has_effect = any(m in low for m in _EFFECT_DIR)
    if has_intervention and has_effect:
        return CAUSAL_SUPPORTED
    if has_intervention:
        return CAUSAL_CANDIDATE
    if any(m in low for m in _MECHANISTIC):
        return MECHANISTIC
    if any(m in low for m in _TEMPORAL):
        return TEMPORAL
    if any(m in low for m in _ASSOCIATION):
        return ASSOCIATION
    return None


def classify_claims(claims: list[Claim]) -> dict[str, Optional[str]]:
    """locator → nivel causal. Es el mapa que consume
    `pack.extract_claims(causal_levels=...)`, que busca por `chunk.locator`.

    Antes se devolvia indexado por `statement`: ninguna clave casaba con un
    locator, asi que etiquetar el Evidence Pack con esta funcion no fallaba —
    simplemente no etiquetaba nada. Un no-op silencioso en la capa que separa
    asociacion de causa.
    """
    out: dict[str, Optional[str]] = {}
    for c in claims:
        level = classify_claim(c.statement)
        for span in c.spans:
            locator = span.chunk_locator
            if not locator:
                continue
            # Un locator puede aportar varios claims: gana el nivel mas alto.
            previous = out.get(locator)
            if level and (previous is None
                          or LEVEL_ORDER[level] > LEVEL_ORDER[previous]):
                out[locator] = level
            else:
                out.setdefault(locator, previous)
    return out


_RECOMMENDATION = ("debo", "debería", "deberia", "recomienda", "recomiendas",
                   "administrar", "prescribir", "tratar con", "tratarlo con",
                   "es eficaz", "usar", "utilizar", "dosis de")


@dataclass
class CausalVerdict:
    allowed: bool
    best_level: Optional[str]
    reason: str
    abstention: Optional[str] = None
    levels_found: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "best_level": self.best_level,
                "reason": self.reason, "abstention": self.abstention,
                "levels_found": self.levels_found}


class CausalGate:
    """Frontera correlación→recomendación. Si la consulta pide una
    recomendación y la mejor evidencia no es de intervención, ABSTENCIÓN."""

    def is_recommendation(self, query: str) -> bool:
        low = query.lower()
        return any(m in low for m in _RECOMMENDATION)

    def check(self, query: str, claims: list[Claim]) -> CausalVerdict:
        levels: dict[str, int] = {}
        for c in claims:
            lvl = classify_claim(c.statement)
            if lvl:
                levels[lvl] = levels.get(lvl, 0) + 1
        best = max(levels, key=lambda l: LEVEL_ORDER[l]) if levels else None
        asks_rec = self.is_recommendation(query)
        if not asks_rec:
            return CausalVerdict(True, best,
                                 "consulta no-recomendativa: la jerarquía se "
                                 "informa sin restricción", levels_found=levels)
        if best is None:
            return CausalVerdict(
                False, None,
                "CAUSAL_GATE: recomendación sin evidencia causal clasificable",
                abstention=("No hay evidencia con contenido causal en los "
                            "documentos indexados; una recomendación clínica "
                            "requeriría ensayos de intervención."),
                levels_found=levels)
        if LEVEL_ORDER[best] <= LEVEL_ORDER[MECHANISTIC]:
            return CausalVerdict(
                False, best,
                f"CAUSAL_GATE: recomendación requiere evidencia de intervención; "
                f"mejor nivel disponible = {best}",
                abstention=(f"La evidencia disponible es de nivel {best} "
                            "(observacional/mecanística). No puedo elevar una "
                            "asociación a recomendación terapéutica: confundir "
                            "señal con causa es el error que este sistema "
                            "declina cometer. Se requiere evidencia de "
                            "intervención (ensayo aleatorizado)."),
                levels_found=levels)
        return CausalVerdict(True, best,
                             f"recomendación respaldada por evidencia de "
                             f"intervención ({best})", levels_found=levels)


# ============================================================
# Benchmark sintético con ground truth (estilo laboratorio OMEGA)
# ============================================================

@dataclass
class CausalScenario:
    name: str                      # mediador | confusor | colisionador | causa_real
    query: str                     # consulta (recomendativa o no)
    evidence_texts: list[str]      # textos de evidencia
    expect: str                    # ALLOW | ABSTAIN
    ground_truth: str              # explicación del mecanismo verdadero


def synthetic_causal_scenarios() -> list[CausalScenario]:
    return [
        CausalScenario(
            name="confusor",
            query="¿Debo limpiarle los dedos amarillos para reducir el riesgo de cáncer de pulmón?",
            evidence_texts=[
                "Estudio observacional: los pacientes con dedos amarillos presentan mayor prevalencia de cáncer de pulmón (asociación estadística).",
                "El tabaquismo se asocia tanto a la pigmentación de los dedos como al cáncer de pulmón; es una causa común.",
            ],
            expect="ABSTAIN",
            ground_truth="tabaco = confusor (causa común); limpiar dedos no cambia el riesgo",
        ),
        CausalScenario(
            name="mediador",
            query="¿Recomiendas alquitran_parches para prevenir el cáncer? ¿debo usar el fármaco X?",
            evidence_texts=[
                "El alquitrán media la vía entre el tabaco y el daño celular; mecanismo propuesto en modelos in vitro.",
            ],
            expect="ABSTAIN",
            ground_truth="alquitrán = mediador (en el camino causal); sin ensayo de intervención no hay recomendación",
        ),
        CausalScenario(
            name="colisionador",
            query="¿Debo asumir que ser atractivo reduce el talento en actores?",
            evidence_texts=[
                "En la muestra de actores famosos se observa una asociación inversa entre atractivo y talento.",
                "El éxito en Hollywood requiere talento o atractivo: condicionar por éxito induce una asociación espuria.",
            ],
            expect="ABSTAIN",
            ground_truth="éxito = colisionador; la asociación inversa es sesgo de selección",
        ),
        CausalScenario(
            name="causa_real",
            query="¿Debo administrar metformina como primera línea en DM2?",
            evidence_texts=[
                "Ensayo aleatorizado doble ciego: la metformina reduce la hemoglobina glucosilada frente a placebo.",
                "Meta-análisis de ensayos aleatorizados: la metformina disminuye la progresión a complicaciones.",
            ],
            expect="ALLOW",
            ground_truth="evidencia de intervención con dirección del efecto → CAUSAL_SUPPORTED",
        ),
        CausalScenario(
            name="consulta_descriptiva",
            query="¿Qué factores se asocian con la mortalidad en insuficiencia cardíaca?",
            evidence_texts=[
                "Estudio de cohorte observacional: la anemia se asocia con mayor mortalidad en insuficiencia cardíaca.",
            ],
            expect="ALLOW",
            ground_truth="consulta no-recomendativa: la asociación se informa como asociación",
        ),
    ]


def run_causal_benchmark() -> list[dict]:
    """Ejecuta los escenarios sintéticos contra el CausalGate sobre claims
    extraídos de la evidencia. Devuelve resultados con esperado/real/veredicto."""
    from .pack import extract_claims
    from ..backends.base import EvidenceChunk
    gate = CausalGate()
    results = []
    for sc in synthetic_causal_scenarios():
        chunks = [EvidenceChunk(text=t, locator=f"synth_{sc.name}_{i}", score=1.0)
                  for i, t in enumerate(sc.evidence_texts)]
        claims = extract_claims(chunks)
        verdict = gate.check(sc.query, claims)
        actual = "ALLOW" if verdict.allowed else "ABSTAIN"
        results.append({
            "scenario": sc.name, "query": sc.query,
            "expected": sc.expect, "actual": actual,
            "pass": actual == sc.expect,
            "best_level": verdict.best_level,
            "ground_truth": sc.ground_truth,
            "reason": verdict.reason,
        })
    return results
