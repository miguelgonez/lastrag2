#!/usr/bin/env python3
"""Productor del recibo G3 (afirmabilidad) — NH-EG-LOOP-001, paquete C-G3.

Corre las 24 consultas congeladas de Wave 1 (bench/run_wave1.py) con el
source_meta CURADO cableado (SourceMetaStore), las 5 capas activas y juez
ALIA real. El recibo sale de las métricas que la ejecución devuelve.

Uso (Spark, ventana ALIA):
  NEO4J_URL=bolt://127.0.0.1:17687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=... \
  LASTRAG_LLM_ENDPOINT=http://127.0.0.1:8024/v1 \
  .venv/bin/python evidencia_gobernada/produce_G3.py \
      --parquet ~/lastrag_pubmed_pilot/cierre_brecha_real/data/pubmed_pilot.parquet \
      --source-meta cierre_brecha_real/data/curation/source_meta_20261023.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

from run_wave1 import FROZEN_QUERIES, build_corpus  # noqa: E402

from core.backends.qdrant_backend import QdrantBackend  # noqa: E402
from core.embedding import FastEmbedEmbedder, HashingEmbedder  # noqa: E402
from core.lastindex.navigator import LastIndex  # noqa: E402
from core.llm.base import LocalLLM  # noqa: E402
from core.rag.engine import LastRAGEngine  # noqa: E402
from core.rag.source_meta_store import SourceMetaStore  # noqa: E402
from core.rag.verifier import ClaimVerifier  # noqa: E402

OUT = ROOT / "evidencia_gobernada" / "receipts" / "G3_afirmabilidad.json"


def log(m):
    print(m, flush=True)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--source-meta", required=True, type=Path)
    ap.add_argument("--qdrant-path", default="bench/results/fb_qdrant")
    args = ap.parse_args()
    endpoint = os.environ.get("LASTRAG_LLM_ENDPOINT")
    if not endpoint:
        log("ERROR: LASTRAG_LLM_ENDPOINT requerido (ventana ALIA)")
        return 2

    store = SourceMetaStore.from_curation(args.source_meta)
    log(f"[G3] source_meta: {store.stamp['entries']} entradas "
        f"(sha {store.stamp['sha256'][:12]}…)")
    llm = LocalLLM(endpoint, model=os.environ.get("LOCAL_LLM_MODEL", "alia-nexthealth"),
                   max_retries=0, timeout=180.0)

    docs, _, rows = build_corpus(args.parquet)
    log(f"[G3] corpus: {len(docs)} abstracts de {len(rows)} filas")
    backend = QdrantBackend(path=args.qdrant_path, embedder=HashingEmbedder(),
                            vector_size=HashingEmbedder.dim,
                            embedding_model=HashingEmbedder.model_id)
    lastindex = LastIndex(os.getenv("NEO4J_URL", "bolt://127.0.0.1:7687"),
                          os.getenv("NEO4J_USERNAME", "neo4j"),
                          os.getenv("NEO4J_PASSWORD", "password"))
    await backend.initialize()
    await lastindex.setup_schema()
    for i, doc in enumerate(docs):
        await lastindex.ingest_tree(doc)
        await backend.ingest(doc.source_path, document_id=doc.document_id,
                             metadata={"blocks": [asdict(b) for b in doc.blocks]})
        if (i + 1) % 300 == 0:
            log(f"[G3] ingeridos {i + 1}/{len(docs)}")
    log("[G3] ingesta completa (idempotente)")

    engine = LastRAGEngine(
        backend, lastindex, llm,
        claim_verifier=ClaimVerifier(embedder=FastEmbedEmbedder(), judge=llm),
        verification="block", verification_judge=True,
        source_meta=store, source_policy="block")

    queries = [(t, q) for t, qs in FROZEN_QUERIES.items() for q in qs]
    per_query, answered, abstained, affirmable = [], 0, 0, 0
    t0 = time.time()
    for i, (topic, q) in enumerate(queries, 1):
        try:
            out = await engine.run(q)
            a, f = bool(out["abstained"]), bool(out["affirmable"])
        except Exception as e:
            log(f"  [{i}/24] {q[:40]}… ERROR {type(e).__name__}")
            per_query.append({"query": q, "topic": topic, "error": str(e)[:160]})
            continue
        answered += int(not a)
        abstained += int(a)
        affirmable += int(f)
        prov = (out.get("features") or {}).get("provenance") or {}
        per_query.append({"query": q, "topic": topic, "abstained": a,
                          "affirmable": f,
                          "provenance_state": prov.get("policy"),
                          "n_fragments": prov.get("n_fragments"),
                          "n_qualified": prov.get("qualified")})
        log(f"  [{i}/24] abst={a} affirm={f} "
            f"(q={prov.get('qualified')}/{prov.get('n_fragments')})")

    receipt = {
        "gate": "G3",
        "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "by": f"zcode@{os.uname().nodename}",
        "inputs_sha256": {
            "producer": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "source_meta": store.stamp["sha256"],
            "llm_model": os.environ.get("LOCAL_LLM_MODEL", "alia-nexthealth"),
            "embedder_model_id": "paraphrase-multilingual-minilm-onnx-v1",
        },
        "metrics": {
            "queries": len(queries), "answered": answered,
            "abstained": abstained, "affirmable": affirmable,
            "per_query": per_query, "duration_s": round(time.time() - t0, 1),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=1))
    log(f"\nrecibo G3: {OUT}")
    log(f"answered={answered} abstained={abstained} affirmable={affirmable} "
        f"({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
