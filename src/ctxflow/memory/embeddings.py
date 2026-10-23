"""Embedding interfaces and a deterministic local embedding implementation."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence


class Embedder(Protocol):
    """Minimal embedding boundary used by ingestion and retrieval."""

    model: str
    dimension: int

    async def embed(self, text: str) -> list[float]: ...


class HashEmbedder:
    """Small deterministic embedder for local development and CI.

    It is not intended to replace a semantic model; it makes the vertical
    slice reproducible when a model server or GPU is unavailable.
    """

    def __init__(self, dimension: int = 128, model: str = "hash-v1") -> None:
        if dimension < 2:
            raise ValueError("dimension must be at least 2")
        self.dimension = dimension
        self.model = model

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in re.findall(r"\w+", text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


async def embed_text(embedder: Embedder, text: str) -> list[float]:
    """Call an async embedder through one stable helper."""

    result = await embedder.embed(text)
    if len(result) != embedder.dimension:
        raise ValueError(
            f"Embedder {embedder.model!r} returned {len(result)} dimensions; "
            f"expected {embedder.dimension}"
        )
    return list(result)
