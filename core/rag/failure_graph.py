"""
LastRAG v2 — Ola 5: Failure Graph + Taxonomía de la Abstención
===============================================================
Compromisos s12 y s13 del deck:
  - Cada modo de fallo identificado y cada degradación con su COSTE MEDIDO.
  - Taxonomía fina del NO EVIDENCE: NO_EVIDENCE (no se recuperó nada) vs
    INSUFFICIENT_EVIDENCE (se recuperó algo pero no cubre la consulta) —
    la diferencia es detectable y viaja en la respuesta.

Modos: RETRIEVAL_MISS · CONFLICT_BLINDNESS · UNSUPPORTED_GENERATION ·
ABSTENTION_FAILURE (responder con confianza sin citas — con el scorer
honesto del motor NO debe dispararse nunca; existe un test negativo).
"""

from __future__ import annotations

import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

RETRIEVAL_MISS = "RETRIEVAL_MISS"
CONFLICT_BLINDNESS = "CONFLICT_BLINDNESS"
UNSUPPORTED_GENERATION = "UNSUPPORTED_GENERATION"
ABSTENTION_FAILURE = "ABSTENTION_FAILURE"
MODES = (RETRIEVAL_MISS, CONFLICT_BLINDNESS, UNSUPPORTED_GENERATION,
         ABSTENTION_FAILURE)


# ---------------- Taxonomía de la ausencia ----------------

NO_EVIDENCE = "NO_EVIDENCE"                # nada recuperado (detectable)
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"  # recuperado pero no cubre


def classify_absence(chunks_count: int, coverage: float | None,
                     claims_count: int = 0, discarded_by_grade: int = 0) -> dict:
    """Clasifica la ausencia de evidencia de forma DISTINGUIBLE:
    - NO_EVIDENCE: el sistema no recuperó nada (problema de recuperación).
    - INSUFFICIENT_EVIDENCE: hay material pero no cubre la consulta
      (problema de cobertura/dominio). La distinción importa porque el
      remedio es distinto: re-buscar vs admitir vacío documental.

    `discarded_by_grade` separa un tercer caso que antes se confundía con el
    primero: SÍ se recuperó material y fue el filtro de dominio quien lo
    descartó. El remedio no es re-buscar: es revisar dominio/consulta."""
    if chunks_count == 0 and discarded_by_grade:
        return {"type": INSUFFICIENT_EVIDENCE,
                "detail": f"0 fragmentos tras descarte del grade "
                          f"({discarded_by_grade} recuperados y descartados "
                          f"por irrelevancia de dominio)",
                "remedy": "revisar dominio de la consulta / corpus indexado; "
                          "NO es un fallo de recuperación"}
    if chunks_count == 0:
        return {"type": NO_EVIDENCE,
                "detail": "0 fragmentos recuperados",
                "remedy": "reintentar recuperación / corpus"}
    cov = coverage if coverage is not None else 0.0
    if claims_count == 0 or cov < 0.5:
        return {"type": INSUFFICIENT_EVIDENCE,
                "detail": f"{chunks_count} fragmentos, cobertura {cov:.0%}, "
                          f"{claims_count} claims",
                "remedy": "declarar vacío documental; no responder con "
                          "conocimiento general"}
    return {"type": None, "detail": "evidencia suficiente", "remedy": ""}


# ---------------- Failure Graph con coste medido ----------------

@dataclass
class FailureRecord:
    mode: str
    detail: str
    cost_ms: float


@dataclass
class FailureGraph:
    records: list[FailureRecord] = field(default_factory=list)

    def record(self, mode: str, detail: str = "", cost_ms: float = 0.0) -> None:
        if mode not in MODES:
            raise ValueError(f"modo de fallo desconocido: {mode}")
        self.records.append(FailureRecord(mode, detail, cost_ms))

    @contextmanager
    def measure(self, mode: str, detail: str = ""):
        """Mide el coste (ms) de una degradación mientras ocurre."""
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.record(mode, detail, (time.perf_counter() - t0) * 1000.0)

    def counts(self) -> dict[str, int]:
        out = {m: 0 for m in MODES}
        for r in self.records:
            out[r.mode] += 1
        return out

    def costs_ms(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for m in MODES:
            costs = [r.cost_ms for r in self.records if r.mode == m]
            if costs:
                out[m] = {"n": len(costs),
                          "p50_ms": round(statistics.median(costs), 2),
                          "max_ms": round(max(costs), 2)}
        return out

    def to_dict(self) -> dict:
        return {"counts": self.counts(), "costs": self.costs_ms(),
                "records": [vars(r) for r in self.records]}
