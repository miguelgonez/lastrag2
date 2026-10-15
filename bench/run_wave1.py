#!/usr/bin/env python3
"""
Wave 1 — Fase 1: benchmark de modos de recuperación de v2-foundation.
Protocolo congelado en bench/BENCHMARK_WAVE1.md (15-oct-2026). Ejecutar en el
host Spark (Neo4j T3 + parquet del piloto). Sin LLM: recuperación pura.

Uso:
  NEO4J_URL=bolt://localhost:17687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=... \
  .venv/bin/python bench/run_wave1.py \
      --parquet ~/lastrag_pubmed_pilot/cierre_brecha_real/data/pubmed_pilot.parquet \
      --out bench/results/wave1_phase1.json
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyarrow.parquet as pq  # noqa: E402

from core.backends.qdrant_backend import QdrantBackend  # noqa: E402
from core.backends.neo4j_graph import Neo4jGraphManager  # noqa: E402
from core.embedding import HashingEmbedder  # noqa: E402
from core.lastindex.navigator import LastIndex  # noqa: E402
from core.lastindex.parser import ParsedDocument, ParsedBlock, make_block_id  # noqa: E402
from core.rag.engine import LastRAGEngine  # noqa: E402

TOP_K = 5

# 24 consultas congeladas (6 por tema). Cambiar una = re-sellar protocolo.
FROZEN_QUERIES: dict[str, list[str]] = {
    "metformin": [
        "dosis de metformina en diabetes tipo 2",
        "efectos gastrointestinales de la metformina",
        "metformina y riesgo de acidosis lactica",
        "metformina en insuficiencia renal cronica",
        "uso de metformina en prediabetes",
        "mecanismo de accion de la metformina",
    ],
    "sglt2": [
        "inhibidores SGLT2 y proteccion renal",
        "iSGLT2 en insuficiencia cardiaca",
        "empagliflozina y riesgo cardiovascular",
        "dapagliflozina en enfermedad renal cronica",
        "inhibidores de SGLT2 y cetoacidosis",
        "beneficios cardiovasculares de los iSGLT2",
    ],
    "heart_failure": [
        "tratamiento de la insuficiencia cardiaca con fraccion reducida",
        "diureticos de asa en insuficiencia cardiaca",
        "insuficiencia cardiaca y hierro intravenoso",
        "betabloqueantes en insuficiencia cardiaca cronica",
        "hospitalizaciones por insuficiencia cardiaca",
        "farmacologia de la insuficiencia cardiaca",
    ],
    "lung_screening": [
        "cribado de cancer de pulmon con tomografia de baja dosis",
        "nodulos pulmonares en el cribado",
        "tabaquismo y deteccion precoz de cancer de pulmon",
        "efectividad del screening pulmonar",
        "criterios de elegibilidad para cribado pulmonar",
        "radiografia frente a TAC en deteccion de cancer de pulmon",
    ],
}

# Respaldo léxico cuando la cita no resuelve el documento (declarado en el
# protocolo: el oro es temático silver).
_TOPIC_HINTS = {
    "metformin": ("metformin", "metformina", "biguanid"),
    "sglt2": ("sglt2", "empagliflozin", "dapagliflozin", "canagliflozin",
              "sodium-glucose", "gliflozin"),
    "heart_failure": ("heart failure", "insuficiencia cardiaca",
                      "hfref", "cardiac failure", "cardiomyopathy"),
    "lung_screening": ("lung cancer screening", "screening", "cribado",
                       "low-dose", "low dose", "pulmonary nodule", "lung cancer"),
}


def build_corpus(parquet_path: str):
    """Devuelve (documentos ParsedDocument, titulo->tema, pmid->tema)."""
    rows = pq.read_table(parquet_path).to_pylist()
    docs, title_to_topic, pmid_to_topic = [], {}, {}
    for row in rows:
        abstract = (row.get("abstract") or "").strip()
        if len(abstract) < 80:
            continue
        pmid = str(row["pmid"])
        document_id = f"pubmed_{pmid}"
        docs.append(ParsedDocument(
            document_id=document_id, title=row["title"],
            source_path=f"pmid:{pmid}",
            blocks=[ParsedBlock(
                block_id=make_block_id(document_id, 1, 0),
                text=f"{row['title']}. {abstract}", page=1,
                section_path="Abstract", section_title="Abstract",
                chapter=None, order=0)],
            specialty=None, doc_type="pubmed_abstract"))
        title_to_topic[row["title"]] = row["topic"]
        pmid_to_topic[document_id] = row["topic"]
    return docs, title_to_topic, rows


def topic_of_chunk(chunk, title_to_topic: dict, query_topic: str) -> bool:
    """Un chunk es 'del tema' si su cita resuelve a un documento del tema o,
    sin cita, si su texto encaja léxicamente con el tema (respaldo declarado)."""
    if chunk.citation and chunk.citation.document in title_to_topic:
        return title_to_topic[chunk.citation.document] == query_topic
    return _text_heuristic(chunk.text, query_topic)


def _text_heuristic(text: str, topic: str) -> bool:
    t = text.lower()
    return any(h in t for h in _TOPIC_HINTS.get(topic, ()))


def mean_or_none(values):
    return round(statistics.mean(values), 4) if values else None


def latency_block(values):
    if not values:
        return {"p50_ms": None, "p95_ms": None, "n": 0}
    ordered = sorted(values)
    return {"p50_ms": round(ordered[len(ordered) // 2] * 1000, 1),
            "p95_ms": round(ordered[min(len(ordered) - 1,
                                        int(len(ordered) * 0.95))] * 1000, 1),
            "n": len(ordered)}


def new_mode():
    return {"precision": [], "mrr": [], "citation": [], "latency": [], "empty": 0}


def record(mode: dict, chunks, query_topic: str, title_to_topic, latency: float):
    mode["latency"].append(latency)
    if not chunks:
        mode["empty"] += 1
        mode["precision"].append(0.0)
        mode["mrr"].append(0.0)
        mode["citation"].append(0.0)
        return
    hits, first = 0, None
    for rank, chunk in enumerate(chunks, start=1):
        if topic_of_chunk(chunk, title_to_topic, query_topic):
            hits += 1
            if first is None:
                first = rank
    mode["precision"].append(hits / len(chunks))
    mode["mrr"].append(1.0 / first if first else 0.0)
    mode["citation"].append(
        sum(1 for c in chunks if c.citation and c.citation.block_id) / len(chunks))


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--qdrant-path", default="/tmp/wave1_qdrant")
    parser.add_argument("--skip-ingest", action="store_true",
                        help="corpus ya ingerido (mismo qdrant-path y Neo4j)")
    args = parser.parse_args()

    docs, title_to_topic, rows = build_corpus(args.parquet)
    n_queries = sum(len(v) for v in FROZEN_QUERIES.values())
    print(f"[wave1] corpus usable: {len(docs)} abstracts de {len(rows)} filas; "
          f"{n_queries} consultas congeladas")

    backend = QdrantBackend(
        path=args.qdrant_path, collection="wave1",
        embedder=HashingEmbedder(), vector_size=HashingEmbedder.dim,
        embedding_model=HashingEmbedder.model_id)
    lastindex = LastIndex(os.getenv("NEO4J_URL", "bolt://localhost:7687"),
                          os.getenv("NEO4J_USERNAME", "neo4j"),
                          os.getenv("NEO4J_PASSWORD", "password"))
    fuse = LastRAGEngine._fuse

    if not args.skip_ingest:
        await backend.initialize()
        await lastindex.setup_schema()
        t0 = time.perf_counter()
        for i, doc in enumerate(docs):
            await lastindex.ingest_tree(doc)
            await backend.ingest(doc.source_path, document_id=doc.document_id,
                                 metadata={"blocks": [asdict(b) for b in doc.blocks]})
            if (i + 1) % 200 == 0:
                print(f"[wave1] ingeridos {i + 1}/{len(docs)} "
                      f"({time.perf_counter() - t0:.0f}s)")
        print(f"[wave1] ingesta completa: {len(docs)} docs "
              f"en {time.perf_counter() - t0:.0f}s")

    modes = {name: new_mode() for name in ("vector_only", "index_only", "hybrid")}
    graph_queries_with_nodes = 0
    graph = Neo4jGraphManager()

    try:
        for topic, queries in FROZEN_QUERIES.items():
            for query in queries:
                # --- vector_only: Qdrant + citas resueltas por LastIndex ---
                t0 = time.perf_counter()
                vec = await backend.search(query, top_k=TOP_K)
                vec_latency = time.perf_counter() - t0
                await lastindex.enrich_chunks(vec.chunks)
                record(modes["vector_only"], vec.chunks, topic,
                       title_to_topic, vec_latency)

                # --- index_only: full-text estructural de Neo4j ---
                t0 = time.perf_counter()
                idx = await lastindex.structural_search(query, top_k=TOP_K)
                idx_latency = time.perf_counter() - t0
                record(modes["index_only"], idx, topic, title_to_topic, idx_latency)

                # --- hybrid: misma fusión por locator que el motor ---
                t0 = time.perf_counter()
                fused = fuse(vec.chunks, idx)
                fuse_latency = time.perf_counter() - t0
                record(modes["hybrid"], fused[:TOP_K], topic,
                       title_to_topic, vec_latency + idx_latency + fuse_latency)

                # --- graph_context: disponibilidad de nodos (no ranking) ---
                try:
                    nodes = await graph.search_related(query=topic, max_depth=2)
                    if nodes:
                        graph_queries_with_nodes += 1
                except Exception as exc:
                    print(f"[wave1] graph error en '{topic}': {type(exc).__name__}")
    finally:
        await graph.close()
        await lastindex.close()
        await backend.close()

    result = {
        "protocol": "bench/BENCHMARK_WAVE1.md (fase 1, congelado 15-oct-2026)",
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "corpus": {"rows": len(rows), "usable_abstracts": len(docs),
                   "gold": "topic_label_silver (declarado, no clinico)"},
        "embedder": HashingEmbedder.model_id,
        "top_k": TOP_K,
        "modes": {name: {
            "topical_precision@5": mean_or_none(m["precision"]),
            "first_hit_mrr": mean_or_none(m["mrr"]),
            "citation_support@5": mean_or_none(m["citation"]),
            **latency_block(m["latency"]),
            "empty_rate": round(m["empty"] / n_queries, 4),
        } for name, m in modes.items()},
        "graph_context": {"queries_with_nodes": graph_queries_with_nodes,
                          "total_queries": n_queries},
        "limitations": ["embedder desarrollo no semantico",
                        "oro tematico silver", "sin baseline LastRAG-MD (fase 2)"],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["modes"], ensure_ascii=False, indent=2))
    print("graph_context:", result["graph_context"])
    print(f"[wave1] resultados en {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
