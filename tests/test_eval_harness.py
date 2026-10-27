"""Tests for the evaluation harness, baselines, and metrics."""

from __future__ import annotations

import json

from researchos.eval import BenchmarkRunner, get_default_contradiction_benchmark
from researchos.eval.baselines import (
    FlatVectorStore,
    HashingEmbedder,
    MultiAgentFlatRAG,
    SingleAgentFlatRAG,
)
from researchos.eval.metrics import EvaluationMetrics, estimate_tokens
from researchos.eval.__main__ import main as eval_main


class TestMetrics:
    def test_estimate_tokens(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("abcd") == 1
        assert estimate_tokens("a" * 9) == 1
        assert estimate_tokens("a b!") == 3

    def test_record_supersession_and_provenance(self):
        suite = get_default_contradiction_benchmark()
        question = suite.questions[0]

        good = EvaluationMetrics(system_name="good")
        good.record(
            question,
            retrieved_texts=question.expected_active_claims,
            cited_sources=question.ground_truth_sources,
            context_text=question.expected_active_claims[0],
            trace_found=True,
        )
        assert good.answer_accuracy == 1.0
        assert good.supersession_defense_rate == 1.0
        assert good.provenance_accuracy == 1.0

        cited_without_trace = EvaluationMetrics(system_name="citation-only")
        cited_without_trace.record(
            question,
            retrieved_texts=question.expected_active_claims,
            cited_sources=question.ground_truth_sources,
            context_text=question.expected_active_claims[0],
            trace_found=False,
        )
        assert cited_without_trace.provenance_accuracy == 0.0

        bad = EvaluationMetrics(system_name="bad")
        bad.record(
            question,
            retrieved_texts=question.expected_superseded_claims,
            cited_sources=["p1", "p2"],
            context_text=question.expected_superseded_claims[0],
            trace_found=False,
        )
        assert bad.answer_accuracy == 0.0
        assert bad.supersession_defense_rate == 0.0
        assert bad.provenance_accuracy == 0.0


class TestBaselines:
    def test_hashing_embedder_is_deterministic(self):
        embedder = HashingEmbedder(dimensions=64)
        first = embedder.embed("graph memory retrieval")
        second = embedder.embed("graph memory retrieval")
        assert first == second
        assert abs(sum(value * value for value in first) - 1.0) < 1e-9
        assert HashingEmbedder.cosine(first, second) > 0.99

    def test_flat_store_ranks_relevant_document_first(self):
        store = FlatVectorStore(k=2)
        store.ingest("a", "graph memory with contradiction edges")
        store.ingest("b", "unrelated cooking recipe")
        hits = store.search("contradiction edges in graph memory", k=2)
        assert hits[0].document.id == "a"

    def test_flat_baselines_smoke(self):
        suite = get_default_contradiction_benchmark()
        for system_cls in (SingleAgentFlatRAG, MultiAgentFlatRAG):
            system = system_cls(k=3)
            system.index_suite(suite)
            answer = system.answer(suite.questions[0])
            assert answer.retrieved_texts
            assert answer.cited_sources
            assert answer.system_name


class TestBenchmarkRunner:
    def test_three_systems_are_compared(self):
        runner = BenchmarkRunner(get_default_contradiction_benchmark())
        metrics = runner.run_benchmark()

        assert set(metrics) == {
            "ctxflow_graph",
            "flat_rag",
            "flat_rag_multi_agent",
        }
        graph = metrics["ctxflow_graph"]
        flat = metrics["flat_rag"]

        assert graph.answer_accuracy >= flat.answer_accuracy
        assert graph.supersession_defense_rate > flat.supersession_defense_rate
        assert graph.provenance_accuracy > flat.provenance_accuracy
        assert graph.avg_context_tokens > 0

    def test_report_is_json_serializable(self):
        runner = BenchmarkRunner(get_default_contradiction_benchmark())
        report = runner.run_report()
        encoded = json.dumps(report)
        decoded = json.loads(encoded)

        assert decoded["suite"]
        assert decoded["questions"] == 10
        assert decoded["papers"] == 5
        assert len(decoded["question_rationales"]) == 10
        assert all(item["rationale"] for item in decoded["question_rationales"])
        assert decoded["configuration"]["provider"].startswith("none")
        assert decoded["configuration"]["model"] == "none"
        assert decoded["configuration"]["shared_controls"]["retrieval_k"] == 5
        prompt = decoded["configuration"]["runtime_synthesis_prompt"]
        assert len(prompt["system_prompt_sha256"]) == 64
        assert prompt["system_prompt_token_count"] > 0
        assert prompt["tokenizer"] == "simple-v1"
        assert prompt["used_by_benchmark"] is False
        assert len(decoded["systems"]) == 3
        assert "answer_accuracy" in decoded["systems"]["ctxflow_graph"]

    def test_cli_writes_run_provenance_and_limitations(self, tmp_path):
        output = tmp_path / "report.json"
        assert eval_main(["--json", "--out", str(output)]) == 0

        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["run"]["date_utc"]
        assert "researchos.eval" in report["run"]["command"]
        assert report["run"]["source_commit"]
        assert isinstance(report["run"]["working_tree_dirty"], bool)
        assert len(report["run"]["limitations"]) >= 5
        assert report["systems"]["ctxflow_graph"]["system_name"] == "CtxFlow graph (direct query)"

    def test_markdown_report(self):
        runner = BenchmarkRunner(get_default_contradiction_benchmark())
        table = runner.format_report()
        assert "| System |" in table
        assert "ctxflow_graph" in table
        assert "flat_rag" in table
