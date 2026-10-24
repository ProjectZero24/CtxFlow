"""Evaluate the memory classifier against the checked-in labeled dataset."""

from __future__ import annotations

import csv
from pathlib import Path

from ctxflow.memory.classification import (
    ClassificationExample,
    MemoryClass,
    classify_memory,
    evaluate_classifier,
)


DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "data"
    / "ctxflow_classification_challenge_100.csv"
)
REQUIRED_COLUMNS = {"event_id", "tool_name", "text", "expected_label"}


def _load_examples() -> tuple[list[dict[str, str]], list[ClassificationExample]]:
    with DATASET_PATH.open(newline="", encoding="utf-8") as dataset:
        rows = list(csv.DictReader(dataset))

    missing_columns = REQUIRED_COLUMNS - set(rows[0]) if rows else REQUIRED_COLUMNS
    assert not missing_columns, f"Dataset is missing columns: {sorted(missing_columns)}"

    examples = [
        ClassificationExample(
            text=row["text"],
            expected=MemoryClass(row["expected_label"]),
            tool_name=row["tool_name"] or None,
        )
        for row in rows
    ]
    return rows, examples


def test_classification_dataset_evaluation() -> None:
    """Run every labeled event through the production classifier and report metrics."""
    rows, examples = _load_examples()
    report = evaluate_classifier(examples)
    labels = [memory_class.value for memory_class in MemoryClass]

    print(f"\nDataset: {DATASET_PATH}")
    print(f"Examples: {report.total}")
    print(f"Correct: {report.correct}")
    print(f"Incorrect: {report.total - report.correct}")
    print(f"Accuracy: {report.accuracy:.2%}")

    print("\nConfusion matrix (expected rows / predicted columns):")
    print("expected\\predicted," + ",".join(labels))
    for expected in labels:
        print(expected + "," + ",".join(str(report.confusion[expected][predicted]) for predicted in labels))

    print("\nPer-class metrics:")
    for label in labels:
        true_positive = report.confusion[label][label]
        false_positive = sum(
            report.confusion[other][label] for other in labels if other != label
        )
        false_negative = sum(
            report.confusion[label][other] for other in labels if other != label
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
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        support = true_positive + false_negative
        print(
            f"{label}: support={support}, precision={precision:.2%}, "
            f"recall={recall:.2%}, f1={f1:.2%}"
        )

    print("\nMisclassified examples:")
    print("event_id | expected | predicted | text")
    for row, example in zip(rows, examples):
        predicted = classify_memory(
            example.text,
            tool_name=example.tool_name,
        ).value
        if predicted != row["expected_label"]:
            print(
                f"{row['event_id']} | {row['expected_label']} | "
                f"{predicted} | {row['text']}"
            )

    assert DATASET_PATH.is_file()
    assert report.total == len(rows)
    assert report.total > 0
