"""
LastRAG 2.0 Foundation — Anclaje claim ↔ evidencia (grado médico, capa 3)
=========================================================================
Port horizontal de la capa de evidencia soberana que ya operaba en los forks
(AESPLA-PRL `lastrag2.py` y FIMABIS `sovereign.py`): el upstream era la pieza
MÁS DÉBIL de la familia y cada producto la reimplementaba. Aquí vive una vez,
dominio-agnóstica, para que todo fork la herede (política de forks: las
mejoras horizontales suben al master).

Tres operaciones, todas verificables por contenido —nunca por afirmación del
modelo:

  1. CONGELACIÓN  — el conjunto EXACTO de evidencia que entra al generador se
     fija con sha256 por fragmento y un `evidence_hash` reproducible.
  2. ANCLAJE      — toda frase con un dato DURO (valor + unidad, porcentaje,
     dosis) debe tener ese dato presente en la evidencia congelada.
  3. CITAS        — una cita textual «…» que no conste LITERALMENTE en la
     evidencia es fabricación: se retira (o bloquea), jamás pasa como respaldo.

Qué NO hace (declarado): no juzga la veracidad clínica de una afirmación sin
datos duros, ni parafrasea semánticamente. Verifica anclaje literal, que es lo
que se puede comprobar sin un segundo modelo. Un texto sin datos duros ni
citas textuales pasa el anclaje por ausencia de material verificable, y eso se
refleja en el estado (`sin_claims_duros`), no en un PASS inventado.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from ..backends.base import EvidenceChunk

# ── Unidades y formas de dato DURO (verificables por contenido) ──────────
# Conservador por diseño: un número suelto no es un claim duro (un año, un
# número de página o un tamaño muestral citado de pasada generarían falsos
# bloqueos). Exigimos unidad, porcentaje o relación explícita.
_UNITS = (
    r"mg/dl|mg/kg|mg/m[²2]|ng/ml|pg/ml|mmol/l|mmol|meq/l|mmhg|cmh2o|ui/l|ui|iu|"
    r"mcg|µg|ug|mg|kg|g/dl|g/l|g|ml|dl|l|%|ºc|°c|bpm|rpm|kcal|"
    r"m/s[²2]|db\(a\)|db|ppm"
)
# El cierre NO puede ser `\b`: unidades como «%» son no-alfanuméricas y `\b`
# nunca casa tras ellas (bug silencioso que dejaba los porcentajes sin
# verificar). Lookahead negativo: la unidad no puede continuar en otra palabra.
_UNIT_END = r"(?![a-z0-9/])"
_HARD_PATTERNS = (
    # 500 mg · 7,5 mg/kg · 12 % · 140/90 mmHg
    re.compile(rf"\b\d+(?:[.,]\d+)?\s*(?:{_UNITS}){_UNIT_END}", re.I),
    re.compile(rf"\b\d+\s*/\s*\d+\s*(?:{_UNITS}){_UNIT_END}", re.I),
    # rangos: "entre 5 y 10 mg" se captura por el patrón anterior en cada extremo
)
# Aparatos de cita/paginación: procedencia, NO afirmación clínica.
_CITATION_NOISE = re.compile(
    r"\[\d+\]|\bp{1,2}\.?\s*\d+\b|\bpág(?:ina)?s?\.?\s*\d+\b|"
    r"\bp\.\s*\d+\b|\bsec(?:ción|cion)\.?\s*[\d.]+\b", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:!?])\s+|\n+")
_QUOTES = re.compile(r"«([^«»]+)»|“([^“”]+)”|\"([^\"]{12,})\"")
_MIN_SENTENCE = 12


def _norm(text: str) -> str:
    """Normalización comparable: sin acentos, minúsculas, decimales con punto,
    unidades pegadas separadas ('500mg' → '500 mg')."""
    txt = unicodedata.normalize("NFD", (text or "").lower())
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = txt.replace("²", "2").replace("³", "3")
    txt = re.sub(r"(\d),(\d)", r"\1.\2", txt)              # 7,5 → 7.5
    txt = re.sub(rf"(\d)\s*({_UNITS})(?![a-z0-9/])", r"\1 \2", txt)  # 500mg → 500 mg
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def _literal(text: str) -> str:
    """Normalización mínima para citas textuales: la literalidad es el punto,
    así que sólo se unifican espacios y formas Unicode."""
    return " ".join(unicodedata.normalize("NFKC", text or "").split())


def sha_of(text: str) -> str:
    return hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()


# ── 1 · Congelación ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class FrozenFragment:
    n: int
    locator: str
    document: str
    text: str
    sha256: str


@dataclass(frozen=True)
class EvidenceFreeze:
    """Conjunto EXACTO de evidencia que entró al generador."""
    hash: str
    fragments: tuple[FrozenFragment, ...] = ()

    @property
    def corpus_norm(self) -> str:
        return " ".join(_norm(f"{f.document} {f.text}") for f in self.fragments)

    @property
    def corpus_literal(self) -> tuple[str, ...]:
        return tuple(_literal(f.text) for f in self.fragments)

    def to_dict(self) -> dict:
        return {"hash": self.hash,
                "fragments": [{"n": f.n, "locator": f.locator,
                               "document": f.document, "sha256": f.sha256}
                              for f in self.fragments]}


def freeze_evidence(chunks: list[EvidenceChunk]) -> EvidenceFreeze:
    """Fija los fragmentos con procedencia verificable. El `hash` es
    reproducible: mismos fragmentos ⇒ mismo hash, en cualquier máquina."""
    fragments = []
    for i, c in enumerate(chunks, 1):
        document = c.citation.document if c.citation else (c.locator or "")
        fragments.append(FrozenFragment(
            n=i,
            locator=c.locator or "",
            document=document,
            text=c.text or "",
            sha256=sha_of(f"{document}|{c.text}")[:16],
        ))
    digest = hashlib.sha256(
        "|".join(f.sha256 for f in fragments).encode("utf-8")).hexdigest()[:16]
    return EvidenceFreeze(hash=digest, fragments=tuple(fragments))


# ── 2 · Anclaje de datos duros ───────────────────────────────────────────

def hard_tokens(sentence: str) -> set[str]:
    """Datos duros verificables de una frase (valor+unidad, porcentaje...).
    El aparato de cita (`[3]`, `p.42`) se descuenta: es procedencia."""
    limpio = _CITATION_NOISE.sub(" ", sentence)
    norm = _norm(limpio)
    tokens: set[str] = set()
    for pattern in _HARD_PATTERNS:
        for match in pattern.finditer(norm):
            tokens.add(" ".join(match.group(0).split()))
    return tokens


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "")
            if len(s.strip()) >= _MIN_SENTENCE]


@dataclass
class GroundingReport:
    claims: list[dict] = field(default_factory=list)
    fabricated_quotes: list[str] = field(default_factory=list)
    evidence_hash: str = ""

    @property
    def n_claims(self) -> int:
        return len(self.claims)

    @property
    def anchored(self) -> list[dict]:
        return [c for c in self.claims if c["anchored"]]

    @property
    def unanchored(self) -> list[dict]:
        return [c for c in self.claims if not c["anchored"]]

    @property
    def state(self) -> str:
        """Estado derivado de métricas CONTABLES (nunca un % inventado)."""
        if self.fabricated_quotes:
            return "fabricated_quotes"
        if not self.claims:
            return "sin_claims_duros"
        if not self.unanchored:
            return "anclada"
        if self.anchored:
            return "parcial"
        return "sin_anclaje"

    @property
    def grounded(self) -> bool:
        return not self.unanchored and not self.fabricated_quotes

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "evidence_hash": self.evidence_hash,
            "n_claims": self.n_claims,
            "n_anchored": len(self.anchored),
            "n_unanchored": len(self.unanchored),
            "fabricated_quotes": len(self.fabricated_quotes),
            # Se exponen los NO anclados: lo que falla es lo que hay que ver.
            "unanchored": [{"sentence": c["sentence"][:160],
                            "missing": c["missing"]} for c in self.unanchored][:6],
        }


def verify_grounding(answer: str, freeze: EvidenceFreeze) -> GroundingReport:
    """Comprueba, dato duro a dato duro, que la respuesta está anclada en la
    evidencia congelada. Verificación por CONTENIDO: el modelo no se audita a
    sí mismo."""
    corpus = freeze.corpus_norm
    report = GroundingReport(evidence_hash=freeze.hash)
    for sentence in split_sentences(answer):
        tokens = hard_tokens(sentence)
        if not tokens:
            continue
        missing = sorted(t for t in tokens
                         if not re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)",
                                          corpus))
        report.claims.append({
            "sentence": sentence,
            "tokens": sorted(tokens),
            "missing": missing,
            "anchored": not missing,
        })
    report.fabricated_quotes = find_fabricated_quotes(answer, freeze)
    return report


# ── 3 · Citas textuales fabricadas ───────────────────────────────────────

def find_fabricated_quotes(answer: str, freeze: EvidenceFreeze) -> list[str]:
    """Citas entrecomilladas que NO constan literalmente en la evidencia.
    Literal = texto exacto tras normalizar Unicode y espacios; jamás un
    solapamiento aproximado."""
    fragments = freeze.corpus_literal
    fabricadas = []
    for match in _QUOTES.finditer(answer or ""):
        quote = next((g for g in match.groups() if g), "")
        if not quote.strip():
            continue
        if not any(_literal(quote) in fragment for fragment in fragments):
            fabricadas.append(quote[:160])
    return fabricadas


def strip_fabricated_quotes(answer: str, freeze: EvidenceFreeze
                            ) -> tuple[str, list[str]]:
    """Retira las citas fabricadas dejando marca visible (modo `declare`)."""
    fragments = freeze.corpus_literal
    fabricadas: list[str] = []

    def _check(match: re.Match) -> str:
        quote = next((g for g in match.groups() if g), "")
        if not quote.strip():
            return match.group(0)
        if any(_literal(quote) in fragment for fragment in fragments):
            return match.group(0)
        fabricadas.append(quote[:160])
        return "「cita retirada: no consta en la evidencia congelada」"

    return _QUOTES.sub(_check, answer or ""), fabricadas
