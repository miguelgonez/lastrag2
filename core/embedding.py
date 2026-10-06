"""
LastRAG v2 — Embedders locales
==============================
Embedders reales (no mocks) ejecutables sin GPU ni descargas pesadas.

`HashingEmbedder` es un embedder de DESARROLLO, declarado como tal en cada
punto y respuesta (`embedding_model`). NO es semántico: proyecta n-gramas de
tokens a un espacio fijo por hash determinista, con normalización L2. Sirve
para ejercitar el camino real Qdrant (vectores, persistencia, filtros, top-k)
mientras el embedder biomédico del despliegue (DGX) no esté conectado.

Producción DEBE sustituirlo (inyectable por constructor) y actualizar la
etiqueta `embedding_model`; el identificador viaja en el payload de Qdrant
para que ninguna medición atribuya a este embedder calidad semántica.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Sequence


class HashingEmbedder:
    """N-gramas de tokens → vector denso 256d determinista, L2-normalizado."""

    model_id = "local-hash-ngram-256-v1"
    dim = 256

    def __init__(self, dim: int = 256):
        self.dim = dim

    @staticmethod
    def _tokens(text: str) -> list[str]:
        norm = "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                       if not unicodedata.combining(c))
        return re.findall(r"[a-z0-9]{3,}", norm)

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = self._tokens(text)
        features = list(tokens)
        features += [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dim
            vec[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0  # texto sin tokens: vector canónico, nunca cero
            return vec
        return [v / norm for v in vec]

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]
