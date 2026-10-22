"""
LastRAG 2.0 Foundation — Cualificación de la fuente (grado médico, capa 5)
==========================================================================
Regla del PI (22-oct-2026, literal): «esto sí se puede afirmar si se remite a
una evidencia trazable respaldada por un centro de evidencia científica, un
paper validado por pares y que a la fecha no haya sido refutado, o guías de
práctica clínica por asociación científica acreditada o respetable
científicamente».

Las capas 1-4 garantizan que cada frase está RESPALDADA por la evidencia
recuperada. Esta capa decide si ese respaldo AUTORIZA UNA AFIRMACIÓN de grado
médico: depende de QUÉ fuente es, no de lo que dice. El motor no juzga la
verdad clínica; juzga la procedencia, que sí es verificable por contrato.

Una fuente CUALIFICA cuando se cumplen las tres condiciones:
  1. Nivel cualificado: `peer_reviewed` · `clinical_guideline` (de asociación
     científica acreditada) · `evidence_center` (Cochrane, NICE, GRADE-based).
  2. No refutada a fecha: `retraction_status == "none"`.
  3. Comprobación trazable: `retraction_checked_at` presente y no caducada
     (`max_check_age_days`, 180 por defecto). «A la fecha» exige una fecha.

Todo lo demás NO cualifica y se declara con su razón: nivel no cualificado
(preprint, literatura gris, documento interno, web), refutada/retractada,
expresión de preocupación, comprobación ausente o caducada, o procedencia
desconocida (sin metadatos). `UNKNOWN != PASS`: una fuente sin metadatos no
es «probablemente buena»; es no afirmable hasta que alguien la cualifique.

Qué NO hace: no consulta registros externos (Retraction Watch, PubMed) — eso
es un proceso de curación del corpus que deja su rastro en los metadatos que
esta capa lee. Y no sustituye la jerarquía clínica de la evidencia (GRADE,
PICO), que por canon pertenece a la solución clínica, no al motor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from ..backends.base import EvidenceChunk

# Niveles de fuente
PEER_REVIEWED = "peer_reviewed"          # paper revisado por pares
CLINICAL_GUIDELINE = "clinical_guideline"  # GPC de asociación científica acreditada
EVIDENCE_CENTER = "evidence_center"      # Cochrane, NICE, centros GRADE
PREPRINT = "preprint"
GREY_LITERATURE = "grey_literature"
INTERNAL = "internal"                    # protocolo interno, documento propio
WEB = "web"
UNKNOWN_TIER = "unknown"

QUALIFIED_TIERS = frozenset({PEER_REVIEWED, CLINICAL_GUIDELINE, EVIDENCE_CENTER})
KNOWN_TIERS = QUALIFIED_TIERS | {PREPRINT, GREY_LITERATURE, INTERNAL, WEB}

# Estado de refutación
RETRACTION_NONE = "none"
RETRACTED = "retracted"
CONCERN = "concern"                      # expression of concern / refutada parcialmente
RETRACTION_UNKNOWN = "unknown"

DEFAULT_MAX_CHECK_AGE_DAYS = 180


@dataclass(frozen=True)
class SourceProvenance:
    """Metadatos de procedencia de una fuente (por documento o por locator)."""
    tier: str = UNKNOWN_TIER
    publisher: Optional[str] = None          # editorial, sociedad, centro
    accredited: Optional[bool] = None        # GPC: ¿asociación acreditada?
    retraction_status: str = RETRACTION_UNKNOWN
    retraction_checked_at: Optional[str] = None   # ISO date de la comprobación
    identifier: Optional[str] = None         # DOI / PMID / URL oficial
    note: Optional[str] = None

    @classmethod
    def from_dict(cls, meta: Optional[dict]) -> "SourceProvenance":
        meta = meta or {}
        return cls(
            tier=str(meta.get("tier") or UNKNOWN_TIER),
            publisher=meta.get("publisher"),
            accredited=meta.get("accredited"),
            retraction_status=str(meta.get("retraction_status") or RETRACTION_UNKNOWN),
            retraction_checked_at=meta.get("retraction_checked_at"),
            identifier=meta.get("identifier") or meta.get("doi") or meta.get("pmid"),
            note=meta.get("note"),
        )


@dataclass(frozen=True)
class Qualification:
    qualified: bool
    tier: str
    reason: str
    blocking: bool = False      # refutada/retractada: contamina la respuesta
    retraction_status: str = RETRACTION_UNKNOWN
    checked_at: Optional[str] = None
    check_age_days: Optional[int] = None

    def to_dict(self) -> dict:
        return {"qualified": self.qualified, "tier": self.tier, "reason": self.reason,
                "blocking": self.blocking, "retraction_status": self.retraction_status,
                "checked_at": self.checked_at, "check_age_days": self.check_age_days}


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def qualify(prov: SourceProvenance, *, today: Optional[date] = None,
            max_check_age_days: int = DEFAULT_MAX_CHECK_AGE_DAYS) -> Qualification:
    """Aplica la regla del PI a una fuente. Cada razón es contable y escrita."""
    today = today or date.today()
    tier = prov.tier if prov.tier in KNOWN_TIERS else UNKNOWN_TIER

    # Refutación: manda sobre todo lo demás.
    if prov.retraction_status == RETRACTED:
        return Qualification(False, tier, "RETRACTED: fuente retractada/refutada",
                             blocking=True, retraction_status=RETRACTED,
                             checked_at=prov.retraction_checked_at)
    if prov.retraction_status == CONCERN:
        return Qualification(False, tier, "CONCERN: expresión de preocupación o refutación parcial",
                             blocking=True, retraction_status=CONCERN,
                             checked_at=prov.retraction_checked_at)

    if tier == UNKNOWN_TIER:
        return Qualification(False, tier, "UNKNOWN_TIER: procedencia sin metadatos",
                             retraction_status=prov.retraction_status)
    if tier not in QUALIFIED_TIERS:
        return Qualification(False, tier, f"UNQUALIFIED_TIER:{tier}",
                             retraction_status=prov.retraction_status)
    if tier == CLINICAL_GUIDELINE and prov.accredited is False:
        return Qualification(False, tier, "GUIDELINE_NOT_ACCREDITED: asociación no acreditada",
                             retraction_status=prov.retraction_status)
    if tier == CLINICAL_GUIDELINE and prov.accredited is None:
        return Qualification(False, tier, "GUIDELINE_ACCREDITATION_UNKNOWN",
                             retraction_status=prov.retraction_status)

    # «A la fecha no refutado» exige comprobación con fecha y vigente.
    if prov.retraction_status != RETRACTION_NONE:
        return Qualification(False, tier, "RETRACTION_UNCHECKED: sin comprobación de refutación",
                             retraction_status=prov.retraction_status,
                             checked_at=prov.retraction_checked_at)
    checked = _parse_date(prov.retraction_checked_at)
    if checked is None:
        return Qualification(False, tier, "RETRACTION_CHECK_UNDATED: comprobación sin fecha",
                             retraction_status=RETRACTION_NONE)
    age = (today - checked).days
    if age < 0:
        return Qualification(False, tier, "RETRACTION_CHECK_IN_FUTURE: fecha inválida",
                             retraction_status=RETRACTION_NONE,
                             checked_at=prov.retraction_checked_at, check_age_days=age)
    if age > max_check_age_days:
        return Qualification(False, tier,
                             f"RETRACTION_CHECK_STALE: {age} días > {max_check_age_days}",
                             retraction_status=RETRACTION_NONE,
                             checked_at=prov.retraction_checked_at, check_age_days=age)
    return Qualification(True, tier, f"QUALIFIED:{tier}", retraction_status=RETRACTION_NONE,
                         checked_at=prov.retraction_checked_at, check_age_days=age)


# ── Resolución por fragmento ─────────────────────────────────────────────

def lookup(source_meta: Optional[dict], chunk: EvidenceChunk) -> SourceProvenance:
    """Metadatos de la fuente de un fragmento: por locator, por block_id o por
    documento (en ese orden). Sin entrada => procedencia desconocida."""
    meta = source_meta or {}
    keys = [chunk.locator]
    if chunk.citation:
        keys += [chunk.citation.block_id, chunk.citation.document]
    for key in keys:
        if key and key in meta:
            return SourceProvenance.from_dict(meta[key])
    return SourceProvenance()


@dataclass
class ProvenanceAssessment:
    per_fragment: dict[str, Qualification] = field(default_factory=dict)  # locator -> Q
    policy: str = "block"

    @property
    def blocking(self) -> list[str]:
        return [loc for loc, q in self.per_fragment.items() if q.blocking]

    @property
    def qualified(self) -> list[str]:
        return [loc for loc, q in self.per_fragment.items() if q.qualified]

    @property
    def unqualified_known(self) -> list[str]:
        return [loc for loc, q in self.per_fragment.items()
                if not q.qualified and not q.blocking and q.tier != UNKNOWN_TIER]

    @property
    def unknown(self) -> list[str]:
        return [loc for loc, q in self.per_fragment.items()
                if not q.qualified and not q.blocking and q.tier == UNKNOWN_TIER]

    @property
    def affirmable(self) -> bool:
        """Toda la evidencia que sostiene la respuesta cualifica."""
        return bool(self.per_fragment) and all(q.qualified for q in self.per_fragment.values())

    def to_dict(self) -> dict:
        return {
            "policy": self.policy,
            "affirmable": self.affirmable,
            "n_fragments": len(self.per_fragment),
            "qualified": len(self.qualified),
            "unqualified_known": len(self.unqualified_known),
            "unknown": len(self.unknown),
            "blocking": len(self.blocking),
            "fragments": {loc: q.to_dict() for loc, q in self.per_fragment.items()},
        }


def assess(chunks: list[EvidenceChunk], source_meta: Optional[dict], *,
           today: Optional[date] = None,
           max_check_age_days: int = DEFAULT_MAX_CHECK_AGE_DAYS,
           policy: str = "block") -> ProvenanceAssessment:
    out = ProvenanceAssessment(policy=policy)
    for c in chunks:
        key = c.locator or (c.citation.document if c.citation else "") or c.text[:40]
        out.per_fragment[key] = qualify(lookup(source_meta, c), today=today,
                                        max_check_age_days=max_check_age_days)
    return out


NOT_AFFIRMABLE_FOOTER = (
    "\n\nℹ️ **Procedencia**: parte de la evidencia que sostiene esta respuesta no "
    "procede de una fuente cualificada a fecha de hoy (paper revisado por pares no "
    "refutado, guía de práctica clínica de asociación acreditada o centro de "
    "evidencia). Se entrega como información respaldada por los documentos "
    "indexados, **no como afirmación de grado médico**."
)
