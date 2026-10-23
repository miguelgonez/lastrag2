"""
LastRAG v2 — Ola 2: Evidence Pack 2.0 (la barrera epistemológica)
===================================================================
Compromiso s7 del deck: la unidad central deja de ser el chunk y pasa a ser
la relación claim ↔ evidence. El LLM no recibe una nube de fragmentos sino
un objeto estructurado con:
  - claims con spans VERIFICABLES (chunk.text[start:end] == span.text)
  - contradicciones etiquetadas (via ConflictEngine)
  - gaps declarados (subpreguntas sin cobertura)
  - provenance completa (locators + block_ids + citas)

Inmutable por construcción (dataclasses frozen); to_dict/render para el LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..backends.base import EvidenceChunk

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# Marcadores de aserción clínica (deterministas; un claim es una frase
# declarativa con sujeto y verbo de afirmación, no una pregunta ni un título)
_CLAIM_MARKERS = ("es ", "son ", "produce", "reduce", "aumenta", "disminuye",
                  "mejora", "empeora", "causa", "previene", "trata",
                  "recomienda", "asociado", "asociación", "asociacion",
                  "se asocia", "se observa", "prevalencia", "administra",
                  "dosis", "eficaz", "seguro", "efecto", "riesgo",
                  "mortalidad", "supervivencia")


@dataclass(frozen=True)
class ClaimSpan:
    chunk_locator: str
    block_id: Optional[str]
    start: int
    end: int
    text: str

    def verify(self, chunk_text: str) -> bool:
        return chunk_text[self.start:self.end] == self.text


@dataclass(frozen=True)
class Claim:
    statement: str
    spans: tuple[ClaimSpan, ...]
    sources: tuple[str, ...]        # "documento · sección · p.N"
    causal_level: Optional[str] = None  # lo etiqueta causal.py si se pide

    @property
    def n_sources(self) -> int:
        return len({s for sp in self.spans for s in self.sources})


@dataclass
class EvidencePack:
    query: str
    claims: list[Claim] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)   # conflict.py
    gaps: list[str] = field(default_factory=list)              # iterative.py
    provenance: list[dict] = field(default_factory=list)       # locator/block/cita

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "claims": [
                {"statement": c.statement,
                 "causal_level": c.causal_level,
                 "n_sources": c.n_sources,
                 "spans": [vars(s) for s in c.spans],
                 "sources": list(c.sources)}
                for c in self.claims
            ],
            "contradictions": self.contradictions,
            "gaps": self.gaps,
            "provenance": self.provenance,
        }

    def render_for_prompt(self) -> str:
        """El objeto estructurado que el LLM recibe EN LUGAR de la nube de
        chunks. Formato expediente: claim → evidencia exacta → fuente."""
        lines = [f"### Evidence Pack 2.0 — consulta: {self.query}"]
        if self.claims:
            lines.append("\n#### Afirmaciones con soporte (spans verificables)")
            for i, c in enumerate(self.claims, 1):
                lvl = f" [nivel causal: {c.causal_level}]" if c.causal_level else ""
                lines.append(f"C{i}{lvl}: {c.statement}")
                for sp in c.spans:
                    lines.append(f"   ↳ evidencia exacta: «{sp.text}» (bloque {sp.block_id or sp.chunk_locator})")
                for src in dict.fromkeys(c.sources):
                    lines.append(f"   ↳ fuente: {src}")
        else:
            lines.append("\n(sin afirmaciones extraíbles de la evidencia)")
        if self.contradictions:
            lines.append("\n#### Contradicciones declaradas (NO promediar)")
            for ct in self.contradictions:
                lines.append(f"⚠ {ct.get('relation')}: {ct.get('reason')}")
        if self.gaps:
            lines.append("\n#### Huecos de cobertura (no responder sobre esto)")
            for g in self.gaps:
                lines.append(f"• {g}")
        return "\n".join(lines)


def extract_claims(chunks: list[EvidenceChunk],
                   causal_levels: Optional[dict[str, str]] = None) -> list[Claim]:
    """Extracción determinista de claims: frases declarativas con marcador
    clínico, ancladas con span exacto al chunk que las contiene.
    `causal_levels` opcional: locator -> nivel (lo produce causal.classify)."""
    claims: list[Claim] = []
    for c in chunks:
        level = (causal_levels or {}).get(c.locator)
        for sentence in _SENTENCE_RE.split(c.text):
            s = sentence.strip()
            if len(s) < 25 or not any(m in s.lower() for m in _CLAIM_MARKERS):
                continue
            start = c.text.find(s)
            if start < 0:
                continue
            span = ClaimSpan(chunk_locator=c.locator,
                             block_id=c.citation.block_id if c.citation else None,
                             start=start, end=start + len(s), text=s)
            src = c.citation.short() if c.citation else f"locator:{c.locator}"
            claims.append(Claim(statement=s, spans=(span,), sources=(src,),
                                causal_level=level))
    return claims


def build_pack(query: str, chunks: list[EvidenceChunk],
               contradictions: Optional[list[dict]] = None,
               gaps: Optional[list[str]] = None,
               causal_levels: Optional[dict[str, str]] = None) -> EvidencePack:
    prov = [{
        "locator": c.locator,
        "block_id": c.citation.block_id if c.citation else None,
        "citation": c.citation.to_dict() if c.citation else None,
    } for c in chunks]
    return EvidencePack(query=query,
                        claims=extract_claims(chunks, causal_levels),
                        contradictions=contradictions or [],
                        gaps=gaps or [],
                        provenance=prov)
