#!/usr/bin/env python3
"""Smoke REAL del DeltaBackend sin pytest (para el contenedor Spark).
Mismas aserciones que tests/test_delta_backend.py. Exit != 0 si falla."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.backends.delta_backend import DeltaBackend  # noqa: E402


async def main() -> int:
    b = DeltaBackend(os.environ.get("DELTA_PATH"))
    await b.initialize()
    result = await b.search("SGLT2 diabetes", top_k=2)
    health = await b.health()
    await b.close()

    assert result.backend == "delta", result.backend
    assert result.degraded_reason is None
    assert len(result.chunks) <= 2
    if result.chunks:
        assert result.chunks[0].locator.startswith("pmid:"), \
            result.chunks[0].locator
        assert result.chunks[0].kind == "abstract"
        assert result.chunks[0].citation.document.startswith("PMID ")
    assert health["status"] == "ok", health
    assert health["records"] == 1095, health  # el piloto completo servido
    print(f"[smoke-delta] ✅ backend={result.backend} · health={health}")
    for c in result.chunks:
        print(f"[smoke-delta]   {c.locator} · {c.text[:70]}…")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
