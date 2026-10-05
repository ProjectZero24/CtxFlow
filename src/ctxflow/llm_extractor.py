"""LLM-powered extractor for CtxFlow.

Implements the :class:`Extractor` interface using an LLM for:
- Semantic keyword/concept extraction (tags)
- Abstractive summarization
- Multi-node synthesis
- Structured claim/method/result extraction from academic text

Uses the same :class:`LLMCallable` protocol as the contradiction
detector, so any LLM backend works.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Protocol, Set

from ctxflow.extractors import Extractor

if TYPE_CHECKING:
    from ctxflow.models import Node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM callable protocol (same as contradiction.py)
# ---------------------------------------------------------------------------

class LLMCallable(Protocol):
    """Protocol for an LLM function: ``(prompt, system) -> str``."""

    def __call__(self, prompt: str, system: str = "") -> str: ...


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_TAG_SYSTEM = (
    "You are a research-text analysis assistant. Extract the most important "
    "concepts, entities, and keywords from the given text. Respond with ONLY "
    "a JSON array of lowercase strings. No markdown fencing. Example: "
    '["machine learning", "transformer", "attention mechanism"]'
)

_SUMMARY_SYSTEM = (
    "You are a research summarization assistant. Produce a concise, "
    "one-to-three sentence summary of the given text. Respond with ONLY "
    "the summary text, no labels or formatting."
)

_MULTI_SUMMARY_SYSTEM = (
    "You are a research synthesis assistant. Given multiple text excerpts, "
    "produce a single concise summary that captures the key information "
    "across all of them. Respond with ONLY the summary text."
)

_CLAIM_SYSTEM = (
    "You are a research-paper analysis assistant. Extract structured claims, "
    "methods, and results from the given text. Respond with ONLY a JSON array "
    "of objects (no markdown fencing). Each object must have:\n"
    '  "type": one of "claim", "method", "result", "finding", "hypothesis"\n'
    '  "text": the extracted statement (one sentence)\n'
    '  "confidence": float 0.0-1.0 indicating how clearly this is stated\n'
    '  "tags": array of lowercase keyword strings for this specific item\n'
    "\nExample:\n"
    '[{"type": "claim", "text": "Attention mechanisms improve translation '
    'quality.", "confidence": 0.9, "tags": ["attention", "translation"]}]'
)


# ---------------------------------------------------------------------------
# LLMExtractor
# ---------------------------------------------------------------------------

class LLMExtractor(Extractor):
    """LLM-powered implementation of the Extractor interface.

    Falls back to simple heuristics if the LLM call fails, so ingestion
    never silently drops content.

    Parameters
    ----------
    llm : LLMCallable
        A callable ``(prompt, system) -> str`` for querying an LLM.
    max_tags : int
        Maximum number of tags to extract per text.
    fallback : Extractor | None
        An optional fallback extractor used when LLM calls fail.
        If ``None``, basic string truncation is used as a last resort.
    """

    def __init__(
        self,
        llm: LLMCallable,
        max_tags: int = 20,
        fallback: Optional[Extractor] = None,
    ) -> None:
        self._llm = llm
        self.max_tags = max_tags
        self._fallback = fallback

    # -- Extractor interface ------------------------------------------------

    def extract_tags(self, text: str) -> Set[str]:
        """Extract semantic tags using the LLM."""
        try:
            raw = self._llm(text, system=_TAG_SYSTEM)
            tags = self._parse_tag_response(raw)
            return set(tags[: self.max_tags])
        except Exception:
            logger.warning("LLM tag extraction failed, using fallback", exc_info=True)
            if self._fallback:
                return self._fallback.extract_tags(text)
            # Bare-minimum fallback: split on whitespace, lowercase, dedup.
            words = text.lower().split()
            return set(w.strip(".,;:!?()[]{}\"'") for w in words[:self.max_tags] if len(w) > 2)

    def summarize(self, text: str) -> str:
        """Produce an abstractive summary using the LLM."""
        try:
            summary = self._llm(text, system=_SUMMARY_SYSTEM)
            return summary.strip()
        except Exception:
            logger.warning("LLM summarization failed, using fallback", exc_info=True)
            if self._fallback:
                return self._fallback.summarize(text)
            # Bare-minimum fallback: first 200 chars.
            return text[:200].strip()

    def summarize_nodes(self, nodes: List[Node]) -> str:
        """Synthesize a summary across multiple nodes using the LLM."""
        if not nodes:
            return ""

        # Build a combined prompt from node summaries/content.
        parts: List[str] = []
        for i, node in enumerate(nodes, 1):
            text = node.summary if node.summary else node.content[:300]
            parts.append(f"[{i}] ({node.node_type}): {text}")
        combined = "\n\n".join(parts)

        try:
            summary = self._llm(combined, system=_MULTI_SUMMARY_SYSTEM)
            return summary.strip()
        except Exception:
            logger.warning("LLM multi-node summary failed, using fallback", exc_info=True)
            if self._fallback:
                return self._fallback.summarize_nodes(nodes)
            return " | ".join(
                n.summary if n.summary else n.content[:100] for n in nodes
            )

    # -- Extended methods (not part of base Extractor) ----------------------

    def extract_claims(self, text: str) -> List[Dict[str, Any]]:
        """Extract structured claims, methods, and results from academic text.

        This method goes beyond the base Extractor interface. It is used
        by the Paper Reader skill to turn a paper section into typed
        graph nodes.

        Parameters
        ----------
        text : str
            Academic text (paper section, abstract, etc.).

        Returns
        -------
        list[dict]
            Each dict has keys ``type``, ``text``, ``confidence``, ``tags``.
        """
        try:
            raw = self._llm(text, system=_CLAIM_SYSTEM)
            claims = self._parse_claims_response(raw)
            return claims
        except Exception:
            logger.warning("LLM claim extraction failed", exc_info=True)
            # Fallback: treat the whole text as a single claim.
            return [{
                "type": "claim",
                "text": text[:500],
                "confidence": 0.5,
                "tags": list(self.extract_tags(text))[:5],
            }]

    # -- Parsing helpers ----------------------------------------------------

    @staticmethod
    def _parse_tag_response(raw: str) -> List[str]:
        """Parse an LLM tag extraction response."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")
        return [str(t).lower().strip() for t in parsed if t]

    @staticmethod
    def _parse_claims_response(raw: str) -> List[Dict[str, Any]]:
        """Parse an LLM claim extraction response."""
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

        valid_types = {"claim", "method", "result", "finding", "hypothesis"}
        cleaned: List[Dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "claim")).lower()
            if item_type not in valid_types:
                item_type = "claim"
            cleaned.append({
                "type": item_type,
                "text": str(item.get("text", "")),
                "confidence": max(0.0, min(1.0, float(item.get("confidence", 0.5)))),
                "tags": [str(t).lower() for t in item.get("tags", [])],
            })

        return cleaned
