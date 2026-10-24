#!/usr/bin/env python3
"""Productor del recibo G2 (curación ejecutada) — NH-EG-LOOP-001.

Lee los artefactos de la PROPIA ejecución del barrido
(curation/retractions_sweep.py: RETRACTIONS_RECEIPT_*.json + source_meta_*.json)
y escribe el recibo con métricas recalculadas desde ellos — nada se teclea.

Uso (MBP, donde vive el corpus):
  .venv/bin/python evidencia_gobernada/produce_G2.py [--data cierre_brecha_real/data/curation]
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cierre_brecha_real" / "data" / "curation"
OUT = ROOT / "evidencia_gobernada" / "receipts" / "G2_curacion.json"


def main() -> int:
    data = Path(sys.argv[sys.argv.index("--data") + 1]) if "--data" in sys.argv else DATA
    sweep = sorted(data.glob("RETRACTIONS_RECEIPT_*.json"))
    metas = sorted(data.glob("source_meta_*.json"))
    if not sweep or not metas:
        print(f"ERROR: sin artefactos de barrido en {data}")
        return 2
    r = json.loads(sweep[-1].read_text())          # la pasada más reciente
    source_meta = json.loads(metas[-1].read_text())
    checked = len(source_meta)
    corpus = r["n_unique_pmids"]
    unknown = sum(1 for v in source_meta.values() if v["retraction_status"] == "unknown")
    today = date.today().toordinal()
    ages = []
    for v in source_meta.values():
        try:
            ages.append(today - date.fromisoformat(v["retraction_checked_at"]).toordinal())
        except (KeyError, ValueError):
            pass
    max_age = max(ages) if ages else None
    receipt = {
        "gate": "G2",
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "by": "zcode@MBP",
        "inputs_sha256": {
            "sweep_receipt": hashlib.sha256(sweep[-1].read_bytes()).hexdigest(),
            "source_meta": hashlib.sha256(metas[-1].read_bytes()).hexdigest(),
            "sweep_script": hashlib.sha256(
                (ROOT / "curation" / "retractions_sweep.py").read_bytes()).hexdigest(),
            "corpus_manifest": hashlib.sha256(
                (ROOT / "cierre_brecha_real" / "data" / "MANIFEST_SCALE.json").read_bytes()
            ).hexdigest(),
        },
        "metrics": {
            "corpus_docs": corpus,
            "checked_docs": checked,
            "unknown": unknown,
            "retracted": r["final_counts"].get("retracted"),
            "concern": r["final_counts"].get("concern"),
            "max_check_age_days": max_age,
            # derivadas del source_meta (p. ej. "pubmed+rwdb" -> {pubmed, rwdb}), no tecleadas
            "sources": sorted({part for v in source_meta.values()
                               for part in str(v.get("retraction_source") or "").split("+") if part}),
            "source_meta_path": str(metas[-1]),
            "sweep_run_date": r.get("run_date"),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=1))
    print(f"recibo G2 escrito: {OUT}")
    print(f"  corpus={corpus} checked={checked} unknown={unknown} "
          f"retracted={receipt['metrics']['retracted']} max_age_d={max_age}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
