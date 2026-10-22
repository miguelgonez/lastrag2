"""
LastRAG v2 — Ola 2: Temporal RAG
=================================
Compromiso s8 del deck: una guía excelente de 2018 puede estar obsoleta.
Ventanas de validez por documento (valid_from / valid_until / superseded_by /
guideline_version) + filtro a tiempo de consulta:
  - query vigente (default) → sólo la versión vigente; los superseded NO se
    sirven como actuales (y el descarte queda DECLARADO).
  - query histórica («en 2018», «antes de», «histórico») → la versión válida
    en esa ventana temporal.
  - documento sin fecha → UNDATED declarado; JAMÁS se inventa la fecha.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..backends.base import EvidenceChunk

_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")
_HISTORICAL_MARKERS = ("histórico", "historico", "antes de", "versión anterior",
                       "version anterior", "anteriormente", "deprecated")


@dataclass
class TemporalMeta:
    locator: str
    valid_from: Optional[int] = None      # año de entrada en vigor
    valid_until: Optional[int] = None     # año de fin (None = vigente)
    superseded_by: Optional[str] = None   # locator de la versión que la sustituye
    guideline_version: Optional[str] = None
    published_at: Optional[int] = None


def parse_temporal_meta(locator: str, meta: dict) -> TemporalMeta:
    return TemporalMeta(
        locator=locator,
        valid_from=meta.get("valid_from"),
        valid_until=meta.get("valid_until"),
        superseded_by=meta.get("superseded_by"),
        guideline_version=meta.get("guideline_version"),
        published_at=meta.get("published_at"),
    )


def wants_historical(query: str, now_year: Optional[int] = None) -> bool:
    """Una consulta es historica si lo dice (marcadores) o si el ultimo año
    que menciona es ANTERIOR al año en curso. El umbral se calculaba contra
    un 2024 fijo: en 2026 una pregunta «en 2025» se trataba como vigente."""
    now_year = now_year if now_year is not None else date.today().year
    low = query.lower()
    if any(m in low for m in _HISTORICAL_MARKERS):
        return True
    years = [int(y) for y in _YEAR_RE.findall(query)]
    return bool(years) and max(years) < now_year


def extract_year(query: str) -> Optional[int]:
    years = [int(y) for y in _YEAR_RE.findall(query)]
    return max(years) if years else None


@dataclass
class TemporalDecision:
    kept: list[EvidenceChunk]
    dropped: list[dict]     # {locator, reason} — JAMÁS silencioso
    mode: str               # "current" | "historical:YYYY"
    undated_kept: int


def temporal_filter(chunks: list[EvidenceChunk],
                    meta_by_locator: dict[str, dict],
                    query: str,
                    now_year: Optional[int] = None) -> TemporalDecision:
    # El "ahora" se lee del reloj, no de una constante: con 2026 fijo, en 2027
    # una guia caducada en 2026 se habria seguido sirviendo como vigente.
    now_year = now_year if now_year is not None else date.today().year
    historical = wants_historical(query, now_year)
    at_year = extract_year(query) if historical else now_year
    kept, dropped, undated = [], [], 0
    for c in chunks:
        meta = meta_by_locator.get(c.locator)
        has_dates = meta is not None and any(
            meta.get(k) is not None for k in
            ("valid_from", "valid_until", "superseded_by", "guideline_version",
             "published_at"))
        if not has_dates:
            undated += 1
            kept.append(c)          # UNDATED se conserva y se declara
            continue
        m = parse_temporal_meta(c.locator, meta)
        if historical:
            # ventana histórica: sirve lo vigente EN ese año
            vf, vu = m.valid_from, m.valid_until
            in_window = (vf is None or vf <= at_year) and \
                        (vu is None or vu >= at_year)
            if in_window:
                kept.append(c)
            else:
                dropped.append({"locator": c.locator,
                                "reason": f"fuera_de_ventana_{at_year}"
                                          f"(valid_from={vf},valid_until={vu})"})
        else:
            if m.superseded_by:
                dropped.append({"locator": c.locator,
                                "reason": f"SUPERSEDED_BY:{m.superseded_by}"})
            elif m.valid_until is not None and m.valid_until < now_year:
                dropped.append({"locator": c.locator,
                                "reason": f"EXPIRED:{m.valid_until}"})
            else:
                kept.append(c)
    mode = f"historical:{at_year}" if historical else "current"
    return TemporalDecision(kept=kept, dropped=dropped, mode=mode,
                            undated_kept=undated)
