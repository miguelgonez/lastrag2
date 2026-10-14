"""
LastRAG v2 — Ola 1: Router Iterativo (investigador que no se rinde)
====================================================================
Cubre el compromiso s5 del deck: descomposición de la consulta en
subpreguntas auditables, sufficiency gate (¿la evidencia recuperada cubre
cada subpregunta?), gap detector (qué falta) y reformulación acotada
(bucle con máximo de iteraciones, jamás infinito).

Diseño determinista y auditable: cada iteración queda registrada en
`iterations[]` (subpreguntas, cobertura, huecos, acción). Si al agotar el
máximo siguen existiendo huecos, se DECLARA (SUFFICIENCY_NOT_REACHED) —
nunca se responde como si la cobertura fuera completa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from ..backends.base import EvidenceChunk

# Separadores de cláusulas compuestas (deterministas, auditables)
_CLAUSE_SPLIT = re.compile(r"\s*(?:[;,]|\?| y también | además | y luego | y )\s*")
_MIN_CLAUSE_CHARS = 12


def decompose_query(query: str) -> list[str]:
    """Divide una consulta compleja en subpreguntas. Una consulta simple
    devuelve [query] sin bucle adicional."""
    raw = [c.strip(" ¿?") for c in _CLAUSE_SPLIT.split(query)]
    clauses = [c for c in raw if len(c) >= _MIN_CLAUSE_CHARS]
    if len(clauses) <= 1:
        return [query.strip()]
    return clauses


def _content_terms(text: str) -> set[str]:
    norm = text.lower()
    words = re.findall(r"[a-záéíóúüñ]{4,}", norm)
    stop = {"como", "cual", "cuales", "para", "porque", "cuando", "donde",
            "sobre", "entre", "desde", "hasta", "puede", "deben", "tiene"}
    return {w for w in words if w not in stop}


@dataclass
class SufficiencyReport:
    covered: dict[str, bool] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    coverage: float = 0.0

    @property
    def sufficient(self) -> bool:
        return self.coverage >= 1.0 and bool(self.covered)


class SufficiencyGate:
    """Cubre una subpregunta si algún fragmento comparte términos de contenido
    con ella (solapamiento léxico ≥ umbral). Determinista y explicable."""

    def __init__(self, min_overlap: float = 0.34):
        self.min_overlap = min_overlap

    def evaluate(self, subqueries: list[str], chunks: list[EvidenceChunk]) -> SufficiencyReport:
        report = SufficiencyReport()
        if not subqueries:
            return report
        chunk_terms = [_content_terms(c.text) for c in chunks]
        for sq in subqueries:
            sq_terms = _content_terms(sq)
            best = 0.0
            for terms in chunk_terms:
                if sq_terms and terms:
                    overlap = len(sq_terms & terms) / len(sq_terms)
                    best = max(best, overlap)
            ok = best >= self.min_overlap
            report.covered[sq] = ok
            if not ok:
                report.gaps.append(sq)
        report.coverage = sum(report.covered.values()) / len(subqueries)
        return report


def reformulate(subquery: str, chunks: list[EvidenceChunk]) -> str:
    """Reformula una subpregunta con hueco: añade los términos de contenido
    más frecuentes de la evidencia recuperada (vocabulario del dominio).
    Determinista: top-3 términos por frecuencia."""
    freq: dict[str, int] = {}
    for c in chunks:
        for t in _content_terms(c.text):
            freq[t] = freq.get(t, 0) + 1
    top = [t for t, _ in sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:3]]
    return " ".join([subquery, *top])


@dataclass
class IterationLog:
    iteration: int
    subqueries: list[str]
    coverage: float
    gaps: list[str]
    action: str  # "retrieve" | "reformulate_and_retrieve" | "done" | "max_reached"


class IterativeRouter:
    """Bucle investigador: descompone → recupera → mide suficiencia →
    reformula los huecos → recupera de nuevo. Acotado por max_iterations."""

    def __init__(self, gate: Optional[SufficiencyGate] = None, max_iterations: int = 3):
        self.gate = gate or SufficiencyGate()
        self.max_iterations = max_iterations

    async def run(
        self,
        query: str,
        retrieve: Callable[[str, int], Awaitable[list[EvidenceChunk]]],
        top_k: int = 5,
    ) -> tuple[list[EvidenceChunk], list[dict], Optional[dict]]:
        """`retrieve(query, top_k)` debe devolver fragmentos (cualquier vía).
        Devuelve (chunks, iterations_log, degradation_o_None)."""
        subqueries = decompose_query(query)
        all_chunks: dict[str, EvidenceChunk] = {}
        iterations: list[IterationLog] = []
        degradation = None

        pending = list(subqueries)
        for it in range(1, self.max_iterations + 1):
            for sq in pending:
                found = await retrieve(sq, top_k)
                for c in found:
                    key = c.locator or c.text[:40]
                    if key not in all_chunks:
                        all_chunks[key] = c
            report = self.gate.evaluate(subqueries, list(all_chunks.values()))
            if report.sufficient:
                iterations.append(IterationLog(it, subqueries, report.coverage,
                                                [], "done"))
                break
            if it == self.max_iterations:
                iterations.append(IterationLog(it, subqueries, report.coverage,
                                                report.gaps, "max_reached"))
                degradation = {
                    "component": "iterative_router",
                    "reason": "SUFFICIENCY_NOT_REACHED",
                    "effect": "partial_coverage",
                    "gaps": report.gaps,
                    "iterations": it,
                }
            else:
                iterations.append(IterationLog(it, subqueries, report.coverage,
                                                report.gaps,
                                                "reformulate_and_retrieve"))
                pending = [reformulate(g, list(all_chunks.values()))
                           for g in report.gaps]

        return (list(all_chunks.values()),
                [vars(log) for log in iterations],
                degradation)
