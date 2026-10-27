"""Evaluation metrics for the ResearchOS truth-maintenance benchmark.

The metrics here are deliberately deterministic and LLM-free so the
harness can run in CI. They implement the four axes from the project
proposal:

1. **Answer correctness** — the retrieved evidence reflects the current
   (non-superseded) claim.
2. **Provenance correctness** — the cited sources include the known
   ground-truth correction, not just the original claim.
3. **Token cost** — estimated prompt tokens consumed per query.
4. **Supersession defence** — how often outdated claims are suppressed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from ctxflow.memory.tokens import SimpleTokenizer


def estimate_tokens(text: str) -> int:
    """Count whitespace-delimited words and punctuation with ``simple-v1``."""
    if not text:
        return 0
    return SimpleTokenizer().count(text)


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for substring matching."""
    return " ".join(text.lower().split())


def text_matches(haystack: str, needle: str) -> bool:
    """Return ``True`` when *needle* appears in *haystack* (normalized)."""
    if not haystack or not needle:
        return False
    return _normalize(needle) in _normalize(haystack)


def matching_claims(texts: Sequence[str], claims: Sequence[str]) -> List[str]:
    """Return the subset of *claims* found in at least one retrieved text."""
    return [
        claim for claim in claims
        if any(text_matches(text, claim) for text in texts)
    ]


@dataclass
class EvaluationMetrics:
    """Aggregated metrics for one system on one benchmark suite.

    The public attribute names are stable so existing callers (and the
    original tests) keep working; derived rates are exposed as
    properties.
    """

    system_name: str
    total_questions: int = 0
    questions_correct: int = 0
    correct_active_claims_retrieved: int = 0
    superseded_claims_suppressed: int = 0
    superseded_claims_incorrectly_returned: int = 0
    provenance_traces_found: int = 0
    provenance_correct: int = 0
    context_tokens_total: int = 0

    # -- Derived rates ------------------------------------------------------

    @property
    def avg_context_tokens(self) -> float:
        """Average context tokens consumed per question."""
        if self.total_questions == 0:
            return 0.0
        return self.context_tokens_total / self.total_questions

    @property
    def token_cost_per_query(self) -> float:
        """Alias for :attr:`avg_context_tokens` (proposal terminology)."""
        return self.avg_context_tokens

    @property
    def answer_accuracy(self) -> float:
        """Fraction of questions whose current claim was retrieved cleanly."""
        if self.total_questions == 0:
            return 0.0
        return self.questions_correct / self.total_questions

    @property
    def provenance_accuracy(self) -> float:
        """Fraction of questions whose citations include the ground truth."""
        if self.total_questions == 0:
            return 0.0
        return self.provenance_correct / self.total_questions

    @property
    def precision_against_supersession(self) -> float:
        """Fraction of retrieved claims that are valid (not superseded)."""
        total_retrieved = (
            self.correct_active_claims_retrieved
            + self.superseded_claims_incorrectly_returned
        )
        if total_retrieved == 0:
            return 1.0
        return self.correct_active_claims_retrieved / total_retrieved

    @property
    def supersession_defense_rate(self) -> float:
        """Fraction of known superseded claims that were correctly suppressed."""
        denominator = (
            self.superseded_claims_suppressed
            + self.superseded_claims_incorrectly_returned
        )
        if denominator == 0:
            return 1.0
        return self.superseded_claims_suppressed / denominator

    # -- Recording ----------------------------------------------------------

    def record(
        self,
        question: Any,
        retrieved_texts: Sequence[str],
        cited_sources: Optional[Sequence[str]] = None,
        context_text: str = "",
        trace_found: bool = False,
    ) -> None:
        """Record one question's outcome.

        Parameters
        ----------
        question : BenchmarkQuestion
            The question with ``expected_active_claims``,
            ``expected_superseded_claims`` and ``ground_truth_sources``.
        retrieved_texts : sequence[str]
            Text of every retrieved/cited context item.
        cited_sources : sequence[str] | None
            Source paper identifiers cited by the system.
        context_text : str
            Full context assembled for the answer (used for token cost).
        trace_found : bool
            Whether a provenance trace was produced for this question.
        """
        self.total_questions += 1
        self.context_tokens_total += estimate_tokens(context_text)

        if trace_found:
            self.provenance_traces_found += 1

        active = list(getattr(question, "expected_active_claims", []) or [])
        superseded = list(
            getattr(question, "expected_superseded_claims", []) or []
        )

        active_hits = matching_claims(retrieved_texts, active)
        superseded_hits = matching_claims(retrieved_texts, superseded)

        self.correct_active_claims_retrieved += len(active_hits)
        self.superseded_claims_incorrectly_returned += len(superseded_hits)
        self.superseded_claims_suppressed += (
            len(superseded) - len(superseded_hits)
        )

        # A question is "correct" when it surfaces the current evidence and
        # does not present a superseded claim as if it were current.
        if active:
            question_correct = bool(active_hits) and not superseded_hits
        else:
            question_correct = not superseded_hits
        self.questions_correct += int(question_correct)

        # Provenance is only "correct" when the trace cites the known
        # correction *and* the system actually used the current claim.
        # A flat baseline that cites every paper but answers from the
        # outdated claim does not earn provenance credit.
        ground_truth = set(
            getattr(question, "ground_truth_sources", []) or []
        )
        if (
            question_correct
            and trace_found
            and ground_truth
            and cited_sources
            and ground_truth & set(cited_sources)
        ):
            self.provenance_correct += 1

    # -- Serialization ------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot of the metrics."""
        return {
            "system_name": self.system_name,
            "total_questions": self.total_questions,
            "questions_correct": self.questions_correct,
            "answer_accuracy": round(self.answer_accuracy, 4),
            "correct_active_claims_retrieved": self.correct_active_claims_retrieved,
            "superseded_claims_suppressed": self.superseded_claims_suppressed,
            "superseded_claims_incorrectly_returned": (
                self.superseded_claims_incorrectly_returned
            ),
            "supersession_defense_rate": round(
                self.supersession_defense_rate, 4
            ),
            "precision_against_supersession": round(
                self.precision_against_supersession, 4
            ),
            "provenance_traces_found": self.provenance_traces_found,
            "provenance_correct": self.provenance_correct,
            "provenance_accuracy": round(self.provenance_accuracy, 4),
            "avg_context_tokens": round(self.avg_context_tokens, 2),
        }
