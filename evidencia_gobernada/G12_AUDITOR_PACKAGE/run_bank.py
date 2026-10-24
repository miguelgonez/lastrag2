#!/usr/bin/env python3
"""Banco del verificador para el auditor (G12) — ejecución autónoma del
banco sintético de 14 casos. Idéntico a run_verifier_benchmark(ClaimVerifier())
pero con salida explícita por caso para revisión manual del tercero."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.rag.verifier import ClaimVerifier, run_verifier_benchmark  # noqa: E402


async def main() -> int:
    result = await run_verifier_benchmark(ClaimVerifier())
    print(f"{'caso':24} {'esperado':12} {'obtenido':12} "
          f"{'fuga':5} {'bloq.':6} método")
    for c in result["cases"]:
        print(f"{c['case']:24} {c['expected']:12} {c['actual']:12} "
              f"{'SÍ' if c['leak'] else '—':5} "
              f"{'SÍ' if c['false_block'] else '—':6} {c.get('method', '')}")
    print(f"\nn={result['n']} · exact={result['exact']} · "
          f"FUGAS={result['fugas']} · falsos_bloqueos={result['falsos_bloqueos']}")
    print("Criterio G1: FUGAS debe ser 0. Los falsos bloqueos se declaran.")
    return 0 if result["fugas"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
