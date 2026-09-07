"""Query engine — tag+recency+proximity scoring.

Implements the composable scoring function:
    score(n) = α·tag_overlap(n, query) + β·recency(n) + γ·proximity(n, anchor)

All weights are configurable per-query (overriding config defaults).
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Set, Tuple

from ctxflow.extractors import Extractor
from ctxflow.governance import GovernanceEngine
from ctxflow.graph import ContextGraph
from ctxflow.models import CtxFlowConfig, Node, QueryResult


class QueryEngine:
    """Stateless query processor."""

    def __init__(
        self,
        config: CtxFlowConfig,
        extractor: Extractor,
        governance: GovernanceEngine,
    ) -> None:
        self.config = config
        self.extractor = extractor
        self.governance = governance

    def query(
        self,
        graph: ContextGraph,
        context: str,
        k: int = 5,
        weights: Optional[Tuple[float, float, float]] = None,
        anchor: Optional[str] = None,
    ) -> List[QueryResult]:
        """Score all nodes and return the top-*k* results.

        Parameters
        ----------
        graph : ContextGraph
            The graph to query.
        context : str
            Natural-language query string (tags are auto-extracted).
        k : int
            Number of results to return.
        weights : tuple[float, float, float] | None
            Override ``(alpha, beta, gamma)`` for this query.
        anchor : str | None
            Node ID to use as the proximity anchor.

        Returns
        -------
        list[QueryResult]
            Top-k nodes sorted by descending score.
        """
        alpha, beta, gamma = weights or (
            self.config.alpha,
            self.config.beta,
            self.config.gamma,
        )

        # 1. Extract tags from the query context.
        query_tags: Set[str] = self.extractor.extract_tags(context)

        # 2. Compute BFS distances from anchor (if provided).
        bfs_distances: Dict[str, int] = {}
        if anchor and graph.has_node(anchor):
            bfs_distances = graph.bfs_distances(
                anchor, max_depth=self.config.bfs_max_depth
            )

        # 3. Score every node.
        now = time.time()
        all_nodes: List[Node] = graph.all_nodes()
        results: List[QueryResult] = []

        for node in all_nodes:
            # Tag overlap (Jaccard).
            tag_score = ContextGraph.jaccard(query_tags, node.tags)

            # Recency: 1 / (1 + age_in_seconds).
            age = max(now - node.timestamp, 0.0)
            recency_score = 1.0 / (1.0 + age)

            # Proximity: 1 / (1 + hop_distance), or 0 if unreachable / no anchor.
            if anchor and node.id in bfs_distances:
                proximity_score = 1.0 / (1.0 + bfs_distances[node.id])
            elif anchor and node.id == anchor:
                proximity_score = 1.0  # Anchor itself has max proximity.
            else:
                proximity_score = 0.0

            # Composite score.
            score = (
                alpha * tag_score
                + beta * recency_score
                + gamma * proximity_score
            )

            # Degree normalization (if enabled).
            degree = graph.total_degree(node.id)
            score = self.governance.normalize_score(score, degree)

            results.append(
                QueryResult(
                    node=node,
                    score=score,
                    score_breakdown={
                        "tag_overlap": tag_score,
                        "recency": recency_score,
                        "proximity": proximity_score,
                    },
                )
            )

        # 4. Sort descending by score, take top-k.
        results.sort(key=lambda r: r.score, reverse=True)
        top_k = results[:k]

        # 5. Update access tracking on returned nodes.
        for result in top_k:
            result.node.touch()

        return top_k
