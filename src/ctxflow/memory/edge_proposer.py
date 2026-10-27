"""LLM-assisted graph edge proposals and benchmark metrics."""

from __future__ import annotations

from dataclasses import dataclass
import json
import inspect
from typing import Callable, Iterable

from ctxflow.memory.store import Edge, Memory, Relation


_RELATIONS = {relation.value for relation in Relation}
_RELATION_VALUES = ", ".join(sorted(_RELATIONS))
_EDGE_SYSTEM = f"""You are a memory-graph edge classifier.
Return ONLY a JSON array. Each item must contain exactly these fields:
target_id (string), relation (string), confidence (number from 0 to 1).
The relation must be one of: {_RELATION_VALUES}.
Only return an edge when the new memory and target memory have a supported,
meaningful relationship. Never invent target IDs or relation names.
Return [] when no supported edge applies. Do not use markdown or explanations."""


@dataclass(frozen=True)
class EdgeMetrics:
    precision: float
    recall: float
    true_positives: int
    predicted: int
    gold: int


@dataclass(frozen=True)
class EdgePRReport:
    overall: EdgeMetrics
    by_relation: dict[str, EdgeMetrics]


class LLMEdgeProposer:
    """Propose typed edges from a cached or uncached LLM callable."""

    def __init__(self, llm: Callable[..., str], *, threshold: float = 0.7) -> None:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        self._llm = llm
        self.threshold = threshold

    def propose(self, memory: Memory, neighbors: Iterable[Memory]) -> list[Edge]:
        candidates = list(neighbors)
        if not candidates:
            return []
        prompt = "\n".join(
            [
                "NEW MEMORY",
                f"id: {memory.id}",
                f"text: {memory.text}",
                "CANDIDATE MEMORIES",
            ]
            + [f"CANDIDATE [{item.id}] {item.text}" for item in candidates]
        )
        parameters = inspect.signature(self._llm).parameters
        accepts_system = "system" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        raw = (
            self._llm(prompt, system=_EDGE_SYSTEM)
            if accepts_system
            else self._llm(prompt)
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("edge proposer returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("edge proposer response must be a JSON array")
        allowed = {item.id for item in candidates}
        edges: list[Edge] = []
        seen: set[tuple[str, str]] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("each proposed edge must be an object")
            if set(item) != {"target_id", "relation", "confidence"}:
                raise ValueError(
                    "each proposed edge must contain only target_id, relation, confidence"
                )
            target = item.get("target_id")
            relation = item.get("relation")
            confidence = item.get("confidence")
            if target not in allowed or relation not in _RELATIONS:
                raise ValueError("edge proposal contains an unknown target or relation")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError("edge confidence must be between 0 and 1")
            key = (target, relation)
            if confidence >= self.threshold and key not in seen:
                edges.append(Edge(memory.id, target, Relation(relation),
                                  confidence=confidence, created_by="llm"))
                seen.add(key)
        return edges


def edge_precision_recall(
    predicted: Iterable[Edge],
    gold: Iterable[Edge],
) -> EdgePRReport:
    """Calculate overall and per-relation edge precision/recall."""

    predicted_keys = {(edge.src, edge.dst, edge.relation.value) for edge in predicted}
    gold_keys = {(edge.src, edge.dst, edge.relation.value) for edge in gold}
    relations = sorted({key[2] for key in predicted_keys | gold_keys})

    def metrics(pred: set[tuple[str, str, str]], expected: set[tuple[str, str, str]]) -> EdgeMetrics:
        true_positives = len(pred & expected)
        return EdgeMetrics(
            precision=true_positives / len(pred) if pred else 0.0,
            recall=true_positives / len(expected) if expected else 0.0,
            true_positives=true_positives,
            predicted=len(pred),
            gold=len(expected),
        )

    by_relation = {
        relation: metrics(
            {key for key in predicted_keys if key[2] == relation},
            {key for key in gold_keys if key[2] == relation},
        )
        for relation in relations
    }
    return EdgePRReport(metrics(predicted_keys, gold_keys), by_relation)
