"""Integration and unit tests for ResearchOS FastAPI Endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from ctxflow import CtxFlow
from ctxflow.models import CtxFlowConfig
from researchos.api.server import create_app


@pytest.fixture
def test_client():
    cf = CtxFlow()
    app = create_app(ctxflow=cf)
    with TestClient(app) as client:
        yield client


class TestApiEndpoints:
    """Tests for ResearchOS REST and system endpoints."""

    def test_health_endpoint(self, test_client):
        res = test_client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "graph_nodes" in data

    def test_list_skills(self, test_client):
        res = test_client.get("/api/skills")
        assert res.status_code == 200
        skills = res.json()["skills"]
        skill_names = [s["name"] for s in skills]
        assert "graph_query" in skill_names
        assert "literature_search" in skill_names
        assert "review_writer" in skill_names

    def test_paper_ingest_and_graph_data(self, test_client):
        # 1. Ingest paper
        ingest_payload = {
            "title": "Scaling Laws for Neural Language Models",
            "authors": ["Jared Kaplan", "Sam McCandlish"],
            "year": 2020,
            "abstract": "We observe that language model performance scales as a power-law with compute, dataset size, and parameter count.",
        }
        res = test_client.post("/api/papers/ingest", json=ingest_payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["paper_node_id"] != ""
        assert len(data["claim_node_ids"]) >= 1

        # 2. Check stats
        stats_res = test_client.get("/api/graph/stats")
        assert stats_res.status_code == 200
        stats = stats_res.json()
        assert stats["total_nodes"] >= 2
        assert stats["total_edges"] >= 1

        # 3. Check graph data
        graph_res = test_client.get("/api/graph/data")
        assert graph_res.status_code == 200
        g_data = graph_res.json()
        assert len(g_data["nodes"]) >= 2
        assert len(g_data["edges"]) >= 1

    def test_chat_query_flow(self, test_client):
        # Ingest knowledge first
        test_client.post(
            "/api/papers/ingest",
            json={
                "title": "BERT: Pre-training of Deep Bidirectional Transformers",
                "abstract": "BERT is designed to pre-train deep bidirectional representations from unlabeled text.",
            },
        )

        chat_payload = {
            "query": "Explain what BERT does",
            "include_trace": True,
        }
        res = test_client.post("/api/chat", json=chat_payload)
        assert res.status_code == 200
        chat_data = res.json()
        assert "answer" in chat_data
        assert chat_data["intent"] != ""

    def test_trace_endpoint(self, test_client):
        ingest_res = test_client.post(
            "/api/papers/ingest",
            json={
                "title": "FlashAttention: Fast and Memory-Efficient Exact Attention",
                "abstract": "FlashAttention reduces memory accesses between GPU high bandwidth memory and on-chip SRAM.",
            },
        )
        claim_id = ingest_res.json()["claim_node_ids"][0]

        trace_res = test_client.post("/api/trace", json={"node_id": claim_id})
        assert trace_res.status_code == 200
        t_data = trace_res.json()
        assert t_data["answer_node_id"] == claim_id
        assert len(t_data["source_papers"]) >= 1

    def test_stream_emits_documented_progress_events(self, test_client):
        response = test_client.get(
            "/api/stream",
            params={"query": "Trace provenance of this claim"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = []
        for frame in response.text.replace("\r\n", "\n").split("\n\n"):
            lines = frame.splitlines()
            event = next((line[7:] for line in lines if line.startswith("event: ")), None)
            data = next((line[6:] for line in lines if line.startswith("data: ")), None)
            if event and data:
                events.append((event, json.loads(data)))

        names = [event for event, _ in events]
        assert names[0] == "start"
        assert names[-1] == "done"
        assert names.count("agent_completed") >= 1
        start = events[0][1]
        assert isinstance(start["query"], str)
        assert isinstance(start["message"], str)
        for event_name, payload in events[1:-1]:
            assert event_name == "agent_completed"
            assert isinstance(payload["agent"], str)
            assert isinstance(payload["success"], bool)
            assert isinstance(payload["duration_ms"], (int, float))
        done = events[-1][1]
        assert isinstance(done["success"], bool)
        assert isinstance(done["data"], dict)
