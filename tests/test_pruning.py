"""Tests for Pruner — drop and summarize strategies."""

import time

from ctxflow.extractors import DefaultExtractor
from ctxflow.graph import ContextGraph
from ctxflow.models import CtxFlowConfig, Edge, Node
from ctxflow.pruning import Pruner


def _make_old_node(id: str, tags: set[str], age_seconds: float = 100000) -> Node:
    """Create a node that appears old and never accessed."""
    return Node(
        content=f"old content {id}",
        summary=f"summary {id}",
        id=id,
        tags=tags,
        timestamp=time.time() - age_seconds,
        last_accessed=0.0,
        access_count=0,
    )


def _make_fresh_node(id: str, tags: set[str]) -> Node:
    """Create a node that was just accessed."""
    return Node(
        content=f"fresh content {id}",
        summary=f"summary {id}",
        id=id,
        tags=tags,
        timestamp=time.time(),
        last_accessed=time.time(),
        access_count=10,
    )


class TestDropStrategy:
    def test_removes_stale_nodes(self):
        config = CtxFlowConfig()
        extractor = DefaultExtractor()
        pruner = Pruner(config, extractor)

        g = ContextGraph()
        g.add_node(_make_old_node("old1", {"a"}))
        g.add_node(_make_old_node("old2", {"b"}))
        g.add_node(_make_fresh_node("fresh", {"c"}))

        # Low threshold to catch stale nodes.
        removed = pruner.prune(g, threshold=0.3, strategy="drop")
        assert "old1" in removed
        assert "old2" in removed
        assert "fresh" not in removed
        assert g.node_count == 1
        assert g.get_node("fresh") is not None

    def test_no_pruning_when_all_fresh(self):
        config = CtxFlowConfig()
        pruner = Pruner(config, DefaultExtractor())

        g = ContextGraph()
        g.add_node(_make_fresh_node("f1", {"a"}))
        g.add_node(_make_fresh_node("f2", {"b"}))

        removed = pruner.prune(g, threshold=0.3, strategy="drop")
        assert removed == []
        assert g.node_count == 2

    def test_empty_graph(self):
        pruner = Pruner(CtxFlowConfig(), DefaultExtractor())
        g = ContextGraph()
        removed = pruner.prune(g, threshold=0.5, strategy="drop")
        assert removed == []


class TestSummarizeStrategy:
    def test_collapses_cluster(self):
        config = CtxFlowConfig()
        pruner = Pruner(config, DefaultExtractor())

        g = ContextGraph()
        # Create a cluster of stale nodes.
        g.add_node(_make_old_node("s1", {"topic_a"}))
        g.add_node(_make_old_node("s2", {"topic_a", "topic_b"}))
        g.add_edge(Edge(source_id="s1", target_id="s2"))

        # Fresh node connected to the cluster.
        g.add_node(_make_fresh_node("fresh", {"topic_c"}))
        g.add_edge(Edge(source_id="s2", target_id="fresh"))

        initial_count = g.node_count
        removed = pruner.prune(g, threshold=0.3, strategy="summarize")

        assert "s1" in removed
        assert "s2" in removed
        # A summary node should have been created.
        # Graph should have 2 nodes: fresh + summary.
        assert g.node_count == 2
        # The summary node should be linked to "fresh".
        remaining_nodes = g.all_nodes()
        summary_node = [n for n in remaining_nodes if n.node_type == "summary"]
        assert len(summary_node) == 1
        assert "topic_a" in summary_node[0].tags
        assert "topic_b" in summary_node[0].tags

    def test_preserves_fresh_nodes(self):
        config = CtxFlowConfig()
        pruner = Pruner(config, DefaultExtractor())

        g = ContextGraph()
        g.add_node(_make_old_node("old", {"x"}))
        g.add_node(_make_fresh_node("fresh", {"y"}))

        removed = pruner.prune(g, threshold=0.3, strategy="summarize")
        assert "fresh" not in removed
        assert g.has_node("fresh")
