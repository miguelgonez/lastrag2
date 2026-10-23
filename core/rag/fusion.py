"""
LastRAG v2 — Ola 1: fusión de rankings
======================================
`fuse_rrf` porta el Reciprocal Rank Fusion del control plane lastrag-md
v1.6/v1.8 (allí ya era operativo sobre vector_qdrant + lastindex_structural +
graph_neo4j) al núcleo de la fundación.

Por qué RRF: fusiona N listas por POSICIÓN — score(d) = Σ 1/(k + rank_i(d)) —
sin mezclar escalas numéricas incompatibles (coseno vectorial vs BM25 vs
puntuaciones de grafo). k=60 es la constante estándar del control plane.

La fusión por locator (histórica, prioridad estructural) se PRESERVA como
default; el modo efectivo viaja declarado en `features` de la respuesta.
"""

from __future__ import annotations

from ..backends.base import EvidenceChunk

RRF_K = 60  # constante del control plane v1.6/v1.8


def fuse_rrf(
    rankings: list[list[EvidenceChunk]], k: int = RRF_K
) -> list[EvidenceChunk]:
    """Fusión por rangos recíprocos sobre N rankings ordenados (mejor primero).

    Un documento que aparece en las primeras posiciones de varias listas
    puntúa por consenso; las escalas originales se ignoran por diseño.
    Deduplicación por locator (fallback: prefijo de texto).
    """
    scores: dict[str, float] = {}
    by_key: dict[str, EvidenceChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            key = chunk.locator or chunk.text[:40]
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in by_key:
                by_key[key] = chunk
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    fused: list[EvidenceChunk] = []
    for key, score in ordered:
        chunk = by_key[key]
        fused.append(
            EvidenceChunk(
                text=chunk.text,
                locator=chunk.locator,
                citation=chunk.citation,
                score=score,
                kind=chunk.kind,
            )
        )
    return fused


def fuse_by_locator(
    structural: list[EvidenceChunk], semantic: list[EvidenceChunk]
) -> list[EvidenceChunk]:
    """Fusión histórica: dedupe por locator con prioridad estructural
    (la citación exacta gana). Idéntica a engine._fuse; extraída para
    que el modo de fusión sea explícito y testeable."""
    by_loc: dict[str, EvidenceChunk] = {}
    for c in structural:
        by_loc[c.locator or c.text[:40]] = c
    for c in semantic:
        key = c.locator or c.text[:40]
        if key not in by_loc:
            by_loc[key] = c
    return list(by_loc.values())
