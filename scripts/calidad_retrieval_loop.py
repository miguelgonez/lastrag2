#!/usr/bin/env python3
"""
Loop de calidad de retrieval — siguiente salto post-100 % arquitectónico
==========================================================================
Compara sobre el conjunto duro de paráfrasis (solapamiento léxico mínimo):
  - baseline : hashing-dev (ranking por coseno puro)
  - real     : MiniLM ONNX → reranker clínico determinista →
               cross-encoder ONNX (si el modelo está disponible; su ausencia
               o fallo queda DECLARADA en el recibo, jamás pass silencioso)

Métricas: recall@1, recall@3, MRR. Mejora clara exigida: Δ recall@1 ≥ 0.3
(o MRR > baseline + 0.15). N-verde = 2 pasadas consecutivas con mejora.

Claim limits (intactos): NO acredita calidad semántica sobre corpus biomédico
real, ni calidad clínica, ni utilidad terapéutica. Mide discriminación de
paráfrasis controladas + efecto de los rerankers sobre ellas.

Exit: 0 = mejora + N-verde · 75 = sin mejora suficiente o N-verde incompleto ·
1 = error (embedder real no disponible).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.backends.base import EvidenceChunk
from core.embedding import HashingEmbedder
from core.rag.rerank import ClinicalReranker

try:
    from core.embedding import FastEmbedEmbedder
    REAL_AVAILABLE = True
except Exception:
    REAL_AVAILABLE = False

CORPUS_HARD = [
    ("gold_hipogluc", "Los inhibidores de SGLT2 provocan pérdida de glucosa por orina y bajadas de azúcar."),
    ("gold_neo", "La canagliflozina se asocia a cetoacidosis euglucémica de inicio agudo."),
    ("gold_cardio", "La empagliflozina reduce los ingresos por descompensación cardíaca."),
    ("d1", "La dieta mediterránea con aceite de oliva mejora el perfil lipídico."),
    ("d2", "El ejercicio aeróbico regular mejora la capacidad funcional y el estado de ánimo."),
    ("d3", "La cirugía bariátrica reduce el peso y la resolución de comorbilidades."),
    ("d4", "Los corticoides sistémicos aumentan la glucemia de forma transitoria."),
    ("d5", "La insulina rápida corrige las hiperglucemias postprandiales."),
    ("d6", "El control de la presión arterial previene la nefropatía diabética."),
    ("d7", "La retinopatía diabética requiere cribado anual con fondo de ojo."),
    ("d8", "La metformina es primera línea y actúa reduciendo la gluconeogénesis hepática."),
]

QUERIES_HARD = [
    ("¿Qué ocurre con el azúcar en sangre al orinarla con los nuevos fármacos renales?", "gold_hipogluc"),
    ("¿Qué complicación aguda metabólica se atribuye a los inhibidores del cotransportador renal?", "gold_neo"),
    ("¿Qué beneficios hay para el corazón descompensado con los gliflozinas?", "gold_cardio"),
    ("¿Qué efecto tiene orinar azúcar con los inhibidores del transportador de sodio-glucosa?", "gold_hipogluc"),
    ("¿Qué riesgo agudo de acidosis sin hiperglucemia se vincula a canagliflozina?", "gold_neo"),
    ("¿Qué impacto tiene empagliflozina en las hospitalizaciones por fallo cardíaco?", "gold_cardio"),
]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def to_chunks(ranked_locs: list[str]) -> list[EvidenceChunk]:
    by_loc = dict(CORPUS_HARD)
    return [EvidenceChunk(text=by_loc[loc], locator=loc, score=1.0 - i * 0.01)
            for i, loc in enumerate(ranked_locs)]


def rank_baseline(embedder, query, k=5) -> list[str]:
    qv = embedder([query])[0]
    scored = sorted(((cosine(qv, embedder([t])[0]), loc) for loc, t in CORPUS_HARD),
                    reverse=True)
    return [loc for _, loc in scored[:k]]


def metrics(ranked_list, gold):
    try:
        pos = ranked_list.index(gold) + 1
    except ValueError:
        return 0.0, 0.0, 0.0
    return (1.0 if pos == 1 else 0.0, 1.0 if pos <= 3 else 0.0, 1.0 / pos)


def evaluate(rank_fn, label: str) -> dict:
    r1, r3, mrr, details = [], [], [], []
    for query, gold in QUERIES_HARD:
        ranked = rank_fn(query, k=5)
        rec1, rec3, rr = metrics(ranked, gold)
        r1.append(rec1); r3.append(rec3); mrr.append(rr)
        details.append({"query": query, "gold": gold,
                        "top1": ranked[0] if ranked else None,
                        "recall1": rec1, "recall3": rec3, "rr": round(rr, 3)})
    return {"embedding_model": label, "n_queries": len(QUERIES_HARD),
            "recall1": round(sum(r1) / len(r1), 3),
            "recall3": round(sum(r3) / len(r3), 3),
            "mrr": round(sum(mrr) / len(mrr), 3), "queries": details}


def main() -> int:
    dest = ROOT / "cierre_brecha" / "QUALITY_RETRIEVAL.json"
    state_path = ROOT / "cierre_brecha" / "QUALITY_STATE.json"
    state = json.loads(state_path.read_text()) if state_path.exists() \
        else {"passes": 0, "history": []}

    baseline = evaluate(lambda q, k: rank_baseline(HashingEmbedder(), q, k),
                        "local-hash-ngram-256-v1 (sin rerank)")

    real, cross_status = None, "not_attempted"
    if not REAL_AVAILABLE:
        print("❌ Embedder real no disponible (fastembed no importable)")
        state["passes"] = 0
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        return 1
    emb = FastEmbedEmbedder()
    clinical = ClinicalReranker()

    cross = None  # instanciado bajo demanda; su ausencia se DECLARA

    def rank_real(query, k=5):
        nonlocal cross, cross_status
        base = rank_baseline(emb, query, k=10)
        chunks = clinical.rerank(query, to_chunks(base)).ranked
        if cross_status in ("ok", "failed"):
            if cross_status == "ok":
                chunks = cross.rerank(query, chunks).ranked
            return [c.locator for c in chunks[:k]]
        # primer intento de cross-encoder: instancia real o ausencia declarada
        try:
            from core.rag.rerank import CrossEncoderReranker
            cross = CrossEncoderReranker()
            result = cross.rerank(query, chunks)
            if "FALLBACK" in result.model:
                cross_status = f"failed ({result.model})"
                return [c.locator for c in chunks[:k]]
            cross_status = "ok"
            return [c.locator for c in result.ranked[:k]]
        except Exception as exc:
            cross_status = f"unavailable ({type(exc).__name__})"
            return [c.locator for c in chunks[:k]]

    real = evaluate(rank_real, f"{emb.model_id} + clinical_rerank"
                    + (" + cross-encoder-onnx" if cross_status == "ok" else ""))

    delta_r1 = real["recall1"] - baseline["recall1"]
    improvement = delta_r1 >= 0.3 or (real["mrr"] > baseline["mrr"] + 0.15)

    receipt = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "corpus": "conjunto duro de paráfrasis (solapamiento léxico mínimo) — sintético ES",
        "claim_limits": [
            "NO valida calidad semántica sobre corpus biomédico real",
            "NO valida calidad clínica ni utilidad terapéutica",
            "Mide discriminación de paráfrasis controladas + efecto de "
            "rerankers (clínico determinista; cross-encoder ONNX si available)",
        ],
        "baseline": baseline,
        "real": real,
        "cross_encoder": cross_status,
        "delta_recall1": round(delta_r1, 3),
        "improvement_demonstrated": improvement,
    }
    dest.write_text(json.dumps(receipt, indent=2, ensure_ascii=False))

    print(f"Baseline (hashing)  recall@1 = {baseline['recall1']:.3f} · MRR = {baseline['mrr']:.3f}")
    print(f"Real (pipeline)     recall@1 = {real['recall1']:.3f} · MRR = {real['mrr']:.3f} · Δr@1 = {delta_r1:+.3f}")
    print(f"cross-encoder: {cross_status}")
    print(f"Mejora demostrada: {improvement}")

    state["passes"] = state.get("passes", 0) + 1 if improvement else 0
    state.setdefault("history", []).append(
        {"at": receipt["timestamp"], "delta_r1": round(delta_r1, 3),
         "improvement": improvement, "cross_encoder": cross_status})
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    print(f"Pasadas con mejora: {state['passes']}/2")
    print(f"Recibo: {dest}")
    if improvement and state["passes"] >= 2:
        print("🎯 Calidad de retrieval: mejora demostrada + N-verde")
        return 0
    return 75


if __name__ == "__main__":
    sys.exit(main())
