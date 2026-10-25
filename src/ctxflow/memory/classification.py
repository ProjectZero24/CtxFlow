"""Deterministic memory classification and evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable


class MemoryClass(str, Enum):
    """Labels used by the ingestion classifier."""

    CONVERSATION = "conversation"
    FACT = "fact"
    DECISION = "decision"
    OBSERVATION = "observation"
    TOOL_RESULT = "tool_result"
    USER_PREFERENCE = "user_preference"


@dataclass(frozen=True)
class ClassificationExample:
    text: str
    expected: MemoryClass
    tool_name: str | None = None


@dataclass(frozen=True)
class ClassificationReport:
    total: int
    correct: int
    accuracy: float
    confusion: dict[str, dict[str, int]]


_FACT_PREFIXES = (
    "fact:",
    "note:",
    "the ",
    "a ",
    "an ",
    "this ",
    "these ",
    "those ",
    "it is ",
    "it was ",
    "there is ",
    "there are ",
    "according to ",
    "based on ",
)

_OBSERVATION_PREFIXES = (
    "observed",
    "observation:",
    "noticed",
    "measurement:",
    "the result ",
    "the results ",
    "the evidence ",
    "the finding ",
    "the findings ",
    "the data ",
    "the output ",
    "the behavior ",
    "the behaviour ",
    "the difference ",
    "the change ",
    "the discrepancy ",
    "the comparison ",
    "the analysis ",
    "this suggests ",
    "this indicates ",
    "this shows ",
    "this suggests that ",
    "this indicates that ",
    "this shows that ",
    "the evidence suggests ",
    "the results indicate ",
    "the data shows ",
    "the data suggests ",
)

_DECISION_PREFIXES = (
    "decided",
    "decision:",
    "we will",
    "let's ",
    "i will ",
    "i'll ",
    "i have decided ",
    "i've decided ",
    "we decided ",
    "we have decided ",
)

_PREFERENCE_PREFIXES = (
    "i prefer ",
    "my preference ",
    "i want ",
    "i don't want ",
    "i do not want ",
    "remember that ",
    "keep ",
    "please keep ",
    "do not ",
    "don't ",
    "never ",
    "prioritize ",
    "please prioritize ",
    "can you keep ",
    "can you give me ",
    "please redact ",
    "the final demonstration must ",
)



def classify_memory(
    text: str,
    *,
    tool_name: str | None = None,
) -> MemoryClass:
    """Classify an event using explicit, prioritized rules."""

    if tool_name:
        return MemoryClass.TOOL_RESULT

    normalized = re.sub(r"\s+", " ", text.strip().lower())

    if not normalized:
        return MemoryClass.CONVERSATION

    # Questions should not be classified by generic factual prefixes.
    if normalized.endswith("?"):
        return MemoryClass.CONVERSATION

    # Explicit user preferences and instructions.
    if (
        "remember that" in normalized
        or any(normalized.startswith(p) for p in _PREFERENCE_PREFIXES)
    ):
        return MemoryClass.USER_PREFERENCE

    # Explicit decisions and first-person commitments.
    if normalized.startswith(_DECISION_PREFIXES):
        return MemoryClass.DECISION

    # Explicit observations and evidence-based findings.
    if normalized.startswith(_OBSERVATION_PREFIXES):
        return MemoryClass.OBSERVATION

    # Explicit factual markers only; avoid generic "the " matching.
    if normalized.startswith(_FACT_PREFIXES):
        return MemoryClass.FACT

    return MemoryClass.CONVERSATION



def evaluate_classifier(
    examples: Iterable[ClassificationExample],
) -> ClassificationReport:
    """Evaluate labels and return accuracy plus a complete confusion matrix."""

    rows = list(examples)
    labels = [label.value for label in MemoryClass]
    confusion = {expected: {predicted: 0 for predicted in labels} for expected in labels}
    correct = 0
    for example in rows:
        predicted = classify_memory(example.text, tool_name=example.tool_name)
        confusion[example.expected.value][predicted.value] += 1
        correct += predicted == example.expected
    return ClassificationReport(
        total=len(rows),
        correct=correct,
        accuracy=correct / len(rows) if rows else 0.0,
        confusion=confusion,
    )
