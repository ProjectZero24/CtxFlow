"""Evaluate the live edge proposer against the checked-in edge dataset."""

from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from dotenv import dotenv_values

from ctxflow.memory import Edge, LLMEdgeProposer, Memory, Relation, edge_precision_recall
from ctxflow.providers.groq import GroqLLM


DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "data"
    / "ctxflow_edge_proposal_eval.csv"
)
REQUIRED_COLUMNS = {"example_id", "source_memory", "candidate_memory", "expected_relation"}
OUTCOMES = ("propose", "reject")


@dataclass(frozen=True)
class EvaluationResult:
    example_id: str
    source_memory: str
    candidate_memory: str
    expected_outcome: str
    actual_outcome: str
    expected_relation: str
    actual_relation: str
    predicted_edges: tuple[Edge, ...]


def _load_rows() -> list[dict[str, str]]:
    with DATASET_PATH.open(newline="", encoding="utf-8") as dataset:
        rows = list(csv.DictReader(dataset))
    missing_columns = REQUIRED_COLUMNS - set(rows[0]) if rows else REQUIRED_COLUMNS
    assert not missing_columns, f"Dataset is missing columns: {sorted(missing_columns)}"
    return rows


def _configured_groq_key() -> str | None:
    values = dotenv_values(Path(".env"))
    return os.getenv("GROQ_API_KEY") or (
        str(values["GROQ_API_KEY"]) if values.get("GROQ_API_KEY") else None
    )


def _metrics(
    results: list[EvaluationResult],
) -> tuple[dict[str, dict[str, int]], dict[str, float]]:
    confusion = {
        expected: {actual: 0 for actual in OUTCOMES} for expected in OUTCOMES
    }
    for result in results:
        confusion[result.expected_outcome][result.actual_outcome] += 1

    metrics: dict[str, float] = {}
    for outcome in OUTCOMES:
        true_positive = confusion[outcome][outcome]
        false_positive = sum(
            confusion[other][outcome] for other in OUTCOMES if other != outcome
        )
        false_negative = sum(
            confusion[outcome][other] for other in OUTCOMES if other != outcome
        )
        precision = (
            true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else 0.0
        )
        recall = (
            true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else 0.0
        )
        metrics[f"{outcome}_precision"] = precision
        metrics[f"{outcome}_recall"] = recall
        metrics[f"{outcome}_f1"] = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
    return confusion, metrics


def test_edge_proposal_dataset_evaluation() -> None:
    """Evaluate every dataset pair with one proposer call per example."""
    if os.getenv("CTXFLOW_RUN_EDGE_PROPOSAL_EVAL") != "1":
        pytest.skip(
            "Set CTXFLOW_RUN_EDGE_PROPOSAL_EVAL=1 to run the live edge proposal evaluation"
        )
    groq_key = _configured_groq_key()
    if not groq_key:
        pytest.skip("GROQ_API_KEY is not configured; skipping the live evaluation")

    rows = _load_rows()
    proposer = LLMEdgeProposer(GroqLLM(api_key=groq_key))
    results: list[EvaluationResult] = []
    predicted_edges: list[Edge] = []
    expected_edges: list[Edge] = []

    for index, row in enumerate(rows):
        if index:
            time.sleep(8)
        expected_relation = row["expected_relation"].strip()
        expected_outcome = "propose" if expected_relation else "reject"
        source = Memory(id=f"{row['example_id']}-source", text=row["source_memory"])
        candidate = Memory(id=f"{row['example_id']}-candidate", text=row["candidate_memory"])
        edges = tuple(proposer.propose(source, [candidate]))
        actual_outcome = "propose" if edges else "reject"
        actual_relations = "|".join(sorted(edge.relation.value for edge in edges))
        results.append(
            EvaluationResult(
                example_id=row["example_id"],
                source_memory=row["source_memory"],
                candidate_memory=row["candidate_memory"],
                expected_outcome=expected_outcome,
                actual_outcome=actual_outcome,
                expected_relation=expected_relation,
                actual_relation=actual_relations,
                predicted_edges=edges,
            )
        )
        predicted_edges.extend(edges)
        if expected_relation:
            expected_edges.append(
                Edge(source.id, candidate.id, Relation(expected_relation))
            )

    confusion, metrics = _metrics(results)
    outcome_correct = sum(
        result.actual_outcome == result.expected_outcome for result in results
    )
    proposed = [result for result in results if result.expected_outcome == "propose"]
    relation_correct = sum(
        result.actual_outcome == "propose"
        and result.actual_relation == result.expected_relation
        for result in proposed
    )
    exact_correct = sum(
        result.actual_outcome == result.expected_outcome
        and (
            result.expected_outcome == "reject"
            or result.actual_relation == result.expected_relation
        )
        for result in results
    )
    edge_report = edge_precision_recall(predicted_edges, expected_edges)
    misclassified = [
        result
        for result in results
        if result.actual_outcome != result.expected_outcome
        or (
            result.expected_outcome == "propose"
            and result.actual_relation != result.expected_relation
        )
    ]

    print(f"\nDataset: {DATASET_PATH}")
    print(f"Examples: {len(rows)}")
    print(f"Processed: {len(results)}")
    print(f"Outcome correct: {outcome_correct}")
    print(f"Outcome incorrect: {len(results) - outcome_correct}")
    print(f"Outcome accuracy: {outcome_correct / len(results):.2%}")
    print("\nOutcome metrics (positive class: propose):")
    print(
        f"propose: precision={metrics['propose_precision']:.2%}, "
        f"recall={metrics['propose_recall']:.2%}, f1={metrics['propose_f1']:.2%}"
    )
    print(
        f"reject: precision={metrics['reject_precision']:.2%}, "
        f"recall={metrics['reject_recall']:.2%}, f1={metrics['reject_f1']:.2%}"
    )
    print("\nConfusion matrix (expected rows / predicted columns):")
    print("expected\\predicted," + ",".join(OUTCOMES))
    for expected in OUTCOMES:
        print(expected + "," + ",".join(str(confusion[expected][actual]) for actual in OUTCOMES))
    print(
        f"\nRelationship accuracy on expected proposals: "
        f"{relation_correct}/{len(proposed)} "
        f"({relation_correct / len(proposed):.2%})"
    )
    print(
        f"Exact edge accuracy (outcome + relation): "
        f"{exact_correct}/{len(results)} ({exact_correct / len(results):.2%})"
    )
    print(
        f"Typed edge precision={edge_report.overall.precision:.2%}, "
        f"recall={edge_report.overall.recall:.2%}"
    )
    print("\nPer-relation typed edge metrics:")
    for relation, relation_metrics in edge_report.by_relation.items():
        f1 = (
            2 * relation_metrics.precision * relation_metrics.recall
            / (relation_metrics.precision + relation_metrics.recall)
            if relation_metrics.precision + relation_metrics.recall
            else 0.0
        )
        print(
            f"{relation}: precision={relation_metrics.precision:.2%}, "
            f"recall={relation_metrics.recall:.2%}, f1={f1:.2%}, "
            f"support={relation_metrics.gold}"
        )
    print("\nMisclassified examples:")
    print("example_id | source_memory | candidate_memory | expected_outcome | actual_outcome | expected_relation | actual_relation")
    for result in misclassified:
        print(
            f"{result.example_id} | {result.source_memory} | {result.candidate_memory} | "
            f"{result.expected_outcome} | {result.actual_outcome} | "
            f"{result.expected_relation} | {result.actual_relation}"
        )

    assert DATASET_PATH.is_file()
    assert len(results) == len(rows)
