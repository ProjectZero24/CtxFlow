"""Lazy tokenizer adapters for memory token-count accounting."""

from __future__ import annotations

import re
from typing import Protocol


class TokenizerAdapter(Protocol):
    tokenizer_id: str

    def count(self, text: str) -> int: ...


class SimpleTokenizer:
    """Deterministic fallback tokenizer with no external dependency."""

    tokenizer_id = "simple-v1"

    def count(self, text: str) -> int:
        return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def count_tokens(memory: object, tokenizer: TokenizerAdapter) -> int:
    """Compute and cache a count on a memory-like object."""

    counts = getattr(memory, "token_counts")
    if tokenizer.tokenizer_id not in counts:
        counts[tokenizer.tokenizer_id] = tokenizer.count(getattr(memory, "text"))
    return counts[tokenizer.tokenizer_id]
