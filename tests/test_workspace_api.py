"""Tests for the workspace UI, notes API, and routing agents."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from ctxflow import CtxFlow
from researchos.agents.router import SkillRouter
from researchos.agents.synthesizer import (
    SYNTHESIS_SYSTEM_PROMPT_SHA256,
    SynthesizerAgent,
    synthesis_prompt_accounting,
)
from researchos.api.server import create_app


@pytest.fixture
def client():
    with TestClient(create_app(ctxflow=CtxFlow())) as test_client:
        yield test_client


@pytest.fixture
def controlled_provider_client():
    ctxflow = CtxFlow()
    calls = []
    cited_ids = []

    def controlled_provider(prompt: str, system: str) -> str:
        calls.append({"prompt": prompt, "system": system})
        return f"Controlled provider answer [Node:{cited_ids[0]}]"

    router = SkillRouter(
        agents={
            "synthesizer": SynthesizerAgent(ctxflow=ctxflow, llm=controlled_provider),
        }
    )
    with TestClient(create_app(ctxflow=ctxflow, router_agent=router)) as test_client:
        yield test_client, calls, cited_ids


class TestWorkspaceUI:
    def test_index_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "ResearchOS" in response.text
        assert "/app.js" in response.text
        assert 'id="chat-status" role="status" aria-live="polite"' in response.text
        assert 'id="health-label" role="status" aria-live="polite"' in response.text
        assert "graph and chat" in response.text
        assert "plan review and" in response.text
        assert 'list="recent-projects"' in response.text
        assert 'id="project-open" type="button">Open label</button>' in response.text
        assert "Only project labels are remembered in this browser" in response.text
        assert 'id="project-status" role="status" aria-live="polite"' in response.text

    def test_static_assets_are_served(self, client):
        assert client.get("/app.js").status_code == 200
        assert client.get("/styles.css").status_code == 200

    def test_workspace_distinguishes_unavailable_and_empty_states(self, client):
        script = client.get("/app.js").text
        assert "Loading graph" in script
        assert "Graph unavailable" in script
        assert "No papers ingested for this project yet." in script
        assert "Unresolvable citation" in script
        assert "Empty result: the stream ended without an answer." in script
        assert "End-to-end completion semantics are not defined by this API." in script
        assert '"Access status"' in script
        assert "Not provided by API; full-text access is unverified" in script
        assert "renderEvidenceMetadata" in script
        assert 'metadata.section || "Not provided by API"' in script
        assert 'metadata.page ?? "Not provided by API"' in script
        assert "Inspect evidence" in script
        assert "Page/section not provided by API" in script
        assert 'id="stream-progress"' in client.get("/").text
        assert 'id="stream-steps" role="log" aria-live="polite"' in client.get("/").text
        assert 'new EventSource(`/api/stream?query=${encodeURIComponent(query)}`)' in script
        assert 'addEventListener("agent_completed"' in script
        assert 'addEventListener("done"' in script
        assert "End-to-end completion semantics are not defined by this API." in script
        assert "Blocked steps: not reported by API" in script
        assert "No superseded claims recorded for this trace." in script
        assert "No contradictions recorded for this trace." in script
        assert "traceRequestId" in script
        assert 'el("button", "chip", "Export Markdown")' in script
        assert "async function markdownReport" in script
        assert "function citationIds(answer, reportedIds)" in script
        assert r"/\[(?:Node:)?([A-Za-z0-9_-]{6,})\]/g" in script
        assert 'jsonRequest("/api/trace", { node_id: nodeId })' in script
        assert "Citation ${nodeId} is not present in the loaded graph." in script
        assert "The API returned no citations for this answer." in script
        assert "function formatErrorDetail(detail)" in script
        assert 'location ? `${location}: ${message}` : message' in script
        assert '$("#health-label").textContent = "API unavailable"' in script
        assert 'Health check failed: ${error.message}' in script


class TestS5EndToEnd:
    def test_synthesizer_records_prompt_accounting_metadata(self):
        ctxflow = CtxFlow()
        ctxflow.ingest(
            "A reproducible source supports deterministic prompt accounting.",
            node_type="claim",
        )
        provider_calls = []

        def controlled_provider(prompt: str, system: str) -> str:
            provider_calls.append({"prompt": prompt, "system": system})
            return "Prompt-accounted answer"

        result = SynthesizerAgent(
            ctxflow=ctxflow,
            llm=controlled_provider,
        ).execute(query="Explain the reproducible source")

        assert result.success
        assert provider_calls
        assert result.metadata["system_prompt_sha256"] == hashlib.sha256(
            provider_calls[0]["system"].encode("utf-8")
        ).hexdigest()
        assert result.metadata["tokenizer"] == "simple-v1"
        assert result.metadata["system_prompt_token_count"] > 0
        assert (
            result.metadata["estimated_total_prompt_tokens"]
            > result.metadata["system_prompt_token_count"]
        )

    def test_controlled_provider_answer_trace_and_sse(self, controlled_provider_client):
        client, provider_calls, expected_citations = controlled_provider_client
        index = client.get("/")
        assert index.status_code == 200
        assert 'src="/app.js"' in index.text

        ingested = client.post(
            "/api/papers/ingest",
            json={
                "title": "Controlled E2E source",
                "abstract": (
                    "A controlled evaluation fixture establishes that the "
                    "evidence trail is reproducible and traceable."
                ),
            },
        )
        assert ingested.status_code == 200
        claim_id = ingested.json()["claim_node_ids"][0]
        expected_citations.append(claim_id)

        chat = client.post(
            "/api/chat",
            json={"query": "Explain the controlled evaluation result", "include_trace": True},
        )
        assert chat.status_code == 200
        chat_data = chat.json()
        assert chat_data["answer"] == f"Controlled provider answer [Node:{claim_id}]"
        assert claim_id in chat_data["cited_nodes"]
        assert chat_data["trace"]["answer_node_id"] == claim_id
        assert chat_data["trace"]["chain_length"] >= 1

        stream = client.get(
            "/api/stream",
            params={"query": "Explain the controlled evaluation result"},
        )
        assert stream.status_code == 200
        frames = []
        for frame in stream.text.replace("\r\n", "\n").split("\n\n"):
            lines = frame.splitlines()
            event_name = next(
                (line[7:] for line in lines if line.startswith("event: ")),
                None,
            )
            data_line = next(
                (line[6:] for line in lines if line.startswith("data: ")),
                None,
            )
            if event_name and data_line:
                frames.append((event_name, json.loads(data_line)))

        event_names = [event_name for event_name, _ in frames]
        assert event_names[0] == "start"
        assert event_names[-1] == "done"
        assert "agent_completed" in event_names
        done = frames[-1][1]
        assert done["data"]["result"]["answer"] == chat_data["answer"]
        assert provider_calls
        for call in provider_calls:
            assert hashlib.sha256(call["system"].encode("utf-8")).hexdigest() == SYNTHESIS_SYSTEM_PROMPT_SHA256
            assert call["prompt"].startswith("Question: Explain the controlled evaluation result")

        accounting = synthesis_prompt_accounting(
            "Explain the controlled evaluation result",
            "test context",
        )
        assert accounting["system_prompt_sha256"] == SYNTHESIS_SYSTEM_PROMPT_SHA256
        assert accounting["estimated_total_prompt_tokens"] > accounting["system_prompt_token_count"]

    def test_default_provider_free_setup_smoke(self, client):
        assert client.get("/").status_code == 200
        assert client.get("/health").json()["status"] == "ok"

        ingested = client.post(
            "/api/papers/ingest",
            json={
                "title": "Default setup smoke source",
                "abstract": (
                    "The default ResearchOS pipeline retains a reproducible "
                    "evidence trail for this smoke test."
                ),
            },
        )
        assert ingested.status_code == 200
        claim_id = ingested.json()["claim_node_ids"][0]

        streamed = client.get(
            "/api/stream",
            params={"query": "Explain the reproducible evidence trail"},
        )
        assert streamed.status_code == 200
        done = [
            json.loads(frame.split("data: ", 1)[1].splitlines()[0])
            for frame in streamed.text.replace("\r\n", "\n").split("\n\n")
            if frame.startswith("event: done\n")
        ]
        assert len(done) == 1
        result = done[0]["data"]["result"]
        assert isinstance(result["answer"], str) and result["answer"]
        assert claim_id in result["answer"]

        chat = client.post(
            "/api/chat",
            json={"query": "Explain the reproducible evidence trail"},
        )
        assert chat.status_code == 200
        assert claim_id in chat.json()["answer"]
        trace = client.post("/api/trace", json={"node_id": claim_id})
        assert trace.status_code == 200
        assert trace.json()["answer_node_id"] == claim_id
        assert trace.json()["source_papers"]


class TestNotes:
    def test_create_and_list_notes(self, client):
        created = client.post(
            "/api/notes",
            json={
                "title": "Leakage hypothesis",
                "content": "The 85% accuracy may be inflated by test leakage.",
                "project_id": "thesis",
                "tags": ["accuracy"],
            },
        )
        assert created.status_code == 200
        note = created.json()
        assert note["node_id"]
        assert note["project_id"] == "thesis"
        assert "note" in note["tags"]

        listed = client.get("/api/notes?project_id=thesis")
        assert listed.status_code == 200
        data = listed.json()
        assert data["total"] == 1
        assert data["notes"][0]["title"] == "Leakage hypothesis"

        # Project isolation.
        other = client.get("/api/notes?project_id=other").json()
        assert other["total"] == 0


class TestRoutingAgents:
    def test_exploratory_trace_route_returns_provenance(self, client):
        ingest = client.post(
            "/api/papers/ingest",
            json={
                "title": "Graph Memory for Agents",
                "abstract": (
                    "Graph memory retains provenance links between claims "
                    "and their source papers."
                ),
            },
        ).json()

        response = client.post(
            "/api/chat",
            json={"query": "Trace the provenance and lineage of this claim"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "exploratory_trace"
        assert "provenance" in data["answer"].lower()
        assert ingest["paper_node_id"]

    def test_claim_verification_route_returns_verdict_text(self, client):
        client.post(
            "/api/papers/ingest",
            json={
                "title": "LoRA",
                "abstract": (
                    "LoRA freezes pretrained weights and injects trainable "
                    "rank decomposition matrices."
                ),
            },
        )

        response = client.post(
            "/api/chat",
            json={"query": "Verify the claim about LoRA rank decomposition"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "claim_verification"
        assert data["answer"]


class TestPaperIngestMetadata:
    def test_project_and_contradiction_fields(self, client):
        response = client.post(
            "/api/papers/ingest",
            json={
                "project_id": "thesis",
                "title": "Scaling Laws",
                "abstract": (
                    "Language model loss scales as a power law with compute."
                ),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "thesis"
        assert data["contradictions_found"] == 0

    def test_graph_data_exposes_real_paper_metadata_for_inspection(self, client):
        created = client.post(
            "/api/papers/ingest",
            json={
                "project_id": "thesis",
                "title": "Traceable Source",
                "authors": ["A. Researcher", "B. Scientist"],
                "year": 2025,
                "doi": "10.1234/example",
                "arxiv_id": "2501.01234",
                "url": "https://example.org/paper",
                "abstract": "This source contains a claim sufficiently long to be indexed.",
            },
        )
        assert created.status_code == 200

        graph = client.get("/api/graph/data").json()
        paper = next(node for node in graph["nodes"] if node["node_type"] == "paper")
        claim_ids = {
            edge["target_id"]
            for edge in graph["edges"]
            if edge["source_id"] == paper["id"]
            and edge["relation_type"] == "extracted_from"
        }
        assert paper["metadata"]["title"] == "Traceable Source"
        assert paper["metadata"]["authors"] == ["A. Researcher", "B. Scientist"]
        assert paper["metadata"]["year"] == 2025
        assert paper["metadata"]["doi"] == "10.1234/example"
        assert paper["metadata"]["arxiv_id"] == "2501.01234"
        assert paper["metadata"]["url"] == "https://example.org/paper"
        assert claim_ids == set(created.json()["claim_node_ids"])
