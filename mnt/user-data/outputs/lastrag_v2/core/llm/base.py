"""
LastRAG v2 — Abstraccion de LLM de generacion
=============================================
El motor habla contra `LLMClient`. En cloud -> Gemini; en DGX -> modelo
biomedico local (MedGemma u otro) implementando la misma interfaz.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional


class LLMClient(ABC):
    name: str = "base"
    runs_locally: bool = False

    @abstractmethod
    async def generate(self, prompt: str, *, max_tokens: int = 8192) -> str:
        raise NotImplementedError


class GeminiLLM(LLMClient):
    name = "gemini"
    runs_locally = False

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        from google import genai
        self.model = model
        key = api_key or os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=key) if key else None

    async def generate(self, prompt: str, *, max_tokens: int = 8192) -> str:
        if not self.client:
            return "Error: cliente Gemini no inicializado."
        from google.genai import types
        try:
            # SDK async para no bloquear el event loop.
            resp = await self.client.aio.models.generate_content(
                model=self.model,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    temperature=0.1, max_output_tokens=max_tokens
                ),
            )
            return resp.text or "El modelo no produjo respuesta."
        except Exception as e:
            return f"Error al generar respuesta: {e}"


class LocalLLM(LLMClient):
    """
    Stub para el despliegue DGX. Implementar con el runtime local
    (vLLM/TGI/transformers) del modelo biomedico. runs_locally=True permite
    al gate PHI autorizar inferencia sobre datos reales.
    """
    name = "local"
    runs_locally = True

    def __init__(self, endpoint: str = os.getenv("LOCAL_LLM_ENDPOINT", "")):
        self.endpoint = endpoint

    async def generate(self, prompt: str, *, max_tokens: int = 8192) -> str:
        raise NotImplementedError(
            "LocalLLM: conectar al runtime del DGX (vLLM/TGI). "
            "Pendiente en la fase de despliegue Nexthealth-OS."
        )
