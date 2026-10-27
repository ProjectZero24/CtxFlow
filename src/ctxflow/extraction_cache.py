"""Deterministic extraction response cache."""

from __future__ import annotations

import hashlib
from typing import Any, Protocol


class ExtractionCache(Protocol):
    """Small cache boundary suitable for an in-memory or persistent backend."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


class InMemoryExtractionCache:
    """Process-local cache used by tests and development ingestion."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._values.get(key)

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value

    def __len__(self) -> int:
        return len(self._values)


def extraction_key(
    operation: str,
    text: str,
    *,
    model_version: str = "default",
    prompt_version: str = "v1",
) -> str:
    """Build a stable key from the event payload and extraction operation."""

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{operation}:{model_version}:{prompt_version}:{digest}"


def event_extraction_key(
    event_hash: str,
    *,
    model_version: str = "default",
    prompt_version: str = "v1",
) -> str:
    """Build the cache key for all atomic memories extracted from an event."""

    return f"atomic:{model_version}:{prompt_version}:{event_hash}"
