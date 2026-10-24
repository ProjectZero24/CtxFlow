"""Duplicate detection for memory ingestion."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from ctxflow.memory.store import Memory, Relation

DEFAULT_DUPLICATE_THRESHOLD = 0.95
ANN_CANDIDATE_LIMIT = 5


@dataclass(frozen=True)
class DuplicateMatch:
    memory_id: str
    similarity: float


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denominator if denominator else 0.0


def similarity(candidate: Memory, existing: Memory) -> float:
    """Return dense cosine similarity for ANN deduplication."""

    return _cosine(candidate.embedding, existing.embedding)


def find_duplicates(
    candidate: Memory,
    existing: Iterable[Memory],
    *,
    threshold: float = DEFAULT_DUPLICATE_THRESHOLD,
    same_type: bool = True,
) -> list[DuplicateMatch]:
    """Find existing memories at or above the duplicate threshold."""

    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    matches = [
        DuplicateMatch(memory.id, similarity(candidate, memory))
        for memory in existing
        if memory.id != candidate.id and similarity(candidate, memory) > threshold
        and (not same_type or memory.memory_type == candidate.memory_type)
    ]
    return sorted(matches, key=lambda item: (-item.similarity, item.memory_id))


def duplicate_edge(candidate_id: str, match: DuplicateMatch) -> tuple[str, str, Relation]:
    """Return the canonical edge representation for a duplicate match."""

    return candidate_id, match.memory_id, Relation.DUPLICATE_OF
