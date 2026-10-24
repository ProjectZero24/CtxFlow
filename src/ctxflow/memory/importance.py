"""Importance scoring for memory retrieval and retention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
from typing import Iterable

from ctxflow.memory.store import Memory


@dataclass(frozen=True)
class ImportanceWeights:
    task_relevance: float = 0.35
    frequency: float = 0.15
    user_explicitness: float = 0.20
    dependent_count: float = 0.15
    novelty: float = 0.15

    def validate(self) -> None:
        values = (self.task_relevance, self.frequency, self.user_explicitness,
                  self.dependent_count, self.novelty)
        if any(value < 0 or value > 1 for value in values):
            raise ValueError("importance weights must be between 0 and 1")
        if abs(sum(values) - 1.0) > 1e-6:
            raise ValueError("importance weights must sum to 1")


def _normalize(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return min(1.0, max(0.0, value) / maximum)


def score_importance(
    memory: Memory,
    *,
    task_relevance: float = 0.0,
    dependent_count: int = 0,
    max_access_count: int = 1,
    max_dependent_count: int = 1,
    novelty: float = 0.0,
    weights: ImportanceWeights | None = None,
) -> float:
    """Compute and return the configured v1 importance score in [0, 1]."""

    selected = weights or ImportanceWeights()
    selected.validate()
    explicit = 1.0 if memory.memory_type.value == "user_preference" else 0.0
    score = (
        selected.task_relevance * max(0.0, min(1.0, task_relevance))
        + selected.frequency * _normalize(memory.access_count, max_access_count)
        + selected.user_explicitness * explicit
        + selected.dependent_count * _normalize(dependent_count, max_dependent_count)
        + selected.novelty * max(0.0, min(1.0, novelty))
    )
    memory.importance = max(0.0, min(1.0, score))
    return memory.importance
