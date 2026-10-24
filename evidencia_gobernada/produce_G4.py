#!/usr/bin/env python3
"""Productor del recibo G4 (falsos bloqueos con anotador HUMANO) — NH-EG-LOOP-001.

Lee el resultado del arnés corregido (e21c1e4) y el paquete de anotación
humana; RECHAZA (exit 2, sin recibo) si:
  - alguna frase retirada tiene veredicto_humano vacío/null,
  - el anotador está vacío,
  - el paquete y el arnés no cuadran (frases retiradas ≠ frases anotadas),
  - algún veredicto no es exactamente RESPALDADA o NO_RESPALDADA.
El árbitro ALIA se copia como consultivo y JAMÁS como anotador.

Uso:
  .venv/bin/python evidencia_gobernada/produce_G4.py \
      [--harness bench/results/falsos_bloqueos_wave1_20261024.json] \
      [--package evidencia_gobernada/G4_ANOTACION_HUMANA_20261024.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HARNESS = ROOT / "bench/results/falsos_bloqueos_wave1_20261024.json"
DEFAULT_PACKAGE = ROOT / "evidencia_gobernada/G4_ANOTACION_HUMANA_20261024.json"
OUT = ROOT / "evidencia_gobernada/receipts/G4_falsos_bloqueos.json"

VALID = {"RESPALDADA", "NO_RESPALDADA"}


def die(reason: str) -> None:
    print(f"RECHAZADO — {reason}", flush=True)
    print("No se escribe recibo. Completa la anotación humana y reintenta.", flush=True)
    sys.exit(2)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", type=Path, default=DEFAULT_HARNESS)
    ap.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    args = ap.parse_args()

    harness = json.loads(args.harness.read_text())
    pkg = json.loads(args.package.read_text())

    # ── métricas del ARNÉS (la ejecución) ────────────────────────────────
    supported = sum((q.get("verdicts") or {}).get("SUPPORTED", 0)
                    for q in harness["per_query"]
                    if not q.get("error") and not q.get("abstained"))
    redacted_harness = [a for q in harness["per_query"]
                        if not q.get("error") and not q.get("abstained")
                        for a in q.get("adjudications", [])]

    # ── validación del paquete humano ────────────────────────────────────
    annotator = (pkg.get("metricas_para_el_recibo") or {}).get("annotator")
    if not annotator or not str(annotator).strip():
        die("anotador vacío: el gate exige un humano con nombre (ALIA no vale)")
    frases = pkg.get("frases") or []
    if len(frases) != len(redacted_harness):
        die(f"desalineado: el arnés retiró {len(redacted_harness)} frases y el "
            f"paquete tiene {len(frases)} (¿paquete obsoleto?)")
    for i, f in enumerate(frases, 1):
        v = f.get("veredicto_humano")
        if v is None or not str(v).strip():
            die(f"frase {i} sin veredicto_humano")
        if str(v).strip().upper() not in VALID:
            die(f"frase {i}: veredicto «{v}» inválido (solo {sorted(VALID)})")

    redacted_legitimate = sum(1 for f in frases
                              if str(f["veredicto_humano"]).strip().upper()
                              == "RESPALDADA")

    receipt = {
        "gate": "G4",
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "by": f"zcode@{__import__('os').uname().nodename}",
        "inputs_sha256": {
            "producer": sha(Path(__file__)),
            "harness": sha(args.harness),
            "annotation_package": sha(args.package),
        },
        "metrics": {
            "queries": harness.get("n_queries", 24),
            "supported_claims": supported,
            "redacted_claims": len(frases),
            "redacted_legitimate": redacted_legitimate,
            "annotator": str(annotator).strip(),
        },
        "annotator_human": str(annotator).strip(),
        "annotated_phrases": [
            {"claim": f["claim"][:200],
             "veredicto_humano": str(f["veredicto_humano"]).strip().upper(),
             "arbitro_ALIA_consultivo": f.get("arbitro_ALIA_consultivo")}
            for f in frases
        ],
        "nota": "redacted_legitimate = frases RESPALDADAS por el anotador "
                "humano (falsos bloqueos). El veredicto ALIA es consultivo y "
                "no computa.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=1))
    rate = redacted_legitimate / max(1, supported)
    print(f"recibo G4 escrito: {OUT}")
    print(f"  anotador={annotator} | supported={supported} | retiradas={len(frases)} "
          f"| RESPALDADAS={redacted_legitimate} | rate={rate:.1%} "
          f"(el loop evalua contra <= 20%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
