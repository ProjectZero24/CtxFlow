"""Embedding interfaces and local embedding implementations."""

from __future__ import annotations

import math
import threading
from typing import Any, Protocol, Sequence

BGE_MODEL_NAME = "BAAI/bge-small-en-v1.5"
BGE_EMBEDDING_DIMENSION = 384


class Embedder(Protocol):
    """Minimal embedding boundary used by ingestion and retrieval."""

    model: str
    dimension: int

    async def embed(self, text: str) -> list[float]: ...

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Small deterministic embedder for local development and CI.

    It is not intended to replace a semantic model; it makes the vertical
    slice reproducible when a model server or GPU is unavailable.
    """

    def __init__(self, dimension: int = 384, model: str = "hash-v1") -> None:
        if dimension < 2:
            raise ValueError("dimension must be at least 2")
        self.dimension = dimension
        self.model = model

    async def embed(self, text: str) -> list[float]:
        from hashlib import blake2b
        import re

        vector = [0.0] * self.dimension
        for token in re.findall(r"\w+", text.lower()):
            digest = blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


class LocalBGEEmbedder:
    """Async local BGE Small embedder with serialized off-thread inference."""

    model = BGE_MODEL_NAME
    dimension = BGE_EMBEDDING_DIMENSION

    def __init__(self, *, model_name: str = BGE_MODEL_NAME, **model_kwargs: Any) -> None:
        if model_name != BGE_MODEL_NAME:
            raise ValueError(f"Only {BGE_MODEL_NAME!r} is supported")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Local BGE embeddings require the 'sentence-transformers' package"
            ) from error
        try:
            self._model = SentenceTransformer(model_name, **model_kwargs)
        except Exception as error:
            raise RuntimeError(
                f"Failed to load local embedding model {model_name!r}; "
                "download it before starting CtxFlow"
            ) from error
        get_dimension = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        actual_dimension = get_dimension()
        if actual_dimension != self.dimension:
            raise RuntimeError(
                f"Local model {model_name!r} reports {actual_dimension} dimensions; "
                f"expected {self.dimension}"
            )
        self.model = model_name
        self._inference_lock = threading.Lock()

    async def embed(self, text: str) -> list[float]:
        vectors = await self.embed_many([text])
        return vectors[0]

    async def embed_query(self, text: str) -> list[float]:
        return await self.embed(text)

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("BGE embedding input texts must be non-empty strings")
        import asyncio

        return await asyncio.to_thread(self._encode, list(texts))

    def _encode(self, texts: list[str]) -> list[list[float]]:
        with self._inference_lock:
            encoded = self._model.encode(
                texts,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        rows = encoded.tolist() if hasattr(encoded, "tolist") else encoded
        if len(rows) != len(texts):
            raise RuntimeError("Local BGE model returned an invalid batch size")
        vectors: list[list[float]] = []
        for row in rows:
            values = [float(value) for value in row]
            if len(values) != self.dimension:
                raise ValueError(
                    f"Local BGE embedding returned {len(values)} dimensions; "
                    f"expected {self.dimension}"
                )
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Local BGE embedding returned non-finite values")
            vectors.append(values)
        return vectors


async def embed_text(embedder: Embedder, text: str) -> list[float]:
    """Call an async embedder through one stable helper."""

    result = await embedder.embed(text)
    if len(result) != embedder.dimension:
        raise ValueError(
            f"Embedder {embedder.model!r} returned {len(result)} dimensions; "
            f"expected {embedder.dimension}"
        )
    return list(result)


async def embed_texts(embedder: Embedder, texts: Sequence[str]) -> list[list[float]]:
    """Embed a batch while preserving the shared dimension contract."""

    embed_many = getattr(embedder, "embed_many", None)
    results = (
        await embed_many(texts)
        if embed_many is not None
        else [await embedder.embed(text) for text in texts]
    )
    if len(results) != len(texts):
        raise ValueError(f"Embedder {embedder.model!r} returned an invalid batch size")
    for result in results:
        if len(result) != embedder.dimension:
            raise ValueError(
                f"Embedder {embedder.model!r} returned {len(result)} dimensions; "
                f"expected {embedder.dimension}"
            )
        if not all(math.isfinite(float(value)) for value in result):
            raise ValueError(f"Embedder {embedder.model!r} returned non-finite values")
    return [list(result) for result in results]


async def embed_query(embedder: Embedder, text: str) -> list[float]:
    """Embed a retrieval query, using a provider-specific query mode when available."""

    query_embed = getattr(embedder, "embed_query", None)
    result = await query_embed(text) if query_embed is not None else await embedder.embed(text)
    if len(result) != embedder.dimension:
        raise ValueError(
            f"Embedder {embedder.model!r} returned {len(result)} dimensions; "
            f"expected {embedder.dimension}"
        )
    return list(result)
