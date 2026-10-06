"""
LastRAG v2 — Clientes LLM
==========================
Interfaz comun para generacion de texto. El motor RAG (engine.py) habla contra
`LLMClient` sin conocer si detras hay Gemini, un modelo local en DGX, o un stub.

Implementaciones:
  - GeminiLLM   : Google Gemini via google-genai (cloud / SaaS)
  - LocalLLM    : cliente OpenAI-compatible para endpoint local (vLLM, TGI,
                  Ollama /v1, LM Studio, llama.cpp). Fail-closed (P0.5).
"""

from __future__ import annotations

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional


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


class LocalLLMError(RuntimeError):
    """Fail-closed: el mensaje lleva reason-code, nunca texto de relleno.

    El motor NO captura este error: una generación sin LLM operativo debe
    fallar la consulta, nunca degradarse a una respuesta inventada.
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class LocalLLM(LLMClient):
    """Cliente real para endpoint OpenAI-compatible local (vLLM / TGI / Ollama
    /v1 / LM Studio / llama.cpp). Soporta timeout, retries limitados con
    backoff, streaming opcional, health check y model metadata. El modelo
    (MedGemma/Qwen/ALIA/...) se elige por configuración sin tocar el stack.

    Fail-closed: sin endpoint válido no arranca; sin respuesta válida tras los
    retries lanza LocalLLMError; nunca devuelve texto vacío como éxito ni
    cae a otro proveedor.
    """

    name = "local"
    sends_data_to_cloud = False

    RETRIABLE_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        endpoint: Optional[str] = None,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        backoff: float = 0.5,
        temperature: float = 0.2,
    ):
        self.endpoint = (endpoint or os.getenv("LOCAL_LLM_ENDPOINT")
                         or "http://localhost:8000/v1").rstrip("/")
        self.model = model or os.getenv("LOCAL_LLM_MODEL", "local-model")
        self.api_key = api_key or os.getenv("LOCAL_LLM_API_KEY")
        if not self.endpoint.startswith(("http://", "https://")):
            raise LocalLLMError("INVALID_ENDPOINT", self.endpoint)
        if type(max_retries) is not int or max_retries < 0 or max_retries > 5:
            raise LocalLLMError("INVALID_RETRY_POLICY", f"max_retries={max_retries}")
        if timeout <= 0:
            raise LocalLLMError("INVALID_TIMEOUT", str(timeout))
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.temperature = temperature
        self._client = None

    def _http(self):
        import httpx

        if self._client is None:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=headers)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------
    # Generación (no streaming)
    # ------------------------------------------------------------
    async def generate(
        self, prompt: str, *, max_tokens: int = 8192
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        body = await self._post_with_retries("/chat/completions", payload)
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LocalLLMError("MALFORMED_RESPONSE", json.dumps(body)[:300]) from exc
        if not isinstance(content, str) or not content.strip():
            raise LocalLLMError("EMPTY_RESPONSE", "el endpoint devolvió contenido vacío")
        return content

    # ------------------------------------------------------------
    # Streaming (SSE agregado): mismo contrato que generate
    # ------------------------------------------------------------
    async def generate_stream(
        self, prompt: str, *, max_tokens: int = 8192
    ) -> str:
        chunks: list[str] = []
        async for delta in self.stream_deltas(prompt, max_tokens=max_tokens):
            chunks.append(delta)
        text = "".join(chunks)
        if not text.strip():
            raise LocalLLMError("EMPTY_RESPONSE", "stream sin contenido")
        return text

    async def stream_deltas(
        self, prompt: str, *, max_tokens: int = 8192
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        client = self._http()
        attempt = 0
        while True:
            try:
                async with client.stream(
                    "POST", self.endpoint + "/chat/completions", json=payload
                ) as response:
                    if response.status_code in self.RETRIABLE_STATUS:
                        raise LocalLLMError(
                            "RETRIABLE_HTTP_ERROR", f"status={response.status_code}"
                        )
                    if response.status_code >= 400:
                        raise LocalLLMError(
                            "HTTP_ERROR", f"status={response.status_code}"
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            obj = json.loads(data)
                            delta = obj["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                            continue  # chunk SSE no estándar (keep-alive, uso, etc.)
                        if delta:
                            yield delta
                    return
            except LocalLLMError as exc:
                if exc.reason == "RETRIABLE_HTTP_ERROR" and attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))
                    continue
                raise
            except Exception as exc:  # timeouts, transporte, conexión
                name = type(exc).__name__
                if attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))
                    continue
                raise LocalLLMError("ENDPOINT_UNREACHABLE", name) from exc

    # ------------------------------------------------------------
    # Health check y metadata del modelo (sin retries: diagnóstico)
    # ------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        import httpx

        try:
            response = await self._http().get(
                self.endpoint + "/models", timeout=5.0
            )
        except httpx.HTTPError as exc:
            return {"status": "DOWN", "reason": f"ENDPOINT_UNREACHABLE:{type(exc).__name__}",
                    "endpoint": self.endpoint}
        if response.status_code != 200:
            return {"status": "DOWN", "reason": f"HTTP_{response.status_code}",
                    "endpoint": self.endpoint}
        try:
            models = [m.get("id") for m in response.json().get("data", [])]
        except (json.JSONDecodeError, AttributeError):
            return {"status": "DEGRADED", "reason": "MALFORMED_MODELS_RESPONSE",
                    "endpoint": self.endpoint}
        return {
            "status": "UP",
            "endpoint": self.endpoint,
            "model": self.model,
            "model_available": self.model in models if models else None,
            "models": models,
        }

    async def model_metadata(self) -> dict[str, Any]:
        """Metadatos del modelo servido (id, owned_by, contexto si el endpoint lo expone)."""
        health = await self.health()
        if health["status"] != "UP":
            return {"status": health["status"], "reason": health.get("reason")}
        import httpx

        response = await self._http().get(self.endpoint + "/models", timeout=5.0)
        for item in response.json().get("data", []):
            if item.get("id") == self.model:
                return {"status": "UP", **{k: v for k, v in item.items()
                                           if k in ("id", "object", "owned_by",
                                                    "context_length", "max_model_len",
                                                    "created")}}
        return {"status": "UP", "model": self.model, "note": "MODEL_NOT_LISTED"}

    # ------------------------------------------------------------
    # Interno: POST con retries limitados (429/5xx/transporte)
    # ------------------------------------------------------------
    async def _post_with_retries(self, path: str, payload: dict) -> dict:
        import httpx

        attempt = 0
        while True:
            try:
                response = await self._http().post(self.endpoint + path, json=payload)
            except httpx.HTTPError as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))
                    continue
                raise LocalLLMError("ENDPOINT_UNREACHABLE", type(exc).__name__) from exc
            if response.status_code >= 400:
                if response.status_code in self.RETRIABLE_STATUS and attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))
                    continue
                detail = response.text[:300]
                raise LocalLLMError(
                    "HTTP_ERROR", f"status={response.status_code} body={detail}"
                )
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise LocalLLMError("MALFORMED_RESPONSE", "cuerpo no JSON") from exc
