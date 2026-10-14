#!/usr/bin/env python3
"""
Fase 3 — Loop de calidad sobre corpus biomédico REAL (piloto)
===============================================================
Lee cierre_brecha_real/data/pubmed_pilot.jsonl (abstracts públicos reales,
gold = etiqueta de sourcing, silver-gold declarado en PREREG_QUALITY.md).
Compara:
  - baseline: hashing-dev (coseno puro)
  - real    : MiniLM ONNX → top-50 → reranker clínico → cross-encoder ONNX
              (ausencia/fallo del cross-encoder DECLARADO, jamás silencioso)

Métricas (gold topical): rec@1 = top1 del tema correcto; p@3 = proporción
de top-3 del tema correcto; MRR = 1/rango del primer acierto.
Gate: Δ rec@1 ≥ 0.25 o MRR > baseline + 0.10. N-verde = 2.
Claim limits del prereg intactos: recuperación cross-lingual ES→EN con gold
proxy; CERO claims clínicos.
Exit: 0 mejora+N-verde · 75 sin mejora/N-verde incompleto · 1 error.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.backends.base import EvidenceChunk
from core.embedding import HashingEmbedder
from core.rag.rerank import ClinicalReranker

DATA = ROOT / "cierre_brecha_real" / "data"
CBR = ROOT / "cierre_brecha_real"

QUERIES = [  # (consulta ES, gold topic) — sin calco léxico del término fuente
    ("¿Qué medicamentos hacen eliminar azúcar por la orina en la diabetes tipo 2?", "sglt2"),
    ("¿Cuál es el fármaco oral de primera línea en la diabetes y cómo actúa en el hígado?", "metformin"),
    ("¿Qué tratamientos reducen los ingresos hospitalarios por fallo cardíaco descompensado?", "heart_failure"),
    ("¿El cribado radiológico del pulmón disminuye la mortalidad por cáncer?", "lung_screening"),
]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
    return float(np.dot(a, b) / denom)


def load_corpus() -> tuple[list[dict], str]:
    # split("\n") y NO splitlines(): \u2028/\u2029 son legales dentro de
    # strings JSON (frecuentes en abstracts) y splitlines los partiría.
    rows = [json.loads(l) for l in
            (DATA / "pubmed_pilot.jsonl").read_text(encoding="utf-8").split("\n")
            if l.strip()]
    corpus_hash = hashlib.sha256(
        "\n".join(r["pmid"] for r in rows).encode()).hexdigest()[:16]
    for r in rows:
        r["_text"] = f"{r['title']}. {r['abstract']}"
    return rows, corpus_hash


def embed_pool(texts: list[str], corpus_hash: str) -> np.ndarray:
    cache = DATA / f"embeddings_{corpus_hash}.npy"
    if cache.exists():
        return np.load(cache)
    from core.embedding import FastEmbedEmbedder
    emb = FastEmbedEmbedder()
    vecs = np.array(emb(texts), dtype=np.float32)
    np.save(cache, vecs)
    return vecs


def rank_semantic(qv: np.ndarray, pool_vecs: np.ndarray, k: int) -> list[int]:
    sims = pool_vecs @ qv
    return list(np.argsort(-sims)[:k])


def rank_hashing(query: str, rows: list[dict], k: int) -> list[int]:
    hasher = HashingEmbedder()
    qv = np.array(hasher([query])[0], dtype=np.float32)
    # hashing es barato: sin caché, en vivo
    sims = []
    for r in rows:
        tv = np.array(hasher([r["_text"][:2000]])[0], dtype=np.float32)
        sims.append(cosine(qv, tv))
    return sorted(range(len(rows)), key=lambda i: -sims[i])[:k]


def metrics(order: list[int], rows: list[dict], gold: str) -> dict:
    topics = [rows[i]["topic"] for i in order]
    rec1 = 1.0 if topics and topics[0] == gold else 0.0
    p3 = (sum(1 for t in topics[:3] if t == gold) / min(3, len(topics))
          if topics else 0.0)
    mrr = 0.0
    for pos, t in enumerate(topics, start=1):
        if t == gold:
            mrr = 1.0 / pos
            break
    return {"rec1": rec1, "p3": p3, "mrr": mrr,
            "top1_topic": topics[0] if topics else None}


def evaluate(rank_fn, label: str, rows: list[dict]) -> dict:
    acc = {"rec1": [], "p3": [], "mrr": []}
    details = []
    for query, gold in QUERIES:
        order = rank_fn(query)
        m = metrics(order, rows, gold)
        for k in acc:
            acc[k].append(m[k])
        details.append({"query": query, "gold": gold, **m,
                        "top3": [rows[i]["pmid"] for i in order[:3]]})
    return {"model": label, "n_queries": len(QUERIES),
            **{k: round(sum(v) / len(v), 3) for k, v in acc.items()},
            "queries": details}


def main() -> int:
    rows, corpus_hash = load_corpus()
    print(f"corpus real: {len(rows)} abstracts · hash {corpus_hash}")

    baseline = evaluate(
        lambda q: rank_hashing(q, rows, 10),
        "local-hash-ngram-256-v1 (coseno puro)", rows)

    try:
        pool_vecs = embed_pool([r["_text"][:2000] for r in rows], corpus_hash)
        from core.embedding import FastEmbedEmbedder
        qvecs = {q: np.array(FastEmbedEmbedder()([q])[0], dtype=np.float32)
                 for q, _ in QUERIES}
    except Exception as exc:
        print(f"❌ embedder real: {type(exc).__name__}: {exc}")
        return 1

    clinical = ClinicalReranker()
    cross, cross_status = None, "not_attempted"

    def rank_real(query: str) -> list[int]:
        nonlocal cross, cross_status
        base = rank_semantic(qvecs[query], pool_vecs, 50)
        chunks = []
        for i in base:
            r = rows[i]
            chunks.append(EvidenceChunk(
                text=r["_text"][:1800], locator=r["pmid"],
                score=float(np.dot(pool_vecs[i], qvecs[query]))))
        chunks = clinical.rerank(query, chunks).ranked
        if cross_status == "ok":
            chunks = cross.rerank(query, chunks).ranked
        elif cross_status != "failed":
            try:
                from core.rag.rerank import CrossEncoderReranker
                cross = CrossEncoderReranker()
                result = cross.rerank(query, chunks)
                if "FALLBACK" in result.model:
                    cross_status = f"failed ({result.model.split('::')[-1]})"
                else:
                    cross_status = "ok"
                    chunks = result.ranked
            except Exception as exc:
                cross_status = f"unavailable ({type(exc).__name__})"
        by_pmid = {r["pmid"]: i for i, r in enumerate(rows)}
        return [by_pmid[c.locator] for c in chunks[:10]]

    real = evaluate(rank_real, f"MiniLM-ONNX + clinical_rerank"
                    + (" + cross-encoder" if cross_status == "ok" else ""), rows)

    delta = real["rec1"] - baseline["rec1"]
    improvement = delta >= 0.25 or (real["mrr"] > baseline["mrr"] + 0.10)

    state_path = CBR / "QUALITY_STATE.json"
    state = json.loads(state_path.read_text()) if state_path.exists() \
        else {"passes": 0, "history": []}
    state["passes"] = state.get("passes", 0) + 1 if improvement else 0

    receipt = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "corpus": {"n": len(rows), "hash": corpus_hash,
                   "source": "PubMed E-utilities, 5 años, 4 temas",
                   "gold": "silver-gold por sourcing (PREREG_QUALITY.md)"},
        "claim_limits": [
            "recuperación cross-lingual ES→EN sobre abstracts públicos con gold proxy",
            "NO validez clínica, NO relevancia clínica fina, NO generación",
        ],
        "baseline": baseline, "real": real, "cross_encoder": cross_status,
        "delta_rec1": round(delta, 3), "improvement_demonstrated": improvement,
    }
    (CBR / "QUALITY_CORPUS_REAL.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False))
    state.setdefault("history", []).append(
        {"at": receipt["timestamp"], "delta_rec1": round(delta, 3),
         "improvement": improvement, "cross_encoder": cross_status})
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    print(f"baseline  rec@1={baseline['rec1']:.3f} p@3={baseline['p3']:.3f} MRR={baseline['mrr']:.3f}")
    print(f"real      rec@1={real['rec1']:.3f} p@3={real['p3']:.3f} MRR={real['mrr']:.3f} Δrec@1={delta:+.3f}")
    print(f"cross-encoder: {cross_status} · mejora: {improvement} · N: {state['passes']}/2")
    if improvement and state["passes"] >= 2:
        print("🎯 corpus REAL: mejora + N-verde")
        return 0
    return 75


if __name__ == "__main__":
    sys.exit(main())
