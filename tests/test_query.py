"""Tests for QueryEngine — scoring math, weight overrides, proximity."""

import time

import pytest

from ctxflow.extractors import DefaultExtractor
from ctxflow.governance import GovernanceEngine
from ctxflow.graph import ContextGraph
from ctxflow.models import CtxFlowConfig, Edge, Node
from ctxflow.query import QueryEngine


def _make_node(id: str, tags: set[str], ts: float | None = None) -> Node:
    return Node(
        content=f"content-{id}",
        id=id,
        tags=tags,
        timestamp=ts or time.time(),
    )


class TestScoring:
    def setup_method(self):
        self.config = CtxFlowConfig()
        self.extractor = DefaultExtractor()
        self.governance = GovernanceEngine(self.config)
        self.engine = QueryEngine(self.config, self.extractor, self.governance)

    def test_tag_overlap_dominates(self):
        """With default weights (α=0.5), nodes with better tag overlap score higher."""
        g = ContextGraph()
        g.add_node(_make_node("good", {"python", "agent", "memory"}))
        g.add_node(_make_node("bad", {"javascript", "web", "browser"}))

        results = self.engine.query(g, "python agent memory graph", k=2)
        assert len(results) == 2
        assert results[0].node.id == "good"
        assert results[0].score > results[1].score

    def test_recency_boost(self):
        """A very recent node should score higher than an old one with same tags."""
        g = ContextGraph()
        old_ts = time.time() - 100000  # ~28 hours ago
        g.add_node(_make_node("old", {"agent"}, ts=old_ts))
        g.add_node(_make_node("new", {"agent"}))  # Created now.

        results = self.engine.query(g, "agent", k=2)
        assert results[0].node.id == "new"

    def test_proximity_boost(self):
        """Node adjacent to anchor should score higher (with gamma > 0)."""
        g = ContextGraph()
        g.add_node(_make_node("anchor", {"task"}))
        g.add_node(_make_node("near", {"task"}))
        g.add_node(_make_node("far", {"task"}))

        g.add_edge(Edge(source_id="anchor", target_id="near"))
        # "far" is not connected.

        results = self.engine.query(
            g, "task", k=3, anchor="anchor",
            weights=(0.0, 0.0, 1.0),  # Only proximity matters.
        )
        # Anchor itself should be first (proximity=1.0), then near (0.5), then far (0.0).
        ids = [r.node.id for r in results]
        assert ids[0] == "anchor"
        assert ids[1] == "near"
        assert ids[2] == "far"

    def test_weight_override(self):
        """Custom weights should be respected."""
        g = ContextGraph()
        g.add_node(_make_node("n1", {"apple"}))

        # All weight on tag overlap.
        results = self.engine.query(g, "apple", k=1, weights=(1.0, 0.0, 0.0))
        assert results[0].score_breakdown["tag_overlap"] > 0
        assert results[0].score == pytest.approx(results[0].score_breakdown["tag_overlap"])

    def test_score_breakdown_keys(self):
        g = ContextGraph()
        g.add_node(_make_node("n1", {"test"}))
        results = self.engine.query(g, "test", k=1)
        assert "tag_overlap" in results[0].score_breakdown
        assert "recency" in results[0].score_breakdown
        assert "proximity" in results[0].score_breakdown

    def test_access_tracking_updated(self):
        """Returned nodes should have their access_count incremented."""
        g = ContextGraph()
        node = _make_node("n1", {"test"})
        g.add_node(node)
        assert node.access_count == 0

        self.engine.query(g, "test", k=1)
        assert node.access_count == 1
        assert node.last_accessed > 0

    def test_empty_graph(self):
        g = ContextGraph()
        results = self.engine.query(g, "anything", k=5)
        assert results == []

    def test_k_limits_results(self):
        g = ContextGraph()
        for i in range(10):
            g.add_node(_make_node(f"n{i}", {"common"}))
        results = self.engine.query(g, "common", k=3)
        assert len(results) == 3


class TestDegreeNormalization:
    def test_high_degree_node_dampened(self):
        config = CtxFlowConfig(degree_normalization=True)
        extractor = DefaultExtractor()
        governance = GovernanceEngine(config)
        engine = QueryEngine(config, extractor, governance)

        g = ContextGraph()
        # Hub node with many edges.
        g.add_node(_make_node("hub", {"test"}))
        g.add_node(_make_node("leaf", {"test"}))
        for i in range(20):
            target = _make_node(f"t{i}", {"other"})
            g.add_node(target)
            g.add_edge(Edge(source_id="hub", target_id=target.id))

        results = engine.query(g, "test", k=2)
        # Leaf should beat hub due to normalization.
        assert results[0].node.id == "leaf"
