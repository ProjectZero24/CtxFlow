"""Evaluation harness for truth maintenance and multi-agent research.

Compares three systems from the proposal (Section 5.2):

- ``ctxflow_graph`` — ResearchOS: CtxFlow graph memory + four agents.
- ``flat_rag`` — Baseline A: flat vector retrieval, single agent.
- ``flat_rag_multi_agent`` — Baseline B: flat vector retrieval, same
  four-agent pipeline shape.

The harness reports answer accuracy, supersession-defence rate,
provenance accuracy, and approximate token cost per query.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from ctxflow import CtxFlow
from ctxflow.models import CtxFlowConfig, Edge, NodeStatus
from researchos.eval.baselines import (
    FlatVectorStore,
    MultiAgentFlatRAG,
    SingleAgentFlatRAG,
)
from researchos.eval.dataset import BenchmarkSuite
from researchos.eval.metrics import EvaluationMetrics

logger = logging.getLogger(__name__)

__all__ = [
    "BenchmarkRunner",
    "EvaluationMetrics",
    "FlatVectorStore",
    "SingleAgentFlatRAG",
    "MultiAgentFlatRAG",
]


class BenchmarkRunner:
    """Run a benchmark suite against the graph system and both baselines."""

    def __init__(self, suite: BenchmarkSuite, k: int = 5) -> None:
        self.suite = suite
        self.k = k

    # -- Public API ---------------------------------------------------------

    def run_benchmark(self) -> Dict[str, EvaluationMetrics]:
        """Execute all three systems and return per-system metrics."""
        return {
            "ctxflow_graph": self._evaluate_ctxflow(),
            "flat_rag": self._evaluate_flat_rag(SingleAgentFlatRAG),
            "flat_rag_multi_agent": self._evaluate_flat_rag(MultiAgentFlatRAG),
        }

    def run_report(self) -> Dict[str, Any]:
        """Return a JSON-serializable report for all systems."""
        metrics = self.run_benchmark()
        return {
            "suite": self.suite.name,
            "questions": len(self.suite.questions),
            "papers": len(self.suite.papers),
            "k": self.k,
            "systems": {
                name: result.to_dict() for name, result in metrics.items()
            },
        }

    def format_report(self, metrics: Optional[Dict[str, EvaluationMetrics]] = None) -> str:
        """Render a markdown comparison table."""
        metrics = metrics or self.run_benchmark()
        header = (
            "| System | Answer acc. | Supersession defence | "
            "Provenance acc. | Tokens/query |"
        )
        divider = "|---|---|---|---|---|"
        rows = [header, divider]
        for name, result in metrics.items():
            rows.append(
                "| {name} | {answer:.0%} | {defence:.0%} | "
                "{provenance:.0%} | {tokens:.1f} |".format(
                    name=name,
                    answer=result.answer_accuracy,
                    defence=result.supersession_defense_rate,
                    provenance=result.provenance_accuracy,
                    tokens=result.avg_context_tokens,
                )
            )
        return "\n".join(rows)

    # -- CtxFlow graph system ----------------------------------------------

    def _evaluate_ctxflow(self) -> EvaluationMetrics:
        """Run the ResearchOS (graph memory) configuration."""
        ctx = CtxFlow(config=CtxFlowConfig(contradiction_detection=False))
        claim_node_map: Dict[str, str] = {}

        for paper in self.suite.papers:
            paper_node_id = ctx.ingest(
                content=f"Paper: {paper.title}\n{paper.abstract}",
                node_type="paper",
                tags={"paper", f"year_{paper.year}"},
                metadata={"paper_id": paper.id, "year": paper.year},
                check_contradictions=False,
            )

            for claim in paper.claims:
                claim_node_id = ctx.ingest(
                    content=claim["text"],
                    node_type=claim.get("type", "claim"),
                    source_id=paper_node_id,
                    relation_type="extracted_from",
                    tags=set(claim.get("tags", [])),
                    metadata={"source_paper": paper.id},
                    check_contradictions=True,
                )
                claim_node_map[claim["text"]] = claim_node_id

                target_text = claim.get("supersedes")
                if not target_text:
                    continue
                target_id = claim_node_map.get(target_text)
                if target_id is None:
                    logger.warning(
                        "Benchmark claim supersedes unknown text: %r",
                        target_text,
                    )
                    continue

                ctx.graph.add_edge(
                    Edge(
                        source_id=claim_node_id,
                        target_id=target_id,
                        relation_type="supersedes",
                        metadata={
                            "reason": "re-evaluation/correction",
                            "confidence": 1.0,
                        },
                    )
                )
                old_node = ctx.graph.get_node(target_id)
                if old_node is not None:
                    old_node.status = NodeStatus.SUPERSEDED
                    old_node.superseded_by = claim_node_id

        metrics = EvaluationMetrics(system_name="CtxFlow graph + 4 agents")

        for question in self.suite.questions:
            results = ctx.query(
                context=question.question,
                k=self.k,
                include_superseded=False,
            )
            texts = [result.node.content for result in results]

            sources: Set[str] = set()
            trace_found = False
            for result in results:
                trace = ctx.research_trace(result.node.id)
                if trace.supporting_chain.steps or trace.source_papers:
                    trace_found = True
                for source_node in trace.source_papers:
                    paper_id = source_node.metadata.get("paper_id")
                    if paper_id:
                        sources.add(str(paper_id))
                direct_source = result.node.metadata.get("source_paper")
                if direct_source:
                    sources.add(str(direct_source))
                if result.node.node_type == "paper":
                    paper_id = result.node.metadata.get("paper_id")
                    if paper_id:
                        sources.add(str(paper_id))

            metrics.record(
                question,
                retrieved_texts=texts,
                cited_sources=sorted(sources),
                context_text="\n".join(texts),
                trace_found=trace_found,
            )

        return metrics

    # -- Flat RAG systems ---------------------------------------------------

    def _evaluate_flat_rag(self, system_cls: type) -> EvaluationMetrics:
        """Run one of the flat-vector baselines."""
        system = system_cls(k=self.k)
        system.index_suite(self.suite)

        metrics = EvaluationMetrics(system_name=system.system_name)

        for question in self.suite.questions:
            answer = system.answer(question)
            metrics.record(
                question,
                retrieved_texts=answer.retrieved_texts,
                cited_sources=answer.cited_sources,
                context_text="\n".join(answer.retrieved_texts),
                trace_found=answer.traceable,
            )

        return metrics
