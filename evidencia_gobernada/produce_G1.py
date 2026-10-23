#!/usr/bin/env python3
"""Productor del recibo G1 (fugas 0 con juez real) — NH-EG-LOOP-001.

Ejecuta run_verifier_benchmark con embedder real + juez real (endpoint
OpenAI-compatible, p. ej. ALIA en el Spark) y escribe el recibo con las
MÉTRICAS QUE DEVUELVE LA EJECUCIÓN — nada se teclea a mano ni se copia de
actas (regla del loop: el recibo lo produce la ejecución que mide).

Uso (Spark, con ALIA :8024 arriba):
  LASTRAG_LLM_ENDPOINT=http://127.0.0.1:8024/v1 \
  .venv/bin/python evidencia_gobernada/produce_G1.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.embedding import FastEmbedEmbedder  # noqa: E402
from core.llm.base import LocalLLM  # noqa: E402
from core.rag.verifier import ClaimVerifier, run_verifier_benchmark  # noqa: E402

OUT = ROOT / "evidencia_gobernada" / "receipts" / "G1_juez_real.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def main() -> int:
    endpoint = os.environ.get("LASTRAG_LLM_ENDPOINT")
    if not endpoint:
        print("ERROR: LASTRAG_LLM_ENDPOINT requerido (ventana ALIA)")
        return 2
    llm = LocalLLM(endpoint, model=os.environ.get("LOCAL_LLM_MODEL", "alia-nexthealth"),
                   max_retries=0, timeout=180.0)
    embedder = FastEmbedEmbedder()
    result = await run_verifier_benchmark(ClaimVerifier(embedder=embedder, judge=llm))
    # metadatos de trazabilidad de ESTA ejecución
    meta = await llm.model_metadata() if hasattr(llm, "model_metadata") else {}
    receipt = {
        "gate": "G1",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "by": f"zcode@{os.uname().nodename}",
        "inputs_sha256": {
            "verifier": sha(ROOT / "core" / "rag" / "verifier.py"),
            "producer": sha(Path(__file__)),
            "embedder_model_id": getattr(embedder, "model_id", "?"),
            "llm_endpoint": endpoint,
            "llm_model": meta.get("model") or os.environ.get("LOCAL_LLM_MODEL", "?"),
            "llm_max_model_len": meta.get("max_model_len"),
        },
        "metrics": {
            "fugas": result["fugas"],
            "falsos_bloqueos": result["falsos_bloqueos"],
            "n": result["n"],
            "exact": result["exact"],
            "methods": result["methods"],
        },
        "raw_cases": result["cases"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=1))
    print(f"recibo G1 escrito: {OUT}")
    print(f"  fugas={result['fugas']} falsos_bloqueos={result['falsos_bloqueos']} "
          f"exact={result['exact']}/{result['n']} methods={result['methods']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
