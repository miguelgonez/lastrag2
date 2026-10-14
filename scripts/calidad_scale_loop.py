#!/usr/bin/env python3
"""
Escala — Loop de calidad sobre 50 k abstracts con gold MeSH-estricto.
=======================================================================
PREREG_SCALE.md manda: gate Δ rec@1 ≥ 0.15 (o MRR > baseline+0.08),
N-verde=2, exits 0/75/1, claim limits intactos.

Gold PRIMARIO MeSH-estricto (descriptor canónico por tema en mesh_terms);
los abstracts del sourcing SIN descriptor quedan como distractores.
Fallback DECLARADO por tema si cobertura MeSH < 30% (silver-gold sourcing).
"""
from __future__ import annotations

import hashlib
import json
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

QUERIES = [
    ("¿Qué medicamentos hacen eliminar azúcar por la orina en la diabetes tipo 2?", "sglt2"),
    ("¿Cuál es el fármaco oral de primera línea en la diabetes y cómo actúa en el hígado?", "metformin"),
    ("¿Qué tratamientos reducen los ingresos hospitalarios por fallo cardíaco descompensado?", "heart_failure"),
    ("¿El cribado radiológico del pulmón disminuye la mortalidad por cáncer?", "lung_screening"),
    ("¿Cómo se controla la glucemia basal en la diabetes del adulto y sus complicaciones?", "t2d_general"),
    ("¿Qué fármacos bajan la presión arterial alta y previenen el ictus?", "hypertension"),
]
# Descriptor canónico por tema (gold MeSH-estricto del prereg)
MESH_GOLD = {
    "sglt2": "Sodium-Glucose Transporter 2 Inhibitors",
    "metformin": "Metformin",
    "heart_failure": "Heart Failure",
    "lung_screening": "Lung Neoplasms",
    "t2d_general": "Diabetes Mellitus, Type 2",
    "hypertension": "Hypertension",
}


def load_corpus():
    rows = [json.loads(l) for l in
            (DATA / "pubmed_scale.jsonl").read_text(encoding="utf-8").split("\n")
            if l.strip()]
    h = hashlib.sha256("\n".join(r["pmid"] for r in rows).encode()).hexdigest()[:16]
    for r in rows:
        r["_text"] = f"{r['title']}. {r['abstract']}"
    return rows, h


def gold_flags(rows: list[dict]) -> dict:
    """Por tema: (n_sourcing, n_mesh_stricto, cobertura). Decide gold usado."""
    rep = {}
    for topic, descriptor in MESH_GOLD.items():
        n_src = sum(1 for r in rows if r["topic"] == topic)
        n_strict = sum(1 for r in rows
                       if r["topic"] == topic and descriptor in r["mesh_terms"])
        cov = (n_strict / n_src) if n_src else 0.0
        rep[topic] = {"sourcing": n_src, "mesh_stricto": n_strict,
                      "cobertura": round(cov, 3),
                      "gold_usado": "mesh_stricto" if cov >= 0.30 else "sourcing_fallback"}
    return rep


def is_gold(row: dict, topic: str, gold_report: dict) -> bool:
    if gold_report[topic]["gold_usado"] == "mesh_stricto":
        return MESH_GOLD[topic] in row["mesh_terms"]
    return row["topic"] == topic


def metrics(order: list[int], rows: list[dict], topic: str, gold_report) -> dict:
    flags = [is_gold(rows[i], topic, gold_report) for i in order]
    rec1 = 1.0 if flags and flags[0] else 0.0
    p3 = (sum(flags[:3]) / min(3, len(flags))) if flags else 0.0
    mrr = 0.0
    for pos, f in enumerate(flags, start=1):
        if f:
            mrr = 1.0 / pos
            break
    return {"rec1": rec1, "p3": p3, "mrr": mrr}


def evaluate(rank_fn, label, rows, gold_report) -> dict:
    accs = {"rec1": [], "p3": [], "mrr": []}
    details = []
    for query, topic in QUERIES:
        order = rank_fn(query)
        m = metrics(order, rows, topic, gold_report)
        for k in accs:
            accs[k].append(m[k])
        details.append({"query": query, "topic": topic, **m,
                        "top3_pmids": [rows[i]["pmid"] for i in order[:3]]})
    return {"model": label, **{k: round(sum(v) / len(v), 3)
                               for k, v in accs.items()}, "queries": details}


def main() -> int:
    rows, corpus_hash = load_corpus()
    gold_report = gold_flags(rows)
    print(f"corpus: {len(rows)} abstracts · hash {corpus_hash}")
    print("gold por tema:", json.dumps(gold_report, ensure_ascii=False))

    # embeddings cacheados (scale_embeddings.py)
    npz_files = sorted(DATA.glob(f"scale_embeddings_{corpus_hash}.npz"))
    if not npz_files:
        print("❌ sin embeddings cacheados para este corpus — ejecutar antes "
              "scripts/scale_embeddings.py (declarado, no se calcula aquí)")
        return 1
    z = np.load(npz_files[0])
    pool_vecs, pmids = z["vectors"], list(z["pmids"])
    by_pmid = {r["pmid"]: i for i, r in enumerate(rows)}
    order_idx = [by_pmid[p] for p in pmids]  # alineación filas↔vectores
    pool_vecs = pool_vecs
    receipt_emb = json.loads((CBR / "EMBED_SCALE_RECEIPT.json").read_text()) \
        if (CBR / "EMBED_SCALE_RECEIPT.json").exists() else {}

    # baseline hashing (submuestreo determinista de 4000 para coste CPU)
    rng = np.random.default_rng(42)
    sample = sorted(rng.choice(len(rows), size=min(4000, len(rows)),
                               replace=False).tolist())

    def rank_baseline(query: str) -> list[int]:
        hasher = HashingEmbedder()
        qv = np.array(hasher([query])[0], dtype=np.float32)
        sims = []
        for i in sample:
            tv = np.array(hasher([rows[i]["_text"][:2000]])[0], dtype=np.float32)
            sims.append((float(np.dot(qv, tv) / ((np.linalg.norm(qv) * np.linalg.norm(tv)) or 1)), i))
        sims.sort(reverse=True)
        return [i for _, i in sims[:10]]

    from core.embedding import FastEmbedEmbedder
    qvecs = {q: np.array(FastEmbedEmbedder()([q])[0], dtype=np.float32)
             for q, _ in QUERIES}

    clinical = ClinicalReranker()
    cross, cross_status = None, "not_attempted"

    def rank_real(query: str) -> list[int]:
        nonlocal cross, cross_status
        qv = qvecs[query]
        top = np.argsort(-(pool_vecs @ qv))[:50]
        chunks = [EvidenceChunk(text=rows[order_idx[int(i)]]["_text"][:1800],
                                locator=rows[order_idx[int(i)]]["pmid"],
                                score=float(pool_vecs[int(i)] @ qv))
                  for i in top]
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
        pos = {r["pmid"]: i for i, r in enumerate(rows)}
        return [pos[c.locator] for c in chunks[:10]]

    baseline = evaluate(rank_baseline, "hashing-dev (coseno puro, subm. 4k)",
                        rows, gold_report)
    real = evaluate(rank_real, "MiniLM-ONNX + clinical + cross-encoder",
                    rows, gold_report)

    # ---- Tercera vía biomédica (PubMedBERT, solo si hay caché o CUDA) ----
    biomed = None
    npz_b = DATA / f"scale_embeddings_biomed_{corpus_hash}.npz"
    try:
        from scripts.scale_embeddings import load_embedder  # noqa
    except Exception:
        pass
    if npz_b.exists():
        zb = np.load(npz_b)
        bvecs = zb["vectors"]
        order_b = [by_pmid[pm] for pm in zb["pmids"]]
        bvecs_shared = bvecs  # para la variante EN (mismo pool)

        # Consultas ES embebidas por PubMedBERT en la B200 (job/srun de
        # Picasso): sin ellas, la vía biomédica queda DECLARADA no medible
        # en local (el MBP no tiene torch). Mismo orden que QUERIES.
        qnpz = DATA / f"query_embeddings_biomed_{corpus_hash}.npz"
        if qnpz.exists():
            zq = np.load(qnpz, allow_pickle=False)
            qv_b = {str(q): zq["vectors"][i]
                    for i, q in enumerate(zq["queries"])}
            b_label = ("microsoft/BiomedNLP-PubMedBERT…@cuda:NVIDIA B200 "
                       "(pool y queries)")
        else:
            def embed_queries_biomed(queries):
                import sys as _sys
                _sys.path.insert(0, str(ROOT / "scripts"))
                from scale_embeddings import load_embedder
                fn, label, dev = load_embedder("torch")
                if dev != "cuda":
                    return None, label
                qv = fn([q for q, _ in queries])
                return {q: qv[i] for i, (q, _) in enumerate(queries)}, label
            qv_b, b_label = embed_queries_biomed(QUERIES)
        if qv_b is not None:
            def rank_biomed(query: str) -> list[int]:
                top = np.argsort(-(bvecs @ qv_b[query]))[:10]
                return [order_b[int(i)] for i in top]
            biomed = evaluate(rank_biomed, f"{b_label} (coseno puro)", rows,
                              gold_report)
        else:
            biomed = {"model": b_label, "status": "queries_no_embeddables"}
    else:
        biomed = {"status": "not_available",
                  "reason": "sin caché biomédica ni CUDA (generar con "
                            "scale_embeddings.py --biomed en GPU; p.ej. "
                            "Picasso B200) — DECLARADO, no medido"}

    # Cierre del hilo embeddings: mismas vías, consultas EN — aísla si el
    # 0.0 de PubMedBERT era IDIOMA (cross-lingual) o dominio/representación.
    biomed_en = None
    npz_en = DATA / f"query_embeddings_biomed_en_{corpus_hash}.npz"
    if npz_en.exists() and npz_b.exists():
        ze = np.load(npz_en)
        qv_en = {str(q): ze["vectors"][i] for i, q in enumerate(ze["queries"])}
        order_e = [by_pmid[pm] for pm in zb["pmids"]]

        # (mapeo posicional: la i-ésima consulta EN corresponde a QUERIES[i])
        en_vecs = list(qv_en.values())

        def _rank_en(i: int) -> list[int]:
            top = np.argsort(-(bvecs_shared @ en_vecs[i]))[:10]
            return [order_e[int(t)] for t in top]

        accs = {"rec1": [], "p3": [], "mrr": []}
        details = []
        for i, (query, topic) in enumerate(QUERIES):
            order = _rank_en(i)
            m = metrics(order, rows, topic, gold_report)
            for k in accs:
                accs[k].append(m[k])
            details.append({"query_es": query, "topic": topic, **m})
        biomed_en = {"model": "PubMedBERT@B200 (consultas EN, coseno puro)",
                     **{k: round(sum(v) / len(v), 3) for k, v in accs.items()},
                     "queries": details,
                     "purpose": "aislar idioma vs dominio"}

    delta = real["rec1"] - baseline["rec1"]
    improvement = delta >= 0.15 or (real["mrr"] > baseline["mrr"] + 0.08)

    state_path = CBR / "QUALITY_SCALE_STATE.json"
    state = json.loads(state_path.read_text()) if state_path.exists() \
        else {"passes": 0, "history": []}
    state["passes"] = state.get("passes", 0) + 1 if improvement else 0

    receipt = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "corpus": {"n": len(rows), "hash": corpus_hash,
                   "source": "PubMed 5 años, 4 temas × 12.500 (PREREG_SCALE)"},
        "gold": {"primary": "MeSH-estricto por descriptor canónico",
                 "por_tema": gold_report,
                 "fallback_declared": [t for t, g in gold_report.items()
                                       if g["gold_usado"] != "mesh_stricto"]},
        "embeddings": {"engine": receipt_emb.get("engine"),
                       "model": receipt_emb.get("model")},
        "baseline": baseline, "real": real, "biomedical": biomed,
        "biomedical_en": biomed_en,
        "cross_encoder": cross_status,
        "delta_rec1": round(delta, 3), "gate": "Δrec@1≥0.15 o MRR>base+0.08",
        "improvement_demonstrated": improvement,
        "claim_limits": ["recuperación sobre abstracts públicos; NO relevancia "
                         "clínica fina, validez clínica ni generación",
                         "el hardware (local o B200) no aporta calidad clínica",
                         "tercera vía biomédica mide recuperación; no validez "
                         "clínica; PubMedBERT monolingual EN (consultas ES por "
                         "subpalabras, declarado)"],
    }
    (CBR / "QUALITY_SCALE.json").write_text(json.dumps(receipt, indent=2,
                                                       ensure_ascii=False))
    state.setdefault("history", []).append(
        {"at": receipt["timestamp"], "delta_rec1": round(delta, 3),
         "improvement": improvement, "cross_encoder": cross_status})
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    print(f"baseline rec@1={baseline['rec1']:.3f} p@3={baseline['p3']:.3f} MRR={baseline['mrr']:.3f}")
    print(f"real     rec@1={real['rec1']:.3f} p@3={real['p3']:.3f} MRR={real['mrr']:.3f} Δ={delta:+.3f}")
    print(f"cross: {cross_status} · mejora: {improvement} · N: {state['passes']}/2")
    if improvement and state["passes"] >= 2:
        print("🎯 ESCALA 50k: mejora + N-verde (gold MeSH-estricto)")
        return 0
    return 75


if __name__ == "__main__":
    sys.exit(main())
