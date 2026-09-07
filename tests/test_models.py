"""Tests for core data models."""

import time

import pytest

from ctxflow.models import CtxFlowConfig, Edge, Node, QueryResult


class TestNode:
    def test_defaults(self):
        node = Node(content="hello world")
        assert node.content == "hello world"
        assert len(node.id) == 12
        assert node.summary == ""
        assert node.embedding is None
        assert node.tags == set()
        assert node.node_type == "generic"
        assert node.timestamp > 0
        assert node.metadata == {}
        assert node.last_accessed == 0.0
        assert node.access_count == 0

    def test_custom_fields(self):
        node = Node(
            content="test",
            id="custom-id",
            tags={"foo", "bar"},
            node_type="observation",
            metadata={"key": "val"},
        )
        assert node.id == "custom-id"
        assert node.tags == {"foo", "bar"}
        assert node.node_type == "observation"
        assert node.metadata == {"key": "val"}

    def test_touch_updates_tracking(self):
        node = Node(content="test")
        assert node.access_count == 0
        assert node.last_accessed == 0.0

        node.touch()
        assert node.access_count == 1
        assert node.last_accessed > 0

        first_access = node.last_accessed
        time.sleep(0.01)
        node.touch()
        assert node.access_count == 2
        assert node.last_accessed >= first_access


class TestEdge:
    def test_defaults(self):
        edge = Edge(source_id="a", target_id="b")
        assert edge.source_id == "a"
        assert edge.target_id == "b"
        assert edge.relation_type == "related_to"
        assert edge.weight == 1.0
        assert edge.timestamp > 0

    def test_custom_fields(self):
        edge = Edge(
            source_id="a",
            target_id="b",
            relation_type="caused_by",
            weight=0.75,
        )
        assert edge.relation_type == "caused_by"
        assert edge.weight == 0.75


class TestCtxFlowConfig:
    def test_defaults_are_valid(self):
        config = CtxFlowConfig()
        config.validate()  # Should not raise.

    def test_weights_must_sum_to_one(self):
        config = CtxFlowConfig(alpha=0.5, beta=0.5, gamma=0.5)
        with pytest.raises(ValueError, match="sum to 1.0"):
            config.validate()

    def test_weights_must_be_in_range(self):
        config = CtxFlowConfig(alpha=-0.1, beta=0.6, gamma=0.5)
        with pytest.raises(ValueError, match="must be in"):
            config.validate()

    def test_degree_cap_minimum(self):
        config = CtxFlowConfig(degree_cap=0)
        with pytest.raises(ValueError, match="degree_cap"):
            config.validate()

    def test_bfs_max_depth_minimum(self):
        config = CtxFlowConfig(bfs_max_depth=0)
        with pytest.raises(ValueError, match="bfs_max_depth"):
            config.validate()


class TestQueryResult:
    def test_repr(self):
        node = Node(content="test", id="abc123", node_type="fact")
        qr = QueryResult(node=node, score=0.85)
        r = repr(qr)
        assert "abc123" in r
        assert "0.85" in r
        assert "fact" in r
