"""Pluggable text extraction interface and default rule-based implementation.

The Extractor is used in two places:
1. During ingestion — to extract tags and generate summaries from raw content.
2. During querying — to extract tags from the query string (same vocabulary).
3. During prune-compaction — to summarize a cluster of stale nodes.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Set

if TYPE_CHECKING:
    from ctxflow.models import Node


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class Extractor(ABC):
    """Abstract base for content extraction.

    Subclass this to plug in LLM-based extraction, spaCy NER, or any
    custom pipeline. The framework only calls these three methods.
    """

    @abstractmethod
    def extract_tags(self, text: str) -> Set[str]:
        """Extract a set of free-form string tags from *text*."""

    @abstractmethod
    def summarize(self, text: str) -> str:
        """Produce a short summary of *text*."""

    @abstractmethod
    def summarize_nodes(self, nodes: List[Node]) -> str:
        """Produce a single summary that captures the key information
        across multiple *nodes* (used during prune-compaction)."""


# ---------------------------------------------------------------------------
# Default rule-based extractor
# ---------------------------------------------------------------------------

# Precompiled patterns for the default extractor.
_WORD_RE = re.compile(r"\b[a-zA-Z]{3,}\b")

# Common English stop words (kept small to avoid external deps).
_STOP_WORDS: Set[str] = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "some", "them",
    "than", "its", "over", "such", "that", "this", "with", "will", "each",
    "make", "like", "from", "just", "into", "about", "could", "would",
    "there", "their", "what", "when", "which", "where", "these", "those",
    "then", "also", "after", "before", "other", "more", "very", "only",
    "does", "did", "how", "may", "should", "most", "being", "any", "both",
    "between", "through", "during", "because", "while", "here",
}

# Maximum number of sentences kept for a summary.
_MAX_SUMMARY_SENTENCES = 3

# Sentence boundary pattern (handles '. ', '! ', '? ' and end-of-string).
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class DefaultExtractor(Extractor):
    """Zero-dependency, rule-based extractor.

    * **Tag extraction**: lowercased words (≥ 3 chars) minus stop words.
    * **Summarization**: first N sentences of the input text.
    * **Node compaction**: concatenation of existing node summaries.
    """

    def __init__(
        self,
        max_tags: int = 20,
        max_summary_sentences: int = _MAX_SUMMARY_SENTENCES,
        stop_words: Set[str] | None = None,
    ) -> None:
        self.max_tags = max_tags
        self.max_summary_sentences = max_summary_sentences
        self.stop_words = stop_words if stop_words is not None else _STOP_WORDS

    # -- Extractor interface ------------------------------------------------

    def extract_tags(self, text: str) -> Set[str]:
        """Extract lowercased keywords, excluding stop words."""
        words = _WORD_RE.findall(text.lower())
        filtered = [w for w in words if w not in self.stop_words]
        # Return the most frequent words, capped at max_tags.
        freq: dict[str, int] = {}
        for w in filtered:
            freq[w] = freq.get(w, 0) + 1
        ranked = sorted(freq, key=lambda w: freq[w], reverse=True)
        return set(ranked[: self.max_tags])

    def summarize(self, text: str) -> str:
        """Return the first few sentences of *text*."""
        text = text.strip()
        if not text:
            return ""
        sentences = _SENTENCE_RE.split(text)
        kept = sentences[: self.max_summary_sentences]
        return " ".join(kept).strip()

    def summarize_nodes(self, nodes: List[Node]) -> str:
        """Concatenate existing node summaries (fallback when no LLM is available)."""
        parts: list[str] = []
        for n in nodes:
            piece = n.summary if n.summary else self.summarize(n.content)
            if piece:
                parts.append(piece)
        return " | ".join(parts) if parts else ""
