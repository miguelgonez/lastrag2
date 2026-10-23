"""Resolución de acreditación de sociedades científicas para GPC (curación).

Política (PI, 23-oct-2026): «sin lista, la acreditación es UNKNOWN y no
afirma». Este módulo implementa el lado curación de esa regla:

  - `resolve_accredited(publisher)` devuelve True SOLO si el editor coincide
    con una sociedad de `curation/accredited_societies.json` (entidades
    elaboradoras con GPC en el catálogo GuíaSalud del SNS, verificadas).
  - Si NO coincide devuelve None (UNKNOWN): la ausencia de la lista NI
    acredita NI desacredita. Ese es el estado que la capa 5
    (`core/rag/provenance.py`) marca como GUIDELINE_ACCREDITATION_UNKNOWN
    y NO afirma.
  - Jamás devuelve False por matching: desacreditar (p. ej. editor
    depredador) es juicio humano del curador, que estampa
    accredited=false a mano con su nota.

El matching es por alias normalizado (nombre completo o acrónimo no
ambiguo, ver "notes" del JSON) con fronteras de palabra sobre el nombre
del editor: «Sociedad Española de Diabetes (SED)» y «SED» casan igual.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

LIST_PATH = Path(__file__).with_name("accredited_societies.json")

# Longitud mínima de alias para matching por contenido (evita casuales cortos)
_MIN_CONTAINED_LEN = 4


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def load_societies(path: Path = LIST_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["societies"]


def _aliases(society: dict) -> list[str]:
    out = [_norm(society["name"])] + [_norm(a) for a in society.get("aliases", [])]
    return [a for a in out if a]


def resolve_accredited(publisher: Optional[str], *, path: Path = LIST_PATH) -> Optional[bool]:
    """True si el editor es una sociedad de la lista; None (UNKNOWN) si no."""
    if not publisher or not publisher.strip():
        return None
    target = _norm(publisher)
    if not target:
        return None
    for society in load_societies(path):
        for alias in _aliases(society):
            if alias == target:
                return True
            if len(alias) >= _MIN_CONTAINED_LEN and re.search(
                    r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", target):
                return True
    return None


def curation_hint(publisher: Optional[str], *, path: Path = LIST_PATH) -> dict:
    """Metadatos listos para `source_meta` de la capa 5 (tier GPC)."""
    return {
        "tier": "clinical_guideline",
        "publisher": publisher,
        "accredited": resolve_accredited(publisher, path=path),
    }
