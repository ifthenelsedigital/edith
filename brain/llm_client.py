"""
EDITH Brain — Ollama LLM Client

Async client for communicating with the local Ollama instance.
Uses the OpenAI-compatible API for portability.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from config import get_settings

logger = logging.getLogger("edith.brain.llm")


class LLMClient:
    """Async client for Ollama's OpenAI-compatible API."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self._client: httpx.AsyncClient | None = None
        self._supports_tools: bool | None = None  # None = not yet probed

    @property
    def supports_tools(self) -> bool:
        """Whether the current model supports tool calls.

        Returns True if not yet probed (optimistic default).
        Call probe_tool_support() at startup to populate this.
        """
        if self._supports_tools is None:
            return True  # optimistic until probed
        return self._supports_tools

    async def probe_tool_support(self) -> bool:
        """Send a lightweight test request with a dummy tool to detect support.

        Caches the result in _supports_tools so subsequent calls are free.
        """
        if self._supports_tools is not None:
            return self._supports_tools

        dummy_tool = [{
            "type": "function",
            "function": {
                "name": "_probe",
                "description": "Probe for tool support.",
                "parameters": {"type": "object", "properties": {}},
            },
        }]

        try:
            resp = await self.client.post("/api/chat", json={
                "model": self.model,
                "messages": [{"role": "user", "content": "hi"}],
                "tools": dummy_tool,
                "stream": False,
                "options": {"num_predict": 1},
            })
            resp.raise_for_status()
            self._supports_tools = True
            logger.info(f"Tool support probe: model '{self.model}' SUPPORTS tools")
        except httpx.HTTPStatusError as e:
            error_text = (e.response.text or "").lower()
            if e.response.status_code == 400 and "does not support tools" in error_text:
                self._supports_tools = False
                logger.info(f"Tool support probe: model '{self.model}' does NOT support tools")
            else:
                # Some other error — assume tools are supported to avoid
                # disabling them unnecessarily.
                self._supports_tools = True
                logger.warning(
                    f"Tool support probe got unexpected error {e.response.status_code}; "
                    f"assuming tools are supported"
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            # Ollama unreachable — leave as None (will re-probe later)
            logger.warning(f"Tool support probe failed (network): {e}")
            self._supports_tools = True  # optimistic

        return self._supports_tools

    def _sanitize_messages_for_non_tool_model(self, messages: list[dict]) -> list[dict]:
        """Remove tool-specific content from a conversation so it can be sent to models without tool support."""
        cleaned: list[dict] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue

            role = msg.get("role")
            if role == "tool":
                continue

            cleaned_msg = dict(msg)
            if role == "assistant":
                cleaned_msg.pop("tool_calls", None)
                if not cleaned_msg.get("content"):
                    cleaned_msg["content"] = ""

            cleaned.append(cleaned_msg)

        return cleaned

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def health_check(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            resp = await self.client.get("/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Check if our model (or a variant of it) is available
                model_base = self.model.split(":")[0]
                available = any(model_base in m for m in models)
                if not available:
                    logger.warning(
                        f"Model '{self.model}' not found. Available: {models}"
                    )
                    logger.warning(f"Run: ollama pull {self.model}")
                    return False
                return True
            return False
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            logger.error(f"Cannot connect to Ollama at {self.base_url}: {e}")
            return False

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
        temperature: float = 0.7,
    ) -> dict:
        """
        Send a chat completion request to Ollama.

        Args:
            messages: List of {"role": "...", "content": "..."} dicts
            tools: Optional list of tool schemas for function calling
            stream: Whether to stream the response
            temperature: Sampling temperature

        Returns:
            The full response dict from Ollama
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
            },
        }

        if tools:
            payload["tools"] = tools

        try:
            resp = await self.client.post("/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            logger.error("LLM request timed out")
            return {"message": {"role": "assistant", "content": "I'm sorry, the request timed out. Please try again."}}
        except httpx.HTTPStatusError as e:
            error_text = (e.response.text or "").lower()

            # Model not found (404)
            if e.response.status_code == 404 and "not found" in error_text:
                logger.error(
                    f"Model '{self.model}' not found in Ollama. "
                    f"Run: ollama pull {self.model}"
                )
                return {"message": {"role": "assistant", "content": f"Model '{self.model}' is not installed in Ollama. Run `ollama pull {self.model}` in your terminal to download it."}}

            # Model doesn't support tools — retry without them
            if e.response.status_code == 400 and "does not support tools" in error_text:
                self._supports_tools = False
                logger.warning(
                    f"Model '{self.model}' does not support tools — retrying without tools"
                )
                payload.pop("tools", None)
                payload["messages"] = self._sanitize_messages_for_non_tool_model(payload["messages"])
                try:
                    resp = await self.client.post("/api/chat", json=payload)
                    resp.raise_for_status()
                    return resp.json()
                except Exception as retry_err:
                    logger.error(f"LLM retry without tools also failed: {retry_err}")
            else:
                logger.error(f"LLM HTTP error: {e.response.status_code} — {e.response.text}")
            return {"message": {"role": "assistant", "content": "I'm having trouble reaching the configured model right now. Please try again in a moment."}}
        except httpx.ConnectError:
            logger.error("Cannot connect to Ollama")
            return {"message": {"role": "assistant", "content": "I can't reach my brain (Ollama). Please make sure it's running with `ollama serve`."}}

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """
        Stream a chat completion response token by token.

        Yields text chunks as they arrive.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": "10m",
            "options": {
                "temperature": temperature,
                "num_predict": 96,
            },
        }

        if tools:
            payload["tools"] = tools

        try:
            async with self.client.stream(
                "POST", "/api/chat", json=payload, timeout=120.0
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            # Check if this chunk has tool calls
                            tool_calls = data.get("message", {}).get("tool_calls")
                            if tool_calls:
                                # Yield a special marker for tool calls
                                yield f"\n__TOOL_CALLS__:{json.dumps(tool_calls)}"
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            yield f"Error: Cannot reach Ollama — {e}"

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.debug("LLM client closed")


# ── Singleton Instance ──
llm_client = LLMClient()
