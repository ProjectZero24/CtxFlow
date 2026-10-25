"""Trace Agent — provenance exploration for ``EXPLORATORY_TRACE`` queries.

The proposal's routing table maps exploratory queries
("trace the lineage", "where did this claim come from") to a
GraphQuery → Provenance Tracer path. This agent implements that path
without an LLM: it retrieves the best-matching node and returns its
research trace plus a short human-readable summary.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ctxflow import CtxFlow
from researchos.agents.base import AgentResult, BaseAgent
from researchos.skills.graph_query import GraphQuerySkill, GraphQueryResult

logger = logging.getLogger(__name__)


class TraceAgent(BaseAgent):
    """Agent that finds a claim and exposes its provenance chain.

    Parameters
    ----------
    ctxflow : CtxFlow
        The graph to search and trace.
    k : int
        Number of candidate nodes to inspect when locating the claim.
    """

    def __init__(
        self,
        ctxflow: CtxFlow,
        k: int = 5,
        llm: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        super().__init__(name="graph_query", llm=llm)
        self._ctx = ctxflow
        self._graph_skill = GraphQuerySkill(ctxflow)
        self.k = k

    def execute(self, **kwargs: Any) -> AgentResult:
        """Trace the provenance of the best-matching node for *query*."""
        query: str = kwargs.get("query", "")
        if not query:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="No query provided.",
            )

        candidates: List[GraphQueryResult] = self._graph_skill.query(
            query_text=query,
            k=self.k,
            include_superseded=True,
        )
        if not candidates:
            return AgentResult(
                agent_name=self.name,
                success=True,
                data={
                    "answer": (
                        "No matching node was found in the knowledge graph, "
                        "so there is no provenance to trace."
                    ),
                    "cited_nodes": [],
                    "alerts": [],
                    "trace": None,
                },
                metadata={"intent": "exploratory_trace", "candidates": 0},
            )

        target = candidates[0]
        trace = self._graph_skill.research_trace(target.node_id)

        alerts: List[Dict[str, Any]] = []
        for node in trace.superseded_claims:
            alerts.append({
                "type": "superseded",
                "node_id": node["node_id"],
                "superseded_by": node.get("superseded_by"),
                "message": (
                    f"Claim [{node['node_id']}] in this chain was superseded."
                ),
            })
        for contradiction in trace.contradictions:
            alerts.append({
                "type": "contradiction",
                "node_id": contradiction["node_id"],
                "message": (
                    f"Node [{contradiction['node_id']}] "
                    f"{contradiction['edge_relation']} this claim."
                ),
            })

        chain_length = len(trace.provenance_chain)
        source_count = len(trace.source_papers)
        answer = (
            f"Traced claim [{target.node_id}] through "
            f"{chain_length} provenance step(s) to "
            f"{source_count} source paper(s)."
        )
        if trace.superseded_claims:
            answer += (
                f" {len(trace.superseded_claims)} superseded claim(s) were "
                "found in the chain."
            )
        if trace.contradictions:
            answer += (
                f" {len(trace.contradictions)} contradiction(s) were found."
            )

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "answer": answer,
                "cited_nodes": [target.node_id],
                "alerts": alerts,
                "trace": {
                    "answer_node_id": trace.answer_node_id,
                    "provenance_chain": trace.provenance_chain,
                    "superseded_claims": trace.superseded_claims,
                    "contradictions": trace.contradictions,
                    "source_papers": trace.source_papers,
                },
            },
            metadata={
                "intent": "exploratory_trace",
                "candidates": len(candidates),
                "chain_length": chain_length,
                "source_papers": source_count,
            },
        )
