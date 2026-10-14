#!/usr/bin/env python3
"""
Escala — Embeddings del corpus 50 k (compatible Picasso B200).
===============================================================
Motor torch+CUDA si hay GPU (B200: batch grande, fp16); si no, fastembed
ONNX/CPU local y lo DECLARA. Salida: npz {vectors, pmids} con hash del
corpus en el nombre (recalculo si el corpus cambia — prereg).

Uso:
  local : .venv/bin/python scripts/scale_embeddings.py
  picasso: (SLURM) python scripts/scale_embeddings.py --engine torch
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "cierre_brecha_real" / "data"
CBR = ROOT / "cierre_brecha_real"

MODEL_LOCAL = "paraphrase-multilingual-minilm-onnx-v1"      # fastembed
MODEL_TORCH = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def load_corpus():
    rows = [json.loads(l) for l in
            (DATA / "pubmed_scale.jsonl").read_text(encoding="utf-8").split("\n")
            if l.strip()]
    h = hashlib.sha256("\n".join(r["pmid"] for r in rows).encode()).hexdigest()[:16]
    return rows, h


def embed_fastembed(texts: list[str]) -> np.ndarray:
    from core.embedding import FastEmbedEmbedder
    emb = FastEmbedEmbedder()
    t0 = time.time()
    vecs = np.array(emb([t[:2000] for t in texts]), dtype=np.float32)
    print(f"[embed] fastembed ONNX/CPU: {len(texts)} textos en {time.time()-t0:.0f}s")
    return vecs


def embed_torch(texts: list[str], batch: int = 256) -> tuple[np.ndarray, str]:
    import torch
    from sentence_transformers import SentenceTransformer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    name = torch.cuda.get_device_name(0) if device == "cuda" else "cpu"
    print(f"[embed] engine=torch · device={device} ({name})")
    model = SentenceTransformer(MODEL_TORCH, device=device)
    t0 = time.time()
    vecs = model.encode([t[:2000] for t in texts], batch_size=batch,
                        show_progress_bar=True,
                        normalize_embeddings=True).astype(np.float32)
    print(f"[embed] {len(texts)} textos en {time.time()-t0:.0f}s")
    return vecs, f"{MODEL_TORCH}@{device}:{name}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["auto", "fastembed", "torch"],
                    default="auto")
    args = ap.parse_args()

    rows, h = load_corpus()
    print(f"[embed] corpus: {len(rows)} abstracts · hash {h}")
    out = DATA / f"scale_embeddings_{h}.npz"
    if out.exists():
        print(f"[embed] caché vigente: {out}")
        return 0

    texts = [f"{r['title']}. {r['abstract']}" for r in rows]
    engine_used, model_label = None, None
    if args.engine in ("auto", "torch"):
        try:
            vecs, model_label = embed_torch(texts)
            engine_used = "torch"
        except Exception as exc:
            print(f"[embed] torch no disponible ({type(exc).__name__}) — "
                  f"fallback ONNX/CPU DECLARADO")
    if engine_used is None:
        vecs = embed_fastembed(texts)
        engine_used = "fastembed"
        model_label = MODEL_LOCAL + " (local/ONNX — Picasso no usado o no disponible)"

    np.savez(out, vectors=vecs, pmids=np.array([r["pmid"] for r in rows]))
    (CBR / "EMBED_SCALE_RECEIPT.json").write_text(json.dumps({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "n": len(rows), "corpus_hash": h, "engine": engine_used,
        "model": model_label, "cache": str(out),
        "claim": "cómputo de embeddings; el hardware no aporta calidad clínica",
    }, indent=2, ensure_ascii=False))
    print(f"[embed] ✅ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
