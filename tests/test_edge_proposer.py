import json

import pytest
from types import SimpleNamespace

from ctxflow.memory import LLMEdgeProposer, Memory, Relation
from ctxflow.providers.groq import GroqEmptyContentError, GroqLLM


def test_edge_proposer_uses_strict_prompt_and_defined_edges_only():
    calls = []
    target = Memory(id="target", text="The deployment uses Postgres.")
    current = Memory(id="current", text="The database is Postgres.")

    def llm(prompt, system=""):
        calls.append((prompt, system))
        return json.dumps([
            {"target_id": "target", "relation": "related_to", "confidence": 0.9},
        ])

    edges = LLMEdgeProposer(llm).propose(current, [target])

    assert len(edges) == 1
    assert edges[0].src == "current"
    assert edges[0].dst == "target"
    assert edges[0].relation is Relation.RELATED_TO
    assert edges[0].confidence == 0.9
    assert edges[0].created_by == "llm"
    assert "Return ONLY a JSON array" in calls[0][1]
    assert Relation.RELATED_TO.value in calls[0][1]


def test_edge_proposer_rejects_undefined_relations_and_extra_fields():
    target = Memory(id="target", text="candidate")
    current = Memory(id="current", text="new")

    def llm(_prompt, system=""):
        return '[{"target_id":"target","relation":"invented","confidence":1}]'

    with pytest.raises(ValueError, match="unknown target or relation"):
        LLMEdgeProposer(llm).propose(current, [target])


def test_edge_proposer_accepts_valid_empty_json_array():
    target = Memory(id="target", text="candidate")
    current = Memory(id="current", text="new")

    def llm(_prompt, system=""):
        return "[]"

    assert LLMEdgeProposer(llm).propose(current, [target]) == []


def test_groq_distinguishes_empty_content_from_empty_json_array():
    class Completions:
        def __init__(self, content):
            self.content = content

        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                    finish_reason="stop",
                )],
                usage=SimpleNamespace(
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                ),
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions("[]")))
    llm = GroqLLM.__new__(GroqLLM)
    llm._client = client
    llm.model = "test-model"
    llm.temperature = 0.0
    llm.max_tokens = 10
    assert llm("prompt") == "[]"

    llm._client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions("   "))
    )
    with pytest.raises(GroqEmptyContentError, match="empty content"):
        llm("prompt")
