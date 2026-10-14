"""
LastRAG v2 — Ola 1: Reranking clínico (separar recall de juicio fino)
=====================================================================
Compromiso s6 del deck: stage 2 de refinado de la señal. Un reranker
determinista por señales clínicas auditables (tipo de estudio, población,
actualidad, autoridad) + un cross-encoder ONNX REAL opcional (fastembed),
etiquetado con su límite (ms-marco-MiniLM entrenado en inglés; calidad ES
no validada).

Cada decisión de reordenado lleva `reasons[]` auditables. Sin reranker
configurado, el motor NO reordena y lo declara — jamás degradación silenciosa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..backends.base import EvidenceChunk

# Jerarquía de evidencia (determinista, portable a config)
STUDY_HIERARCHY: dict[str, float] = {
    "meta-analisis": 5.0, "meta-análisis": 5.0, "metaanalisis": 5.0,
    "revision sistematica": 4.5, "revisión sistemática": 4.5,
    "ensayo aleatorizado": 4.0, "aleatorizado": 3.8, "aleatorizada": 3.8,
    "double ciego": 3.8, "doble ciego": 3.8, "ensayo clinico": 3.2,
    "ensayo clínico": 3.2, "cohorte": 2.4, "longitudinal": 2.2,
    "caso": 1.2, "casos y controles": 1.6, "observacional": 1.4,
    "in vitro": 0.8, "preclinico": 0.8, "preclínico": 0.8,
}
AUTHORITY_MARKERS = ("guia clinica", "guía clínica", "guia de practica",
                     "guía de práctica", "oms", "organizacion mundial",
                     "organización mundial", "ministerio de sanidad",
                     "sociedad espanola", "sociedad española", "consenso")
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")


def _content_terms(text: str) -> set[str]:
    return set(re.findall(r"[a-záéíóúüñ]{4,}", text.lower()))


@dataclass
class RerankResult:
    ranked: list[EvidenceChunk]
    model: str
    reasons: dict[str, list[str]] = field(default_factory=dict)  # locator -> reasons


class ClinicalReranker:
    """Reranking determinista por señales clínicas. Cada fragmento recibe un
    bonus explicable; el orden final es por score total. model declarado."""

    model = "clinical-filters-deterministic-v1"

    def __init__(self, now_year: int = 2026):
        self.now_year = now_year

    def rerank(self, query: str, chunks: list[EvidenceChunk]) -> RerankResult:
        query_terms = _content_terms(query)
        scored: list[tuple[float, EvidenceChunk, list[str]]] = []
        for c in chunks:
            text_l = c.text.lower()
            score = c.score
            reasons: list[str] = []
            study = max(((v, k) for k, v in STUDY_HIERARCHY.items() if k in text_l),
                        default=None)
            if study:
                score += study[0]
                reasons.append(f"estudio:{study[1]}(+{study[0]})")
            years = [int(y) for y in _YEAR_RE.findall(c.text)]
            if years:
                age = max(0, self.now_year - max(years))
                bonus = max(0.0, 2.0 - 0.2 * age)
                if bonus > 0:
                    score += bonus
                    reasons.append(f"actualidad:{max(years)}(+{bonus:.1f})")
            auth = next((a for a in AUTHORITY_MARKERS if a in text_l), None)
            if auth:
                score += 1.5
                reasons.append(f"autoridad:{auth}(+1.5)")
            if query_terms:
                overlap = len(query_terms & _content_terms(c.text))
                if overlap:
                    score += min(2.0, 0.4 * overlap)
                    reasons.append(f"poblacion/consulta:{overlap} términos(+{min(2.0, 0.4*overlap):.1f})")
            scored.append((score, c, reasons))
        scored.sort(key=lambda t: t[0], reverse=True)
        ranked = [c for _, c, _ in scored]
        reasons = {c.locator: r for _, c, r in scored if r}
        return RerankResult(ranked, self.model, reasons)


class CrossEncoderReranker:
    """Cross-encoder REAL (ONNX local vía fastembed). Descarga el modelo en el
    primer uso (~90 MB). Etiqueta honesta: entrenado en inglés (ms-marco);
    la calidad en español no se reclama sin benchmark."""

    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2",
                 fallback: Optional[ClinicalReranker] = None):
        self.model_name = model_name
        self.fallback = fallback or ClinicalReranker()
        self._model = None

    @property
    def model(self) -> str:
        return f"crossencoder-onnx:{self.model_name}+{self.fallback.model}"

    def _ensure_model(self):
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._model = TextCrossEncoder(model_name=self.model_name)

    def rerank(self, query: str, chunks: list[EvidenceChunk]) -> RerankResult:
        if not chunks:
            return RerankResult([], self.model, {})
        try:
            self._ensure_model()
            # API fastembed vigente: rerank(query, documents) -> scores
            scores = list(self._model.rerank(query, [c.text[:1800] for c in chunks]))
        except Exception as exc:
            # El fallo del cross-encoder NUNCA es silencioso: cae al
            # determinista declarándolo en el resultado.
            base = self.fallback.rerank(query, chunks)
            return RerankResult(
                base.ranked, f"{self.model}::FALLBACK_{type(exc).__name__}",
                base.reasons)
        base = self.fallback.rerank(query, chunks)  # señales clínicas como base
        order = sorted(range(len(chunks)),
                       key=lambda i: scores[i], reverse=True)
        ranked = [chunks[i] for i in order]
        reasons = {c.locator: [f"crossencoder:{s:.3f}"] for c, s in zip(chunks, scores)}
        for c in base.ranked:
            reasons.setdefault(c.locator, base.reasons.get(c.locator, []))
        return RerankResult(ranked, self.model, reasons)
