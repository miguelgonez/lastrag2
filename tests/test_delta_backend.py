"""
Test de humo del DeltaBackend (Fase 2). SKIP declarado si no hay Delta
accesible — NUNCA éxito falso:
  - sin DELTA_PATH → skip (motivo escrito)
  - sin pyspark en el entorno → skip (motivo escrito)
Ejecución real (host Spark, contenedor de la Fase 1):
  docker run --rm -e HOME=/tmp -e DELTA_PATH=/work/delta_out/delta_pubmed \
    -v $HOME/lastrag_pubmed_pilot:/work --entrypoint /opt/spark/bin/spark-submit \
    apache/spark:3.5.9-java17-python3 --packages io.delta:delta-spark_2.12:3.2.0 \
    --conf spark.jars.ivy=/tmp/.ivy2 --conf spark.ui.enabled=false \
    /work/scripts/run_delta_smoke_pyspark.py
(o pytest dentro de un entorno con pyspark+delta y DELTA_PATH apuntando al Delta)
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

pytestmark = pytest.mark.skipif(
    not os.getenv("DELTA_PATH"),
    reason="DELTA_PATH no definido — skip declarado (no éxito falso)")


def _pyspark_available() -> bool:
    try:
        import pyspark  # noqa: F401
        return True
    except Exception:
        return False


def test_delta_backend_search_smoke():
    if not _pyspark_available():
        pytest.skip("pyspark no instalado en este entorno — skip declarado "
                    "(el smoke REAL corre en el host/contenedor Spark)")
    from core.backends.delta_backend import DeltaBackend

    async def _run():
        b = DeltaBackend()
        await b.initialize()
        result = await b.search("SGLT2 diabetes", top_k=2)
        health = await b.health()
        await b.close()
        return result, health

    result, health = asyncio.run(_run())
    assert result.backend == "delta"
    assert len(result.chunks) <= 2
    assert result.degraded_reason is None
    if result.chunks:
        assert result.chunks[0].locator.startswith("pmid:")
        assert result.chunks[0].kind == "abstract"
        assert result.chunks[0].citation.document.startswith("PMID ")
    assert health["status"] == "ok"
    assert health["records"] == 1095  # el piloto completo servido desde Delta
