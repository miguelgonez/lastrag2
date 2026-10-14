#!/usr/bin/env python3
"""
Benchmark de fusión y coste de degradaciones — recibo de evidencia (Ola 1/5).
==============================================================================
1. Fusión: recall@3 de fuse_by_locator vs fuse_rrf sobre corpus sintético
   biomédico ES, vía semántica con el embedder DISPONIBLE (hashing-dev y,
   si el modelo ONNX está accesible, multilingual-e5-small REAL). El modelo
   usado queda etiquetado: ninguna medición atribuye calidad al embedder
   equivocado.
2. Degradación: coste medido (ms) de recuperar con LastIndex caído vs sano,
   registrando que la degradación queda DECLARADA (nunca respuesta normal
   silenciosa).

Salida: cierre_brecha/BENCHMARK_FUSION.json (recibo con hashes de contexto).
NO es un benchmark de calidad semántica sobre corpus biomédico real (eso
requiere corpus real y sigue NOT_VALIDATED); mide FUSIÓN y COSTE.
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.backends.base import EvidenceChunk, Citation
from core.embedding import HashingEmbedder
from core.rag.fusion import fuse_by_locator, fuse_rrf

CORPUS = [
    ("blk_tto", "La metformina es el tratamiento de primera línea en la diabetes tipo 2."),
    ("blk_dose", "La dosis inicial de metformina es de 500 mg al día con las comidas."),
    ("blk_contra", "La metformina está contraindicada en insuficiencia renal grave."),
    ("blk_rct", "Ensayo aleatorizado: la metformina reduce la hemoglobina glucosilada frente a placebo."),
    ("blk_obs", "Estudio observacional: la metformina se asocia con menor mortalidad cardiovascular."),
    ("blk_sulfo", "Las sulfonilureas aumentan el riesgo de hipoglucemia en pacientes ancianos."),
    ("blk_ins", "La insulina glargina se administra una vez al día por vía subcutánea."),
    ("blk_diag", "El diagnóstico de diabetes tipo 2 requiere dos glucemias en ayunas alteradas."),
    ("blk_life", "El ejercicio aeróbico regular mejora el control glucémico y la sensibilidad a la insulina."),
    ("blk_mono", "La monitorización continua de glucosa reduce el tiempo en hipoglucemia."),
]
# Conjunto DURO: paráfrasis con solapamiento léxico mínimo — el embedding
# hashing-dev DEBE fallar aquí; un embedder semántico real debe ganar.
# (Es el recibo que justifica el gate de embedder real de la Ola 1.)
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
]

QUERIES = [
    ("¿Cuál es el tratamiento de primera línea en DM2?", "blk_tto"),
    ("¿Qué dosis inicial tiene la metformina?", "blk_dose"),
    ("¿Qué ensayo aleatorizado respalda la metformina?", "blk_rct"),
    ("¿Qué se asocia con menor mortalidad cardiovascular?", "blk_obs"),
    ("¿Cómo se administra la insulina glargina?", "blk_ins"),
]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def lexical_ranking(query, k=5):
    q = {w for w in query.lower().replace("¿", "").replace("?", "").split()
         if len(w) > 3}
    scored = []
    for loc, text in CORPUS:
        t = set(text.lower().split())
        overlap = len(q & t)
        scored.append((overlap, loc))
    scored.sort(reverse=True)
    return [loc for _, loc in scored[:k]]


def embedder_ranking(embedder, query, k=5, label=""):
    qv = embedder([query])[0]
    scored = []
    for loc, text in CORPUS:
        tv = embedder([text])[0]
        scored.append((cosine(qv, tv), loc))
    scored.sort(reverse=True)
    return [loc for _, loc in scored[:k]]


def recall_at_3(ranked, gold):
    return 1.0 if gold in ranked[:3] else 0.0


def bench_hard(embedder, model_label):
    """Recall@1 sobre el conjunto duro (paráfrasis). hashing-dev se espera
    < 1.0; el embedder real debería superarlo — recibo del valor semántico."""
    results = {"embedding_model": model_label, "set": "hard", "queries": []}
    hits = []
    corpus_texts = [t for _, t in CORPUS_HARD]
    for query, gold in QUERIES_HARD:
        qv = embedder([query])[0]
        scored = sorted(
            ((cosine(qv, embedder([t])[0]), loc) for loc, t in CORPUS_HARD),
            reverse=True)
        top = scored[0][1]
        hit = top == gold
        hits.append(hit)
        results["queries"].append({"query": query, "gold": gold,
                                   "top1": top, "hit": hit})
    results["recall1"] = sum(hits) / len(hits)
    return results


def bench_fusion(embedder, model_label):
    results = {"embedding_model": model_label, "queries": []}
    rec_locator, rec_rrf = [], []
    for query, gold in QUERIES:
        sem = embedder_ranking(embedder, query)
        struct = lexical_ranking(query)
        # ordenar chunks completos según cada ranking
        by_loc = {loc: EvidenceChunk(text=dict(CORPUS)[loc], locator=loc,
                                     score=1.0) for loc, _ in CORPUS}
        sem_chunks = [by_loc[l] for l in sem]
        struct_chunks = [by_loc[l] for l in struct]
        f_locator = fuse_by_locator(struct_chunks, sem_chunks)
        f_rrf = fuse_rrf([sem_chunks, struct_chunks])
        r_loc = recall_at_3([c.locator for c in f_locator], gold)
        r_rrf = recall_at_3([c.locator for c in f_rrf], gold)
        rec_locator.append(r_loc)
        rec_rrf.append(r_rrf)
        results["queries"].append({"query": query, "gold": gold,
                                   "recall3_locator": r_loc,
                                   "recall3_rrf": r_rrf})
    results["recall3_locator"] = sum(rec_locator) / len(rec_locator)
    results["recall3_rrf"] = sum(rec_rrf) / len(rec_rrf)
    return results


async def bench_degradation_cost():
    """Coste medido de una recuperación con LastIndex sano vs caído."""
    from tests.doubles import FakeBackend, FakeLastIndex, FakeLLM
    from core.rag.engine import LastRAGEngine

    async def timed_run(lastindex):
        engine = LastRAGEngine(FakeBackend(), lastindex, FakeLLM())
        t0 = time.perf_counter()
        await engine.run("¿Qué dice la guía sobre metformina?")
        return (time.perf_counter() - t0) * 1000.0

    healthy_ms = [await timed_run(FakeLastIndex()) for _ in range(5)]

    class BrokenLastIndex(FakeLastIndex):
        async def enrich_chunks(self, chunks):
            raise ConnectionError("NEO4J_UNREACHABLE")
        async def structural_search(self, query, *, top_k=5):
            raise ConnectionError("NEO4J_UNREACHABLE")

    broken_ms, declared = [], False
    for _ in range(5):
        engine = LastRAGEngine(FakeBackend(), BrokenLastIndex(), FakeLLM())
        t0 = time.perf_counter()
        out = await engine.run("¿Qué dice la guía sobre metformina?")
        broken_ms.append((time.perf_counter() - t0) * 1000.0)
        if any(d.get("effect") == "citations_unresolved"
               for d in out["degradations"]):
            declared = True
    return {
        "healthy_p50_ms": round(sorted(healthy_ms)[2], 1),
        "degraded_p50_ms": round(sorted(broken_ms)[2], 1),
        "degradation_declared": declared,
        "note": "coste de la degradación declarada vs pipeline sano (fake "
                "services; mide SOBRECOSTE del manejo fail-closed, no latencia "
                "de servicios reales)",
    }


def main():
    out = {"timestamp": datetime.now().isoformat(timespec="seconds"),
           "corpus": "sintético ES biomédico (10 chunks, 5 queries con gold)",
           "claim_limits": ["NO valida calidad semántica sobre corpus real",
                            "NO valida calidad clínica"]}
    out["hashing_dev"] = bench_fusion(HashingEmbedder(), "local-hash-ngram-256-v1")
    out["hashing_dev_hard"] = bench_hard(HashingEmbedder(), "local-hash-ngram-256-v1")
    try:
        from core.embedding import FastEmbedEmbedder
        emb = FastEmbedEmbedder()
        out["fastembed_real"] = bench_fusion(emb, emb.model_id)
        out["fastembed_real_hard"] = bench_hard(emb, emb.model_id)
    except Exception as exc:
        out["fastembed_real"] = {"error": f"{type(exc).__name__}: {exc}",
                                 "declared_absence": True}
    out["degradation_cost"] = asyncio.run(bench_degradation_cost())
    dest = ROOT / "cierre_brecha" / "BENCHMARK_FUSION.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items()
                      if k in ("hashing_dev_hard", "fastembed_real_hard",
                               "degradation_cost")},
                     indent=2, ensure_ascii=False)[:2500])
    print(f"\nrecibo: {dest}")


if __name__ == "__main__":
    main()
