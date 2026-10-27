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
    rationale: str = ""


@dataclass
class BenchmarkSuite:
    """A benchmark suite of papers and validation queries."""

    name: str
    papers: List[BenchmarkPaper]
    questions: List[BenchmarkQuestion]


def get_default_contradiction_benchmark() -> BenchmarkSuite:
    """Return a standard benchmark suite with known supersessions and contradictions.

    The five-paper synthetic scenario covers an Algorithm X correction,
    Algorithm Z under isolated validation, and a separate Algorithm W
    correction. Ten questions exercise performance, efficiency, leakage,
    supersession, comparison, and source attribution.
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
        BenchmarkPaper(
            id="p4",
            title="Algorithm W: Competitive Results on Benchmark Y",
            year=2021,
            claims=[
                {
                    "text": "Algorithm W achieves 86% accuracy on Benchmark Y using the published evaluation protocol.",
                    "type": "claim",
                    "tags": ["algorithm_w", "benchmark_y", "accuracy", "evaluation"],
                },
            ],
            abstract="We report 86% accuracy for Algorithm W using the published evaluation protocol.",
        ),
        BenchmarkPaper(
            id="p5",
            title="Revisiting Algorithm W Under Leakage-Free Evaluation",
            year=2023,
            claims=[
                {
                    "text": "Algorithm W achieves 74% accuracy on Benchmark Y after duplicate test examples are removed.",
                    "type": "claim",
                    "tags": ["algorithm_w", "benchmark_y", "accuracy", "re-evaluation"],
                    "supersedes": "Algorithm W achieves 86% accuracy on Benchmark Y using the published evaluation protocol.",
                },
                {
                    "text": "The earlier Algorithm W evaluation included duplicate examples across training and test sets.",
                    "type": "claim",
                    "tags": ["algorithm_w", "benchmark_y", "duplicate", "leakage"],
                },
            ],
            abstract="We identify duplicate examples across training and test sets and report 74% accuracy after removing them.",
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
            rationale="Tests whether the correction supersedes a widely reported but leakage-affected score.",
        ),
        BenchmarkQuestion(
            id="q2",
            question="Which algorithm has the highest reported valid accuracy on Benchmark Y?",
            expected_answer="Algorithm Z (89%)",
            expected_active_claims=["Algorithm Z achieves 89% accuracy on Benchmark Y with strictly isolated validation sets."],
            expected_superseded_claims=[],
            requires_contradiction_awareness=False,
            ground_truth_sources=["p3"],
            rationale="Tests selection of the strongest result whose validation is explicitly leakage-isolated.",
        ),
        BenchmarkQuestion(
            id="q3",
            question="How does Algorithm X's compute footprint compare with the baseline?",
            expected_answer="4x lower",
            expected_active_claims=[
                "The compute footprint of Algorithm X is 4x lower than baseline."
            ],
            expected_superseded_claims=[],
            requires_contradiction_awareness=False,
            ground_truth_sources=["p1"],
            rationale="Covers an efficiency claim unrelated to the superseded accuracy result.",
        ),
        BenchmarkQuestion(
            id="q4",
            question="What flaw was found in the original Algorithm X evaluation?",
            expected_answer="test set data leakage",
            expected_active_claims=[
                "Algorithm X achieves 71% accuracy on Benchmark Y when test set data leakage is corrected."
            ],
            expected_superseded_claims=[
                "Algorithm X achieves 85% accuracy on Benchmark Y under standard splits."
            ],
            ground_truth_sources=["p2"],
            rationale="Checks that an explanation of the evaluation flaw retrieves the correction rather than the invalid score.",
        ),
        BenchmarkQuestion(
            id="q5",
            question="What accuracy did Algorithm Z achieve with strictly isolated validation sets?",
            expected_answer="89%",
            expected_active_claims=[
                "Algorithm Z achieves 89% accuracy on Benchmark Y with strictly isolated validation sets."
            ],
            expected_superseded_claims=[],
            requires_contradiction_awareness=False,
            ground_truth_sources=["p3"],
            rationale="Checks exact performance and validation context for the leakage-resistant method.",
        ),
        BenchmarkQuestion(
            id="q6",
            question="What is the corrected accuracy of Algorithm W after duplicate test examples are removed?",
            expected_answer="74%",
            expected_active_claims=[
                "Algorithm W achieves 74% accuracy on Benchmark Y after duplicate test examples are removed."
            ],
            expected_superseded_claims=[
                "Algorithm W achieves 86% accuracy on Benchmark Y using the published evaluation protocol."
            ],
            ground_truth_sources=["p5"],
            rationale="Adds a second independent supersession case to avoid relying on one correction scenario.",
        ),
        BenchmarkQuestion(
            id="q7",
            question="Why was Algorithm W's earlier Benchmark Y score revised?",
            expected_answer="duplicate examples across training and test sets",
            expected_active_claims=[
                "The earlier Algorithm W evaluation included duplicate examples across training and test sets."
            ],
            expected_superseded_claims=[
                "Algorithm W achieves 86% accuracy on Benchmark Y using the published evaluation protocol."
            ],
            ground_truth_sources=["p5"],
            rationale="Tests retrieval of the concrete cause behind the independent Algorithm W correction.",
        ),
        BenchmarkQuestion(
            id="q8",
            question="Which source documents the corrected Algorithm W result?",
            expected_answer="Revisiting Algorithm W Under Leakage-Free Evaluation",
            expected_active_claims=[
                "Algorithm W achieves 74% accuracy on Benchmark Y after duplicate test examples are removed."
            ],
            expected_superseded_claims=[
                "Algorithm W achieves 86% accuracy on Benchmark Y using the published evaluation protocol."
            ],
            ground_truth_sources=["p5"],
            rationale="Checks provenance attribution for a correction, not just retrieval of its numeric value.",
        ),
        BenchmarkQuestion(
            id="q9",
            question="Compare the corrected Benchmark Y accuracies of Algorithm X and Algorithm W.",
            expected_answer="Algorithm X 71%; Algorithm W 74%",
            expected_active_claims=[
                "Algorithm X achieves 71% accuracy on Benchmark Y when test set data leakage is corrected.",
                "Algorithm W achieves 74% accuracy on Benchmark Y after duplicate test examples are removed.",
            ],
            expected_superseded_claims=[
                "Algorithm X achieves 85% accuracy on Benchmark Y under standard splits.",
                "Algorithm W achieves 86% accuracy on Benchmark Y using the published evaluation protocol.",
            ],
            ground_truth_sources=["p2", "p5"],
            rationale="Requires both independent corrections while suppressing both superseded scores.",
        ),
        BenchmarkQuestion(
            id="q10",
            question="Which paper reports the Algorithm X compute-efficiency result?",
            expected_answer="Algorithm X: Fast Optimization on Benchmark Y",
            expected_active_claims=[
                "The compute footprint of Algorithm X is 4x lower than baseline."
            ],
            expected_superseded_claims=[],
            requires_contradiction_awareness=False,
            ground_truth_sources=["p1"],
            rationale="Checks source attribution for a non-accuracy claim to broaden coverage beyond supersession.",
        ),
    ]

    return BenchmarkSuite(
        name="Scientific Contradiction & Supersession Suite v1",
        papers=papers,
        questions=questions,
    )
