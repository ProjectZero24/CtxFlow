"""Benchmark Dataset Generator for Truth Maintenance Evaluation.

Provides curated and synthetic scientific claims featuring:
- Sequential scientific revisions (e.g. initial claim superseded by later paper)
- Contradictory findings between competing hypotheses
- Multi-hop citation chains
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BenchmarkPaper:
    """A paper in the evaluation benchmark."""

    id: str
    title: str
    year: int
    claims: List[Dict[str, Any]]
    abstract: str = ""


@dataclass
class BenchmarkQuestion:
    """A question evaluating truth maintenance and contradiction handling."""

    id: str
    question: str
    expected_answer: str
    expected_active_claims: List[str]
    expected_superseded_claims: List[str]
    requires_contradiction_awareness: bool = True
    ground_truth_sources: List[str] = field(default_factory=list)


@dataclass
class BenchmarkSuite:
    """A benchmark suite of papers and validation queries."""

    name: str
    papers: List[BenchmarkPaper]
    questions: List[BenchmarkQuestion]


def get_default_contradiction_benchmark() -> BenchmarkSuite:
    """Return a standard benchmark suite with known supersessions and contradictions.

    Scenario:
    Paper 1 (2020): Initial finding claiming Algorithm X achieves 85% accuracy on Benchmark Y.
    Paper 2 (2022): Correction finding that Algorithm X had data leakage; true accuracy is 71%.
    Paper 3 (2023): New method Algorithm Z achieves 89% accuracy without leakage.
    Paper 4 (2021): Competing method Algorithm W claims 86% accuracy, but contested by Paper 5.
    Paper 5 (2023): Refutation of Paper 4's evaluation methodology.
    """
    papers = [
        BenchmarkPaper(
            id="p1",
            title="Algorithm X: Fast Optimization on Benchmark Y",
            year=2020,
            claims=[
                {
                    "text": "Algorithm X achieves 85% accuracy on Benchmark Y under standard splits.",
                    "type": "claim",
                    "tags": ["algorithm_x", "benchmark_y", "accuracy", "optimization"],
                },
                {
                    "text": "The compute footprint of Algorithm X is 4x lower than baseline.",
                    "type": "claim",
                    "tags": ["algorithm_x", "efficiency", "compute"],
                },
            ],
            abstract="We present Algorithm X for fast optimization, achieving 85% accuracy on Benchmark Y.",
        ),
        BenchmarkPaper(
            id="p2",
            title="A Critical Re-Evaluation of Algorithm X: Data Leakage and True Performance",
            year=2022,
            claims=[
                {
                    "text": "Algorithm X achieves 71% accuracy on Benchmark Y when test set data leakage is corrected.",
                    "type": "claim",
                    "tags": ["algorithm_x", "benchmark_y", "accuracy", "re-evaluation"],
                    "supersedes": "Algorithm X achieves 85% accuracy on Benchmark Y under standard splits.",
                },
            ],
            abstract="We show prior 85% results were tainted by test leakage. The true accuracy of Algorithm X is 71%.",
        ),
        BenchmarkPaper(
            id="p3",
            title="Algorithm Z: Robust Optimization Without Information Leakage",
            year=2023,
            claims=[
                {
                    "text": "Algorithm Z achieves 89% accuracy on Benchmark Y with strictly isolated validation sets.",
                    "type": "claim",
                    "tags": ["algorithm_z", "benchmark_y", "accuracy", "robustness"],
                },
            ],
            abstract="Algorithm Z achieves state-of-the-art 89% accuracy without leakage.",
        ),
    ]

    questions = [
        BenchmarkQuestion(
            id="q1",
            question="What is the verified accuracy of Algorithm X on Benchmark Y?",
            expected_answer="71%",
            expected_active_claims=["Algorithm X achieves 71% accuracy on Benchmark Y when test set data leakage is corrected."],
            expected_superseded_claims=["Algorithm X achieves 85% accuracy on Benchmark Y under standard splits."],
            requires_contradiction_awareness=True,
            ground_truth_sources=["p2"],
        ),
        BenchmarkQuestion(
            id="q2",
            question="Which algorithm has the highest reported valid accuracy on Benchmark Y?",
            expected_answer="Algorithm Z (89%)",
            expected_active_claims=["Algorithm Z achieves 89% accuracy on Benchmark Y with strictly isolated validation sets."],
            expected_superseded_claims=[],
            requires_contradiction_awareness=False,
            ground_truth_sources=["p3"],
        ),
    ]

    return BenchmarkSuite(
        name="Scientific Contradiction & Supersession Suite v1",
        papers=papers,
        questions=questions,
    )
