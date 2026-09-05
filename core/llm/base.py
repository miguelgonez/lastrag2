"""
LastRAG v2 — Clientes LLM
==========================
Interfaz comun para generacion de texto. El motor RAG (engine.py) habla contra
`LLMClient` sin conocer si detras hay Gemini, un modelo local en DGX, o un stub.

Implementaciones:
  - GeminiLLM   : Google Gemini via google-genai (cloud / SaaS)
  - LocalLLM    : stub para modelo biomedico local (vLLM/TGI en DGX)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional


class LLMClient(ABC):
    """Contrato que todo cliente de generacion debe cumplir."""

    name: str = "base"

    @abstractmethod
    async def generate(
        self, prompt: str, *, max_tokens: int = 8192
    ) -> str:
        """Genera texto a partir de un prompt. Devuelve string plano."""
        raise NotImplementedError


class GeminiLLM(LLMClient):
    """Cliente de generacion via Google Gemini (google-genai SDK)."""

    name = "gemini"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash",
    ):
        self.model = model
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate(
        self, prompt: str, *, max_tokens: int = 8192
    ) -> str:
        from google.genai import types

        client = self._get_client()
        response = client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=max_tokens,
            ),
        )
        return response.text or ""


class LocalLLM(LLMClient):
    """
    Stub para modelo biomedico local (vLLM / TGI en DGX).
    Pendiente de implementacion real (Fase 2 del roadmap).
    """

    name = "local"

    def __init__(self, endpoint: Optional[str] = None):
        self.endpoint = endpoint or os.getenv("LOCAL_LLM_ENDPOINT", "http://localhost:8000/v1")

    async def generate(
        self, prompt: str, *, max_tokens: int = 8192
    ) -> str:
        # TODO: implementar llamada real al endpoint vLLM/TGI
        raise NotImplementedError(
            f"LocalLLM no implementado aun. "
            f"Endpoint configurado: {self.endpoint}"
        )
