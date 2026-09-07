"""Tests for serialization — JSON and binary round-trips."""

import json
import os
import tempfile

import pytest

from ctxflow.graph import ContextGraph
from ctxflow.models import Edge, Node
from ctxflow.serialization import export_json, import_json


def _build_test_graph() -> ContextGraph:
    """Build a small graph for round-trip testing."""
    g = ContextGraph()
    n1 = Node(
        content="Hello world",
        id="n1",
        summary="Greeting",
        tags={"greeting", "english"},
        node_type="utterance",
        metadata={"speaker": "user"},
        access_count=3,
        last_accessed=1000.0,
    )
    n2 = Node(
        content="Goodbye world",
        id="n2",
        summary="Farewell",
        tags={"farewell", "english"},
        node_type="utterance",
    )
    g.add_node(n1)
    g.add_node(n2)
    g.add_edge(Edge(source_id="n1", target_id="n2", relation_type="followed_by", weight=0.9))
    return g


class TestJSONRoundTrip:
    def test_round_trip(self, tmp_path):
        original = _build_test_graph()
        path = str(tmp_path / "graph.json")
        export_json(original, path)

        loaded = import_json(path)
        assert loaded.node_count == original.node_count
        assert loaded.edge_count == original.edge_count

        # Verify node data.
        n1 = loaded.get_node("n1")
        assert n1 is not None
        assert n1.content == "Hello world"
        assert n1.summary == "Greeting"
        assert n1.tags == {"greeting", "english"}
        assert n1.node_type == "utterance"
        assert n1.metadata == {"speaker": "user"}
        assert n1.access_count == 3
        assert n1.last_accessed == 1000.0

        n2 = loaded.get_node("n2")
        assert n2 is not None
        assert n2.content == "Goodbye world"

        # Verify edge data.
        edges = loaded.get_edges_from("n1")
        assert len(edges) == 1
        assert edges[0].target_id == "n2"
        assert edges[0].relation_type == "followed_by"
        assert edges[0].weight == pytest.approx(0.9)

    def test_json_is_readable(self, tmp_path):
        g = _build_test_graph()
        path = str(tmp_path / "graph.json")
        export_json(g, path)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "version" in data
        assert "nodes" in data
        assert "edges" in data
        assert data["version"] == 1

    def test_empty_graph_round_trip(self, tmp_path):
        g = ContextGraph()
        path = str(tmp_path / "empty.json")
        export_json(g, path)
        loaded = import_json(path)
        assert loaded.node_count == 0
        assert loaded.edge_count == 0


class TestBinaryRoundTrip:
    def test_round_trip(self, tmp_path):
        try:
            from ctxflow.serialization import export_binary, import_binary
        except ImportError:
            pytest.skip("msgpack not installed")

        original = _build_test_graph()
        path = str(tmp_path / "graph.msgpack")
        try:
            export_binary(original, path)
        except ImportError:
            pytest.skip("msgpack not installed")

        loaded = import_binary(path)
        assert loaded.node_count == original.node_count
        assert loaded.edge_count == original.edge_count

        n1 = loaded.get_node("n1")
        assert n1 is not None
        assert n1.content == "Hello world"
        assert n1.tags == {"greeting", "english"}
