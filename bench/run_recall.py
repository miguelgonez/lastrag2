#!/usr/bin/env python3
"""G6 — recall@20 y p50 por embedder sobre el corpus de escala (48.399).

Preregistrado en bench/PREREG_RECALL_WAVE2.md (oro: 10 PMIDs por consulta,
seed 20261024, muestreo sin reposición sobre positivos MeSH-estricto).
Sin LLM: recuperación pura. Los umbrales los evalúa el loop (G6).

Uso (Spark):
  # candidato MiniLM (fastembed):
  .venv/bin/python bench/run_recall.py --embedder minilm \
      --corpus cierre_brecha_real/data/pubmed_scale.jsonl --out bench/results/recall_minilm.json
  # candidato bge-m3 (venv larbench con sentence-transformers+torch):
  ~/venvs/larbench/bin/python bench/run_recall.py --embedder bge-m3 \
      --corpus ... --out bench/results/recall_bgem3.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED = 20261024
GOLD_PER_QUERY = 10
TOP_K = 20

# Descriptores MeSH canónicos por tema (mismos que calidad_scale_loop.py)
TOPIC_MESH = {
    "sglt2": "Sodium-Glucose Transporter 2 Inhibitors",
    "metformin": "Metformin",
    "heart_failure": "Heart Failure",
    "lung_screening": "Mass Screening",
    "t2d_general": "Diabetes Mellitus, Type 2",
    "hypertension": "Hypertension",
}

# 108 consultas congeladas (18/tema) — parte del prereg.
FROZEN_QUERIES_G6: dict[str, list[str]] = {
    "metformin": [
        "dosis inicial de metformina en diabetes tipo 2",
        "efectos secundarios digestivos de la metformina",
        "metformina y acidosis lactica riesgo",
        "metformina en insuficiencia renal crónica",
        "metformina en prediabetes prevención",
        "mecanismo de acción de la metformina",
        "metformina de liberación prolongada tolerancia",
        "metformina y vitamina B12 deficiencia",
        "metformina en diabetes gestacional",
        "combinación de metformina con otros antidiabéticos",
        "metformina y pérdida de peso",
        "contraindicaciones de la metformina",
        "metformina tras síndrome coronario agudo",
        "metformina en ancianos con diabetes",
        "metformina y resistencia a la insulina",
        "adesión al tratamiento con metformina",
        "metformina frente a sulfonilureas",
        "monitorización renal en tratamiento con metformina",
    ],
    "sglt2": [
        "inhibidores SGLT2 y protección renal",
        "iSGLT2 en insuficiencia cardiaca con fracción reducida",
        "empagliflozina y riesgo cardiovascular",
        "dapagliflozina en enfermedad renal crónica diabética",
        "inhibidores de SGLT2 y cetoacidosis",
        "beneficios cardiovasculares de los iSGLT2",
        "iSGLT2 y pérdida de peso en diabetes tipo 2",
        "inhibidores SGLT2 en ancianos",
        "empagliflozina frente a dapagliflozina",
        "iSGLT2 y riesgo de amputación",
        "inhibidores SGLT2 e infecciones urinarias",
        "iSGLT2 como tratamiento inicial de la diabetes",
        "mecanismo renal de los inhibidores de SGLT2",
        "iSGLT2 en insuficiencia cardiaca con fracción preservada",
        "efectos de los iSGLT2 sobre la presión arterial",
        "inhibidores SGLT2 y mortalidad cardiovascular",
        "iSGLT2 y control glucémico",
        "seguridad renal a largo plazo de los iSGLT2",
    ],
    "heart_failure": [
        "tratamiento de la insuficiencia cardiaca con fracción reducida",
        "diuréticos de asa en insuficiencia cardiaca",
        "farmacología de la insuficiencia cardiaca",
        "insuficiencia cardiaca con fracción preservada",
        "betabloqueantes en insuficiencia cardiaca",
        "sacubitrilo valsartán en insuficiencia cardiaca",
        "hospitalizaciones por insuficiencia cardiaca",
        "insuficiencia cardiaca terminal",
        "biomarcadores en insuficiencia cardiaca",
        "rehabilitación cardiaca en insuficiencia cardiaca",
        "insuficiencia cardiaca en ancianos",
        "diagnóstico de insuficiencia cardiaca",
        "fisiopatología de la insuficiencia cardiaca",
        "antagonistas del receptor mineralocorticoide en insuficiencia cardiaca",
        "insuficiencia cardiaca y diabetes",
        "seguimiento del paciente con insuficiencia cardiaca",
        "inhibidores SGLT2 aprobados en insuficiencia cardiaca",
        "pronóstico de la insuficiencia cardiaca",
    ],
    "lung_screening": [
        "cribado de cáncer de pulmón con tomografía computarizada",
        "nódulos pulmonares en el cribado",
        "tabaquismo y detección precoz de cáncer de pulmón",
        "criterios de elegibilidad para cribado pulmonar",
        "radiografía frente a TAC en detección de cáncer",
        "efectividad del screening pulmonar en mortalidad",
        "falso positivo en cribado de cáncer de pulmón",
        "cribado pulmonar en fumadores activos",
        "diagnóstico precoz del cáncer de pulmón",
        "programas poblacionales de cribado pulmonar",
        "nódulo pulmonar solitario manejo",
        "cribado pulmonar y abandono del tabaco",
        "densidad de masa pulmonar en cribado",
        "seguimiento de nódulos pulmonares pequeños",
        " cribado de cáncer de pulmón en Europa",
        "coste-efectividad del cribado pulmonar",
        "prevención del cáncer de pulmón",
        "estadiaje del cáncer de pulmón detectado en cribado",
    ],
    "t2d_general": [
        "tratamiento de la diabetes mellitus tipo 2",
        "diagnóstico de diabetes tipo 2",
        "hemoglobina glucosilada objetivos en diabetes",
        "complicaciones crónicas de la diabetes tipo 2",
        "diabetes tipo 2 y enfermedad cardiovascular",
        "estilo de vida en diabetes tipo 2",
        "nuevos fármacos para la diabetes tipo 2",
        "diabetes tipo 2 en jóvenes",
        "control glucémico intenso frente a convencional",
        "nefropatía diabética prevención",
        "retinopatía diabética cribado",
        "pie diabético prevención",
        "insulinización en diabetes tipo 2",
        "educación terapéutica en diabetes",
        "diabetes tipo 2 y obesidad",
        "agonistas GLP-1 en diabetes tipo 2",
        "hipoglucemia en diabetes tipo 2",
        "diabetes tipo 2 y enfermedad renal",
    ],
    "hypertension": [
        "tratamiento de la hipertensión arterial",
        "hipertensión arterial en ancianos",
        "objetivos de presión arterial en diabetes",
        "hipertensión resistente manejo",
        "inhibidores ECA frente a antagonistas del calcio",
        "hipertensión y enfermedad renal crónica",
        "medición domiciliaria de la presión arterial",
        "hipertensión de bata blanca",
        "hipertensión arterial secundaria",
        "diuréticos tiazídicos en hipertensión",
        "hipertensión y riesgo de ictus",
        "cambio de estilo de vida en hipertensión",
        "hipertensión en el embarazo",
        "hipertensión arterial sistólica aislada",
        "adesión al tratamiento antihipertensivo",
        "hipertensión y fibrilación auricular",
        "tratamiento combinado de la hipertensión",
        "cribado de hipertensión arterial en población",
    ],
}


def load_corpus(path: Path):
    docs = []
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if line:
            docs.append(json.loads(line))
    return docs


def build_gold(docs) -> dict[str, list[str]]:
    rng = random.Random(SEED)
    gold = {}
    for topic, descriptor in TOPIC_MESH.items():
        positives = sorted(str(d["pmid"]) for d in docs
                           if d.get("topic") == topic
                           and descriptor in (d.get("mesh_terms") or ""))
        k = min(GOLD_PER_QUERY, len(positives))
        gold[topic] = sorted(rng.sample(positives, k))
    return gold


def make_embedder(name: str):
    if name == "minilm":
        from core.embedding import FastEmbedEmbedder
        return FastEmbedEmbedder(), FastEmbedEmbedder.model_id
    if name == "bge-m3":
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("BAAI/bge-m3")

        class BGE:
            model_id = "baai-bge-m3-v1"
            dim = 1024

            def __call__(self, texts):
                return [list(map(float, v))
                        for v in model.encode(list(texts),
                                              normalize_embeddings=True)]
        return BGE(), BGE.model_id
    raise SystemExit(f"embedder desconocido: {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--embedder", required=True, choices=["minilm", "bge-m3"])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--qdrant-path", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="solo smoke declarado: NO vale para recibo")
    args = ap.parse_args()

    docs = load_corpus(args.corpus)
    if args.limit:
        docs = docs[: args.limit]
    gold = build_gold(docs)
    queries = [(t, q) for t, qs in FROZEN_QUERIES_G6.items() for q in qs]

    embedder, model_id = make_embedder(args.embedder)
    from core.backends.qdrant_backend import QdrantBackend
    qpath = args.qdrant_path or f"bench/results/g6_qdrant_{args.embedder}"
    backend = QdrantBackend(path=qpath, embedder=embedder,
                            vector_size=embedder.dim, embedding_model=model_id)

    async def run():
        await backend.initialize()
        import asyncio as aio
        from dataclasses import asdict
        from core.lastindex.parser import ParsedDocument, ParsedBlock, make_block_id
        t0 = time.time()
        pending = []
        for d in docs:
            pid = str(d["pmid"])
            doc = ParsedDocument(
                document_id=f"pubmed_{pid}", title=d["title"],
                source_path=f"pmid:{pid}",
                blocks=[ParsedBlock(block_id=make_block_id(f"pubmed_{pid}", 1, 0),
                                    text=f"{d['title']}. {d['abstract']}", page=1,
                                    section_path="Abstract", section_title="Abstract",
                                    chapter=None, order=0)],
                specialty=None, doc_type="pubmed_abstract")
            pending.append(backend.ingest(doc.source_path,
                                          document_id=doc.document_id,
                                          metadata={"blocks": [asdict(b) for b in doc.blocks],
                                                    "pmid": pid,
                                                    "topic": d.get("topic")}))
            if len(pending) >= 50:
                await aio.gather(*pending)
                pending = []
        await aio.gather(*pending)
        print(f"[g6] ingesta {len(docs)} docs en {time.time()-t0:.0f}s "
              f"({model_id})", flush=True)

        recalls, latencies = [], []
        for topic, q in queries:
            t1 = time.time()
            res = await backend.search(q, top_k=TOP_K)
            latencies.append((time.time() - t1) * 1000)
            top_pmids = set()
            for c in res.chunks:
                pm = getattr(c, "locator", "").split("::")[0].replace("pubmed_", "")
                top_pmids.add(pm)
            hits = len(top_pmids & set(gold[topic]))
            recalls.append(hits / max(1, len(gold[topic])))
        await backend.close()
        result = {
            "embedder": model_id, "corpus_n": len(docs),
            "smoke_limit": args.limit or None,
            "queries": len(queries),
            "recall_at_20": round(statistics.mean(recalls), 4),
            "p50_ms": round(statistics.median(latencies), 1),
            "p95_ms": round(sorted(latencies)[int(len(latencies) * .95)], 1),
            "gold_per_topic": {t: g for t, g in gold.items()},
            "gold_seed": SEED,
            "prereg": "bench/PREREG_RECALL_WAVE2.md",
            "prereg_sha256": hashlib.sha256(
                (ROOT / "bench/PREREG_RECALL_WAVE2.md").read_bytes()).hexdigest(),
            "per_query_recall_min": round(min(recalls), 4),
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(f"[g6] recall@20={result['recall_at_20']} p50={result['p50_ms']}ms "
              f"-> {args.out}", flush=True)

    import asyncio
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
