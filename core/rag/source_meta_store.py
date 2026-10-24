"""SourceMetaStore — el puente curación → engine (C-G3, NH-EG-LOOP-001).

Carga un `source_meta_YYYYMMDD.json` producido por la curación
(`curation/retractions_sweep.py`: 48.399 entradas indexadas por PMID) y lo
expone como `Mapping` con TODAS las formas de clave PMID
(`pubmed_<pmid>` ≡ `pmid:<pmid>` ≡ `<pmid>`), de modo que el `source_meta`
del engine (que busca por locator/block_id/document/document_id) case sin
cambiar la firma del motor. El engine acepta cualquier Mapping: esta clase
es transparente para él.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Dict

from .provenance import _pmid_forms


class SourceMetaStore(Mapping):
    """Mapping inmutable de claves de fuente → metadatos de procedencia."""

    def __init__(self, data: Dict[str, dict], stamp: dict | None = None):
        # Expande TODAS las formas de clave PMID (pubmed_X ≡ pmid:X ≡ X):
        # vale para un fichero de curación (por PMID) o para un dict crudo.
        expanded: Dict[str, dict] = {}
        for key, value in data.items():
            for form in _pmid_forms(key):
                expanded.setdefault(form, value)
        self._data = expanded
        self.stamp = stamp or {}
        self.stamp.setdefault("entries", len(data))

    @classmethod
    def from_curation(cls, path: str | Path) -> "SourceMetaStore":
        p = Path(path)
        raw = json.loads(p.read_text())
        stamp = {
            "path": str(p),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "entries": len(raw),
        }
        return cls(raw, stamp)

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self) -> str:  # pragma: no cover
        return (f"SourceMetaStore(entries={self.stamp.get('entries')}, "
                f"keys={len(self._data)}, sha256={self.stamp.get('sha256', '')[:12]}…)")
