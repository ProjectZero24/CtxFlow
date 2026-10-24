"""Unit tests for ResearchOS Evaluation Harness and Benchmark Suite."""

from __future__ import annotations

import pytest

from researchos.eval.benchmark import BenchmarkRunner
from researchos.eval.dataset import get_default_contradiction_benchmark


class TestEvaluationHarness:
    """Tests for truth maintenance and contradiction benchmark runner."""

    def test_default_contradiction_suite(self):
        suite = get_default_contradiction_benchmark()
        assert len(suite.papers) >= 3
        assert len(suite.questions) >= 2

        runner = BenchmarkRunner(suite)
        results = runner.run_benchmark()

        assert "ctxflow_graph" in results
        assert "flat_rag" in results

        ctx_metrics = results["ctxflow_graph"]
        flat_metrics = results["flat_rag"]

        # CtxFlow graph memory must suppress superseded claims
        assert ctx_metrics.superseded_claims_suppressed > 0
        assert ctx_metrics.supersession_defense_rate > flat_metrics.supersession_defense_rate

        # CtxFlow must preserve provenance traces
        assert ctx_metrics.provenance_traces_found > 0
