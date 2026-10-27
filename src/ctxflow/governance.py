"""Graph governance — degree caps and score normalization.

Enforces structural health constraints at insertion time (degree cap)
and optionally at query time (score normalization by degree). This is
the explicit mitigation of Mem0g's high-degree bias problem.
"""

from __future__ import annotations

from ctxflow.graph import ContextGraph
from ctxflow.models import CtxFlowConfig


class GovernanceEngine:
    """Stateless governance checks operating over a ContextGraph."""

    def __init__(self, config: CtxFlowConfig) -> None:
        self.config = config

    def can_add_edge(self, graph: ContextGraph, source_id: str) -> bool:
        """Return ``True`` if *source_id* can accept another outgoing edge.

        When ``degree_cap_enabled`` is ``False``, always returns ``True``.
        Otherwise, checks that the node's out-degree is below the cap.
        """
        if not self.config.degree_cap_enabled:
            return True
        return graph.out_degree(source_id) < self.config.degree_cap

    def normalize_score(self, score: float, degree: int) -> float:
        """Optionally normalize *score* by the node's total degree.

        When ``degree_normalization`` is enabled, returns
        ``score / (degree + 1)`` to dampen high-degree nodes.
        Otherwise returns *score* unchanged.
        """
        if not self.config.degree_normalization:
            return score
        return score / (degree + 1)
