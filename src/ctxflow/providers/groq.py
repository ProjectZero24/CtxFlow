"""Groq adapter for structured extraction and graph edge proposals."""

from __future__ import annotations

import os
import logging
from typing import Any

from dotenv import dotenv_values

from ctxflow.llm_extractor import LLMExtractor
from ctxflow.memory.edge_proposer import LLMEdgeProposer

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_CHAT_MODEL = "openai/gpt-oss-20b"
_LOGGER = logging.getLogger(__name__)


class GroqEmptyContentError(RuntimeError):
    """Raised when Groq returns a completion choice without message content."""


def _api_key(api_key: str | None) -> str:
    key = api_key or os.getenv("GROQ_API_KEY") or dotenv_values().get("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY must be set to use Groq models")
    return key


class GroqLLM:
    """Synchronous OpenAI-compatible callable for CtxFlow LLM tasks."""

    model = GROQ_CHAT_MODEL

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = GROQ_BASE_URL,
        model: str = GROQ_CHAT_MODEL,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError(
                "The Groq adapter requires the 'openai' package"
            ) from error
        self._client = OpenAI(api_key=_api_key(api_key), base_url=base_url)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def __call__(self, prompt: str, system: str = "") -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        choices = getattr(response, "choices", [])
        choice = choices[0] if choices else None
        content = getattr(getattr(choice, "message", None), "content", None)
        if not isinstance(content, str) or not content.strip():
            finish_reason = getattr(choice, "finish_reason", None)
            usage = getattr(response, "usage", None)
            usage_summary = {
                name: getattr(usage, name, None)
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            } if usage is not None else None
            _LOGGER.error(
                "Groq returned empty chat content model=%s finish_reason=%s usage=%s response_id=%s",
                self.model,
                finish_reason,
                usage_summary,
                getattr(response, "id", None),
            )
            raise GroqEmptyContentError(
                "Groq chat completion returned empty content "
                f"(model={self.model}, finish_reason={finish_reason})"
            )
        return content


def create_groq_extractor(
    *,
    api_key: str | None = None,
    cache: Any | None = None,
    extraction_retries: int = 2,
) -> LLMExtractor:
    """Build an extractor backed by the configured Groq chat model."""

    return LLMExtractor(
        GroqLLM(api_key=api_key),
        cache=cache,
        extraction_retries=extraction_retries,
    )


def create_groq_edge_proposer(
    *,
    api_key: str | None = None,
    threshold: float = 0.7,
) -> LLMEdgeProposer:
    """Build an edge proposer backed by the configured Groq chat model."""

    return LLMEdgeProposer(GroqLLM(api_key=api_key), threshold=threshold)
