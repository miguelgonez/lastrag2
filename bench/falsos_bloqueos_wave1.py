#!/usr/bin/env python3
"""
Puerta (a) — tasa de falsos bloqueos de la capa 4 sobre las 24 consultas
congeladas de Wave 1, con generación y juez ALIA reales.

PREREGISTRO sellado en bench/PREREG_FALSOS_BLOQUEOS_WAVE1.md (23-oct-2026):
GATE <= 20% de falsos_bloqueos/retiradas_adjudicables, umbral fijado ANTES
de medir. Ejecutar en el Spark (Neo4j T3 + parquet del piloto + ALIA :8024).

Uso:
  NEO4J_URL=bolt://127.0.0.1:17687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=... \
  LASTRAG_LLM_ENDPOINT=http://127.0.0.1:8024/v1 \
  .venv/bin/python bench/falsos_bloqueos_wave1.py \
      --parquet ~/lastrag_pubmed_pilot/cierre_brecha_real/data/pubmed_pilot.parquet \
      --out bench/results/falsos_bloqueos_wave1.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
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
from core.rag.verifier import ClaimVerifier  # noqa: E402

GATE = 0.20
ADJ_PROMPT = ("Afirmación: {claim}\n\nEvidencia:\n{evidence}\n\n"
              "¿La afirmación está respaldada por la evidencia? "
              "Responde solo una letra.\nA — Sí, respaldada\nB — No respaldada\n"
              "C — No se puede decidir\n")


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_letter(text: str) -> str:
    m = re.search(r"\b([ABC])\b", (text or "").strip().upper()[:80])
    return m.group(1) if m else "UNPARSEABLE"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--qdrant-path", default="bench/results/fb_qdrant")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    llm_url = os.environ.get("LASTRAG_LLM_ENDPOINT")
    if not llm_url:
        log("ERROR: LASTRAG_LLM_ENDPOINT requerido (ventana ALIA)")
        return 2
    llm = LocalLLM(llm_url, model=os.environ.get("LOCAL_LLM_MODEL", "alia-nexthealth"),
                   max_retries=0, timeout=180.0)

    docs, _, rows = build_corpus(args.parquet)
    log(f"[fb] corpus: {len(docs)} abstracts de {len(rows)} filas")
    backend = QdrantBackend(path=args.qdrant_path, embedder=HashingEmbedder(),
                            vector_size=HashingEmbedder.dim,
                            embedding_model=HashingEmbedder.model_id)
    lastindex = LastIndex(os.getenv("NEO4J_URL", "bolt://127.0.0.1:7687"),
                          os.getenv("NEO4J_USERNAME", "neo4j"),
                          os.getenv("NEO4J_PASSWORD", "password"))
    from dataclasses import asdict as _asdict
    log("[fb] ingesta idempotente (Qdrant + arbol T3)…")
    await backend.initialize()
    await lastindex.setup_schema()
    for i, doc in enumerate(docs):
        await lastindex.ingest_tree(doc)
        await backend.ingest(doc.source_path, document_id=doc.document_id,
                             metadata={"blocks": [_asdict(b) for b in doc.blocks]})
        if (i + 1) % 300 == 0:
            log(f"[fb] ingeridos {i + 1}/{len(docs)}")
    log(f"[fb] ingesta completa: {len(docs)} docs")

    try:
        verifier = ClaimVerifier(embedder=FastEmbedEmbedder(), judge=llm)
        engine = LastRAGEngine(backend, lastindex, llm,
                               claim_verifier=verifier,
                               verification="declare", verification_judge=True)
        queries = [(t, q) for t, qs in FROZEN_QUERIES.items() for q in qs]
        per_query, all_verdicts, adjudications = [], [], {"A": 0, "B": 0, "C": 0,
                                                          "UNPARSEABLE": 0}
        t0 = time.time()
        for i, (topic, q) in enumerate(queries, 1):
            try:
                out = await engine.run(q)
            except Exception as e:  # la consulta falla, la medición sigue
                log(f"  [{i}/24] {q[:40]}… ERROR {type(e).__name__}: {e}")
                per_query.append({"topic": topic, "query": q, "error": str(e)[:200]})
                continue
            feats = out.get("features") or {}
            verif = feats.get("verification") or {}
            evidence_text = "\n\n".join(
                f"[{n}] {e.get('text', e.get('chunk', ''))[:1200]}"
                for n, e in enumerate(out.get("evidence") or [], 1)) or "(sin evidencia)"
            claims = verif.get("claims") or []
            entry = {"topic": topic, "query": q, "abstained": out.get("abstained"),
                     "affirmable": out.get("affirmable"),
                     "n_claims": len(claims), "verdicts": {}, "adjudications": []}
            for c in claims:
                v = c.get("verdict", "?")
                entry["verdicts"][v] = entry["verdicts"].get(v, 0) + 1
                all_verdicts.append(v)
                if v == "UNSUPPORTED" and not out.get("abstained"):
                    prompt = ADJ_PROMPT.format(claim=c.get("sentence", ""), evidence=evidence_text)
                    try:
                        raw = await llm.generate(prompt, max_tokens=8)
                        letter = parse_letter(raw)
                    except Exception as e:
                        letter = f"ERROR:{type(e).__name__}"
                    adjudications[letter] = adjudications.get(letter, 0) + 1
                    entry["adjudications"].append({"claim": (c.get("sentence") or "")[:160],
                                                   "method": c.get("method"),
                                                   "arbiter": letter})
            log(f"  [{i}/24] {q[:44]}… claims={len(claims)} "
                f"{entry['verdicts']} abst={out.get('abstained')}")
            per_query.append(entry)

        n_retired_adj = adjudications["A"] + adjudications["B"]
        rate = adjudications["A"] / n_retired_adj if n_retired_adj else None
        counted = [v for v in all_verdicts if v in
                   ("SUPPORTED", "UNSUPPORTED", "CONTRADICTED")]
        result = {
            "run_date": "2026-10-23", "prereg": "bench/PREREG_FALSOS_BLOQUEOS_WAVE1.md",
            "gate": GATE, "judge": "alia-nexthealth :8024 (ventana 4096)",
            "verdict_counts": {v: all_verdicts.count(v) for v in set(all_verdicts)},
            "adjudications": adjudications,
            "tasa_falsos_bloqueos_adjudicables": round(rate, 4) if rate is not None else None,
            "retiradas_sobre_total_claims": (round(
                all_verdicts.count("UNSUPPORTED") / len(counted), 4) if counted else None),
            "gate_result": (("PASS" if rate is not None and rate <= GATE else "FAIL")
                            if n_retired_adj else "SIN_RETIRADAS_ADJUDICABLES"),
            "n_queries": len(queries), "n_errors": sum(1 for e in per_query if e.get("error")),
            "duration_s": round(time.time() - t0, 1),
            "per_query": per_query,
        }
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        log(f"\nRESULTADO: adjudicaciones {adjudications}")
        log(f"tasa (gate <= {GATE:.0%}): "
            f"{rate:.1%}" if rate is not None else "sin retiradas adjudicables")
        log(f"GATE: {result['gate_result']} · salida: {args.out}")
        return 0
    finally:
        await lastindex.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
