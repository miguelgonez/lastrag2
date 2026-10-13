"""
LastRAG v2 — Ola 2: Conflict Engine
====================================
Compromiso s8 del deck: la literatura médica es contradictoria; promediar
textos borra información crítica. Este motor agrupa claims comparables
(comparten entidad clínica y desenlace) y clasifica su relación:
  AGREEMENT · CONTRADICTION · METHODOLOGICAL_DIFFERENCE · UNRESOLVED
«Hay evidencia contradictoria que no puedo reconciliar» puede ser la
respuesta más honesta — nunca se promedia ni se oculta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .pack import Claim

_UP = ("aumenta", "eleva", "mayor", "superior", "mejora", "incrementa",
       "amplia", "refuerza")
_DOWN = ("disminuye", "reduce", "menor", "inferior", "empeora", "baja",
         "atenúa", "atenúa el", "disminuye el")
_OUTCOME_HINT = ("riesgo", "mortalidad", "supervivencia", "eficacia", "dosis",
                 "efecto", "respuesta", "presión", "hemoglobina", "dolor",
                 "progresión", "recurrencia")
_METHOD_TYPES = ("aleatorizado", "observacional", "cohorte", "casos",
                 "in vitro", "meta-análisis", "meta-analisis")


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[a-záéíóúüñ]{5,}", text.lower()))


def _direction(text: str) -> Optional[str]:
    low = text.lower()
    up = any(w in low for w in _UP)
    down = any(w in low for w in _DOWN)
    if up and not down:
        return "up"
    if down and not up:
        return "down"
    return None


def _methods(text: str) -> set[str]:
    low = text.lower()
    return {m for m in _METHOD_TYPES if m in low}


@dataclass
class ConflictGroup:
    entity: str
    claims: list[Claim] = field(default_factory=list)
    relation: str = "UNRESOLVED"
    reason: str = ""

    def to_dict(self) -> dict:
        return {"entity": self.entity, "relation": self.relation,
                "reason": self.reason,
                "claims": [c.statement for c in self.claims]}


class ConflictEngine:
    """Agrupa claims comparables y clasifica sus relaciones. Determinista:
    cada veredicto lleva su razón escrita."""

    def __init__(self, min_shared_terms: int = 2):
        self.min_shared_terms = min_shared_terms

    def _comparable(self, a: Claim, b: Claim) -> Optional[str]:
        shared = _terms(a.statement) & _terms(b.statement)
        if len(shared) < self.min_shared_terms:
            return None
        return sorted(shared)[0]

    def detect(self, claims: list[Claim]) -> list[dict]:
        groups: list[ConflictGroup] = []
        used: set[int] = set()
        for i, a in enumerate(claims):
            if i in used:
                continue
            group = ConflictGroup(entity="", claims=[a])
            for j in range(i + 1, len(claims)):
                if j in used:
                    continue
                b = claims[j]
                entity = self._comparable(a, b)
                if entity:
                    group.claims.append(b)
                    used.add(j)
                    if not group.entity:
                        group.entity = entity
            used.add(i)
            if len(group.claims) > 1:
                groups.append(self._classify(group))
        return [g.to_dict() for g in groups]

    def _classify(self, group: ConflictGroup) -> ConflictGroup:
        dirs = [_direction(c.statement) for c in group.claims]
        real_dirs = [d for d in dirs if d]
        distinct = set(real_dirs)
        methods = set().union(*(_methods(c.statement) for c in group.claims))
        if len(distinct) > 1:
            group.relation = "CONTRADICTION"
            group.reason = (f"direcciones opuestas sobre el desenlace "
                            f"({sorted(distinct)}) en claims comparables")
        elif len(distinct) == 1 and len(methods) > 1:
            group.relation = "METHODOLOGICAL_DIFFERENCE"
            group.reason = f"misma dirección, diseños distintos: {sorted(methods)}"
        elif len(distinct) == 1:
            group.relation = "AGREEMENT"
            group.reason = f"misma dirección ({real_dirs[0]}) en claims comparables"
        else:
            group.relation = "UNRESOLVED"
            group.reason = "claims comparables sin dirección medible; requiere revisión"
        return group

    @staticmethod
    def summarize(conflicts: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for c in conflicts:
            counts[c["relation"]] = counts.get(c["relation"], 0) + 1
        return {"conflict_groups": len(conflicts), "by_relation": counts,
                "silent_averaging": False}
