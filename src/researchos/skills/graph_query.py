"""Graph Query Skill — CtxFlow query and provenance wrapper.

Exposes CtxFlow's ``query()`` and ``research_trace()`` methods as
schema-compliant skills that can be invoked by agents through the
SkillRegistry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from ctxflow import CtxFlow
from ctxflow.models import NodeStatus, QueryResult, ResearchTrace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class GraphQueryResult:
    """Simplified query result for skill consumers.

    Attributes
    ----------
    node_id : str
        The matched node ID.
    content : str
        Node content text.
    summary : str
        Node summary.
    score : float
        Relevance score.
    node_type : str
        Node type label.
    status : str
        Node status (active, superseded, contested).
    tags : list[str]
        Node tags.
    score_breakdown : dict
        Per-component score details.
    """

    node_id: str = ""
    content: str = ""
    summary: str = ""
    score: float = 0.0
    node_type: str = ""
    status: str = "active"
    tags: List[str] = field(default_factory=list)
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class TraceResult:
    """Simplified research trace for skill consumers.

    Attributes
    ----------
    answer_node_id : str
        The traced node.
    provenance_chain : list[dict]
        Steps in the provenance chain.
    superseded_claims : list[dict]
        Superseded nodes in the chain.
    contradictions : list[dict]
        Contradicting nodes and edges.
    source_papers : list[dict]
        Source paper nodes.
    """

    answer_node_id: str = ""
    provenance_chain: List[Dict[str, Any]] = field(default_factory=list)
    superseded_claims: List[Dict[str, Any]] = field(default_factory=list)
    contradictions: List[Dict[str, Any]] = field(default_factory=list)
    source_papers: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GraphQuerySkill
# ---------------------------------------------------------------------------

class GraphQuerySkill:
    """Skill wrapping CtxFlow's query and provenance methods.

    Parameters
    ----------
    ctxflow : CtxFlow
        The CtxFlow instance to query against.
    """

    def __init__(self, ctxflow: CtxFlow) -> None:
        self._ctx = ctxflow

    def query(
        self,
        query_text: str,
        k: int = 5,
        anchor: Optional[str] = None,
        include_superseded: bool = False,
        token_budget: Optional[int] = None,
    ) -> List[GraphQueryResult]:
        """Query the knowledge graph.

        Parameters
        ----------
        query_text : str
            Natural-language query.
        k : int
            Maximum results.
        anchor : str | None
            Anchor node for proximity scoring.
        include_superseded : bool
            Whether to include superseded nodes.
        token_budget : int | None
            If set, greedily pack results within this token budget
            (approximated at 4 chars per token).

        Returns
        -------
        list[GraphQueryResult]
        """
        raw_results: List[QueryResult] = self._ctx.query(
            context=query_text,
            k=k * 2 if token_budget else k,  # Over-fetch if budget filtering
            anchor=anchor,
            include_superseded=include_superseded,
        )

        results: List[GraphQueryResult] = []
        total_tokens = 0
        chars_per_token = 4  # Approximate

        for qr in raw_results:
            node = qr.node
            node_tokens = len(node.content) // chars_per_token

            if token_budget and total_tokens + node_tokens > token_budget:
                continue

            total_tokens += node_tokens
            results.append(GraphQueryResult(
                node_id=node.id,
                content=node.content,
                summary=node.summary,
                score=qr.score,
                node_type=node.node_type,
                status=node.status if isinstance(node.status, str) else node.status.value,
                tags=sorted(node.tags),
                score_breakdown=qr.score_breakdown,
            ))

            if len(results) >= k:
                break

        return results

    def research_trace(self, node_id: str) -> TraceResult:
        """Build a research trace for a node.

        Parameters
        ----------
        node_id : str
            The node to trace.

        Returns
        -------
        TraceResult
        """
        trace: ResearchTrace = self._ctx.research_trace(node_id)

        chain_steps = []
        for step in trace.supporting_chain.steps:
            step_dict: Dict[str, Any] = {
                "node_id": step.node.id,
                "content": step.node.content,
                "summary": step.node.summary,
                "node_type": step.node.node_type,
                "status": step.node.status if isinstance(step.node.status, str) else step.node.status.value,
            }
            if step.edge:
                step_dict["edge"] = {
                    "source_id": step.edge.source_id,
                    "target_id": step.edge.target_id,
                    "relation_type": step.edge.relation_type,
                    "weight": step.edge.weight,
                }
            chain_steps.append(step_dict)

        superseded = [
            {
                "node_id": n.id,
                "content": n.content,
                "superseded_by": n.superseded_by,
            }
            for n in trace.superseded_claims
        ]

        contradictions = [
            {
                "node_id": n.id,
                "content": n.content,
                "edge_relation": e.relation_type,
                "confidence": e.metadata.get("confidence", 0.0),
                "evidence": e.metadata.get("evidence", ""),
            }
            for n, e in trace.contradicting_claims
        ]

        sources = [
            {
                "node_id": n.id,
                "content": n.content,
                "node_type": n.node_type,
                "tags": sorted(n.tags),
            }
            for n in trace.source_papers
        ]

        return TraceResult(
            answer_node_id=trace.answer_node_id,
            provenance_chain=chain_steps,
            superseded_claims=superseded,
            contradictions=contradictions,
            source_papers=sources,
        )

    def get_graph_stats(self) -> Dict[str, Any]:
        """Return summary statistics about the knowledge graph."""
        graph = self._ctx.graph
        all_nodes = graph.all_nodes()

        status_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        for node in all_nodes:
            status = node.status if isinstance(node.status, str) else node.status.value
            status_counts[status] = status_counts.get(status, 0) + 1
            type_counts[node.node_type] = type_counts.get(node.node_type, 0) + 1

        return {
            "total_nodes": graph.node_count,
            "total_edges": graph.edge_count,
            "status_distribution": status_counts,
            "type_distribution": type_counts,
        }
