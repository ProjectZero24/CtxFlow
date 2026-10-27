"""Integration tests — full ingest → query → prune → export → import workflow."""

import pytest

from ctxflow import CtxFlow, CtxFlowConfig, QueryResult


class TestEndToEnd:
    def test_basic_workflow(self, tmp_path):
        ctx = CtxFlow()

        # Ingest several context units.
        id1 = ctx.ingest(
            "The agent detected a wall obstacle directly ahead at distance 2 meters.",
            node_type="observation",
        )
        id2 = ctx.ingest(
            "The agent decided to turn left to avoid the obstacle.",
            node_type="decision",
            source_id=id1,
        )
        id3 = ctx.ingest(
            "After turning left, the agent found an open corridor.",
            node_type="observation",
            source_id=id2,
        )
        id4 = ctx.ingest(
            "The temperature sensor reads 25 degrees Celsius.",
            node_type="sensor_reading",
        )

        assert len(ctx) == 4
        assert ctx.graph.node_count == 4
        assert ctx.graph.edge_count > 0  # At least explicit edges.

        # Query: should find obstacle-related nodes.
        results = ctx.query("What obstacle has the agent seen?", k=2)
        assert len(results) == 2
        assert all(isinstance(r, QueryResult) for r in results)
        # The wall observation should be most relevant.
        top_ids = [r.node.id for r in results]
        assert id1 in top_ids

        # Query with anchor: proximity to id2 should boost id1 and id3.
        results_anchored = ctx.query(
            "agent observation",
            k=4,
            anchor=id2,
        )
        assert len(results_anchored) == 4

    def test_export_import_round_trip(self, tmp_path):
        ctx = CtxFlow()
        ctx.ingest("fact one about the world", node_type="fact")
        ctx.ingest("fact two about physics", node_type="fact")
        ctx.ingest("a decision was made", node_type="decision")

        path = str(tmp_path / "state.json")
        ctx.export(path)

        # Load into a fresh instance.
        ctx2 = CtxFlow()
        ctx2.import_(path)
        assert len(ctx2) == len(ctx)
        assert ctx2.graph.edge_count == ctx.graph.edge_count

        # Query should still work.
        results = ctx2.query("physics fact", k=1)
        assert len(results) == 1

    def test_prune_workflow(self, tmp_path):
        ctx = CtxFlow()

        # Ingest nodes — they'll all be "fresh" right now.
        for i in range(5):
            ctx.ingest(f"Context unit number {i}", node_type="event")

        # Pruning with a very low threshold shouldn't remove fresh nodes.
        removed = ctx.prune(threshold=0.9, strategy="drop")
        # All nodes are fresh, so staleness should be low.
        assert len(ctx) == 5

    def test_custom_config(self):
        config = CtxFlowConfig(
            degree_cap=2,
            max_link_k=1,
            alpha=1.0,
            beta=0.0,
            gamma=0.0,
        )
        ctx = CtxFlow(config=config)

        ctx.ingest("alpha bravo charlie", tags={"alpha", "bravo"})
        ctx.ingest("bravo charlie delta", tags={"bravo", "charlie"})
        ctx.ingest("charlie delta echo", tags={"charlie", "delta"})

        # Degree cap of 2: nodes shouldn't have more than 2 outgoing edges.
        for node in ctx.graph.all_nodes():
            assert ctx.graph.out_degree(node.id) <= 2

    def test_repr(self):
        ctx = CtxFlow()
        ctx.ingest("test content")
        r = repr(ctx)
        assert "nodes=1" in r

    def test_tags_passed_through(self):
        ctx = CtxFlow()
        node_id = ctx.ingest(
            "some content",
            tags={"manual_tag"},
            metadata={"key": "value"},
        )
        node = ctx.graph.get_node(node_id)
        assert "manual_tag" in node.tags
        assert node.metadata == {"key": "value"}

    def test_invalid_config_raises(self):
        with pytest.raises(ValueError):
            CtxFlow(config=CtxFlowConfig(alpha=0.5, beta=0.5, gamma=0.5))
