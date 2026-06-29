"""LLM client wrapper - OpenAI-compatible, configurable via base_url + api_key."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import AsyncIterator, Iterator

from openai import OpenAI

from config import ModelConfig

logger = logging.getLogger(__name__)

# Newer "thinking"/reasoning model families deprecate the `temperature` parameter;
# sending it makes such backends (e.g. AWS Bedrock) reject the request with 400.
# Detect by a loose name hint so we simply omit it for those models while keeping
# it everywhere else. Add tokens here as new thinking models appear.
_THINKING_MODEL_HINTS: tuple[str, ...] = (
    "opus-4", "opus4",        # Claude Opus 4.x (extended-thinking)
    "o1-", "o3-", "o4-",      # OpenAI o-series reasoning models
    "gpt-5", "reasoning", "thinking",
)


def supports_temperature(model_name: str | None) -> bool:
    """Return False for models that reject the temperature field."""
    m = (model_name or "").lower()
    return not any(h in m for h in _THINKING_MODEL_HINTS)


class LLMClient:
    """Thin wrapper around OpenAI-compatible chat completions."""

    def __init__(self, config: ModelConfig | None = None):
        self.config = config or ModelConfig()
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=120,
            )
        return self._client

    def reconfigure(self, **kwargs):
        """Update model config at runtime (e.g. user picks a new model)."""
        changed = False
        for k, v in kwargs.items():
            if v is None:
                continue
            if hasattr(self.config, k) and getattr(self.config, k) != v:
                setattr(self.config, k, v)
                changed = True
        if changed:
            self._client = None  # force reconnect with new settings
        return self.config

    def list_models(self) -> list[str]:
        """List available model IDs from the model server (OpenAI-compatible /models)."""
        try:
            resp = self.client.models.list()
            return [m.id for m in resp.data]
        except Exception as e:
            logger.warning(f"Failed to list models from server: {e}")
            return []

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        stop: list[str] | None = None,
    ) -> str:
        """Synchronous chat completion. Returns the assistant message content."""
        params: dict = {
            "model": self.config.model_name,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
        }
        # Thinking/reasoning models reject `temperature`; only send it when supported.
        if supports_temperature(self.config.model_name):
            params["temperature"] = temperature if temperature is not None else self.config.temperature
        if response_format:
            params["response_format"] = response_format
        if stop:
            params["stop"] = stop

        resp = self.client.chat.completions.create(**params)
        return resp.choices[0].message.content or ""

    def chat_json(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
    ) -> dict:
        """Chat completion expecting JSON output. Returns parsed dict."""
        content = self.chat(
            messages,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Fallback: try to extract JSON from the response
            import re
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                return json.loads(match.group())
            raise ValueError(f"Failed to parse JSON from LLM response: {content[:200]}")

    def stream(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """Streaming chat completion. Yields content chunks."""
        params: dict = {
            "model": self.config.model_name,
            "messages": messages,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "stream": True,
        }
        if supports_temperature(self.config.model_name):
            params["temperature"] = temperature if temperature is not None else self.config.temperature
        for chunk in self.client.chat.completions.create(**params):
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


# Global instance, reconfigured via API
llm_client = LLMClient()
