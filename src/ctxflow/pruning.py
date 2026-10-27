"""Pruning and compaction — decoupled maintenance pass.

Runs separately from ingestion to keep the hot path O(1). Two strategies:
- ``drop``: remove stale nodes outright.
- ``summarize``: collapse clusters of stale nodes into summary nodes
  (borrowing RAPTOR's idea, but only as an offline compaction step).
"""

from __future__ import annotations

import time
from typing import Dict, List, Set, Tuple

from ctxflow.extractors import Extractor
from ctxflow.graph import ContextGraph
from ctxflow.models import CtxFlowConfig, Edge, Node


class Pruner:
    """Decoupled graph pruning / compaction."""

    def __init__(self, config: CtxFlowConfig, extractor: Extractor) -> None:
        self.config = config
        self.extractor = extractor

    # -- Public API ---------------------------------------------------------

    def prune(
        self,
        graph: ContextGraph,
        threshold: float = 0.5,
        strategy: str = "drop",
    ) -> List[str]:
        """Prune stale nodes from *graph*.

        Parameters
        ----------
        graph : ContextGraph
            The graph to prune (mutated in place).
        threshold : float
            Nodes with a staleness score **above** this threshold are pruned.
            Staleness is in [0, 1] where 1 = most stale.
        strategy : str
            ``"drop"`` — delete stale nodes.
            ``"summarize"`` — collapse connected stale clusters into summary nodes.

        Returns
        -------
        list[str]
            IDs of nodes that were removed (or replaced by summary nodes).
        """
        if strategy not in ("drop", "summarize"):
            raise ValueError(f"Unknown prune strategy: {strategy!r}")

        stale_ids = self._find_stale(graph, threshold)
        if not stale_ids:
            return []

        if strategy == "drop":
            return self._drop(graph, stale_ids)
        else:
            return self._summarize(graph, stale_ids)

    # -- Staleness scoring --------------------------------------------------

    def _staleness(self, node: Node, now: float, max_age: float) -> float:
        """Compute a staleness score in [0, 1] (higher = more stale).

        Combines three signals:
        - **Age**: how old the node is relative to the oldest node.
        - **Access frequency**: inverse of access_count.
        - **Last-accessed recency**: how long since the last query hit.
        """
        cfg = self.config

        # Age component: older → more stale.
        age = now - node.timestamp
        age_score = min(age / max_age, 1.0) if max_age > 0 else 0.0

        # Access frequency component: fewer accesses → more stale.
        access_score = 1.0 / (1.0 + node.access_count)

        # Last-accessed recency: longer since last access → more stale.
        if node.last_accessed > 0:
            since_access = now - node.last_accessed
            recency_score = min(since_access / max_age, 1.0) if max_age > 0 else 0.0
        else:
            recency_score = 1.0  # Never accessed → maximally stale on this axis.

        return (
            cfg.prune_age_weight * age_score
            + cfg.prune_access_weight * access_score
            + cfg.prune_recency_weight * recency_score
        )

    def _find_stale(
        self, graph: ContextGraph, threshold: float
    ) -> Set[str]:
        """Identify nodes whose staleness exceeds *threshold*."""
        nodes = graph.all_nodes()
        if not nodes:
            return set()

        now = time.time()
        timestamps = [n.timestamp for n in nodes]
        max_age = max(now - min(timestamps), 1.0)  # Avoid div-by-zero.

        stale: Set[str] = set()
        for node in nodes:
            score = self._staleness(node, now, max_age)
            if score > threshold:
                stale.add(node.id)
        return stale

    # -- Strategy: drop -----------------------------------------------------

    def _drop(self, graph: ContextGraph, stale_ids: Set[str]) -> List[str]:
        """Remove stale nodes outright."""
        removed: List[str] = []
        for nid in stale_ids:
            if graph.remove_node(nid) is not None:
                removed.append(nid)
        return removed

    # -- Strategy: summarize ------------------------------------------------

    def _summarize(
        self, graph: ContextGraph, stale_ids: Set[str]
    ) -> List[str]:
        """Collapse connected clusters of stale nodes into summary nodes.

        For each connected component among the stale nodes:
        1. Collect all non-stale neighbors of the cluster.
        2. Generate a summary node via the Extractor.
        3. Remove the stale nodes.
        4. Link the summary node to the collected neighbors.
        """
        # Build clusters: connected components among stale nodes.
        clusters = self._find_clusters(graph, stale_ids)
        removed: List[str] = []

        for cluster in clusters:
            cluster_nodes = [graph.get_node(nid) for nid in cluster]
            cluster_nodes = [n for n in cluster_nodes if n is not None]
            if not cluster_nodes:
                continue

            # Collect non-stale neighbors of the cluster.
            external_neighbors: Set[str] = set()
            for nid in cluster:
                for edge in graph.get_edges_from(nid):
                    if edge.target_id not in stale_ids:
                        external_neighbors.add(edge.target_id)
                for edge in graph.get_edges_to(nid):
                    if edge.source_id not in stale_ids:
                        external_neighbors.add(edge.source_id)

            # Generate summary node.
            summary_content = self.extractor.summarize_nodes(cluster_nodes)
            all_tags: Set[str] = set()
            for n in cluster_nodes:
                all_tags.update(n.tags)

            summary_node = Node(
                content=summary_content,
                summary=summary_content,
                tags=all_tags,
                node_type="summary",
                metadata={"compacted_from": [n.id for n in cluster_nodes]},
            )

            # Remove stale nodes.
            for nid in cluster:
                if graph.remove_node(nid) is not None:
                    removed.append(nid)

            # Insert summary node and link to external neighbors.
            graph.add_node(summary_node)
            for nbr_id in external_neighbors:
                if graph.has_node(nbr_id):
                    edge = Edge(
                        source_id=summary_node.id,
                        target_id=nbr_id,
                        relation_type="summarizes",
                        weight=1.0,
                    )
                    graph.add_edge(edge)

        return removed

    def _find_clusters(
        self, graph: ContextGraph, node_ids: Set[str]
    ) -> List[Set[str]]:
        """Find connected components among *node_ids* in the graph.

        Uses BFS limited to the stale-node subgraph.
        """
        remaining = set(node_ids)
        clusters: List[Set[str]] = []

        while remaining:
            seed = next(iter(remaining))
            cluster: Set[str] = set()
            queue = [seed]
            while queue:
                current = queue.pop()
                if current in cluster:
                    continue
                cluster.add(current)
                remaining.discard(current)
                # Neighbors within the stale set.
                for edge in graph.get_edges_from(current):
                    if edge.target_id in remaining:
                        queue.append(edge.target_id)
                for edge in graph.get_edges_to(current):
                    if edge.source_id in remaining:
                        queue.append(edge.source_id)
            clusters.append(cluster)

        return clusters
