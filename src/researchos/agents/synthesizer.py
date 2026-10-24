"""Synthesizer Agent — bias-aware context packing and response synthesis.

The Synthesizer assembles a response from the knowledge graph using
positional-bias-aware prompt construction. It ensures critical findings
and corrections are placed at high-salience positions (start/end) in
the LLM prompt, mitigating the "lost-in-the-middle" phenomenon.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ctxflow import CtxFlow
from ctxflow.models import NodeStatus, QueryResult
from researchos.agents.base import AgentResult, BaseAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = (
    "You are a research synthesis assistant. Given a set of research claims, "
    "findings, and context from a knowledge graph, produce a clear, accurate, "
    "and well-structured answer to the user's question.\n\n"
    "Rules:\n"
    "1. Cite your sources using [Node:ID] format.\n"
    "2. If any claims are marked as SUPERSEDED, note the correction.\n"
    "3. If claims are CONTESTED, present both perspectives.\n"
    "4. Be concise but comprehensive.\n"
    "5. Structure your answer with clear sections when appropriate.\n"
    "Respond with ONLY the answer text."
)

_NO_LLM_HEADER = "Based on the available knowledge graph context:\n\n"


# ---------------------------------------------------------------------------
# SynthesizerAgent
# ---------------------------------------------------------------------------

class SynthesizerAgent(BaseAgent):
    """Bias-aware synthesizer that drafts answers from graph context.

    Parameters
    ----------
    ctxflow : CtxFlow
        The CtxFlow instance for querying.
    llm : callable | None
        LLM callable for synthesis. If ``None``, produces a
        structured concatenation of relevant nodes.
    token_budget : int
        Maximum tokens for the context window.
    """

    def __init__(
        self,
        ctxflow: CtxFlow,
        llm: Optional[Callable[[str, str], str]] = None,
        token_budget: int = 2048,
    ) -> None:
        super().__init__(name="synthesizer", llm=llm)
        self._ctx = ctxflow
        self.token_budget = token_budget

    def execute(self, **kwargs: Any) -> AgentResult:
        """Synthesize a response from knowledge graph context.

        Parameters
        ----------
        query : str
            The user's question.
        context : dict
            Pipeline context (may contain previous_output from Retriever).

        Returns
        -------
        AgentResult
            Contains the synthesized answer, cited node IDs, and
            any supersession alerts.
        """
        query: str = kwargs.get("query", "")

        if not query:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="No query provided.",
            )

        # 1. Retrieve relevant nodes from graph
        results: List[QueryResult] = self._ctx.query(
            context=query,
            k=20,
            include_superseded=False,
        )

        if not results:
            return AgentResult(
                agent_name=self.name,
                success=True,
                data={
                    "answer": "No relevant information found in the knowledge graph.",
                    "cited_nodes": [],
                    "alerts": [],
                },
            )

        # 2. Apply bias-aware ordering
        ordered = self._bias_aware_reorder(results)

        # 3. Pack within token budget
        packed = self._pack_within_budget(ordered)

        # 4. Build the prompt context
        prompt_context = self._build_prompt_context(packed)

        # 5. Generate response
        if self._llm:
            answer = self._synthesize_with_llm(query, prompt_context)
        else:
            answer = self._synthesize_heuristic(query, packed)

        # 6. Collect alerts
        alerts = self._collect_alerts(packed)
        cited_ids = [r.node.id for r in packed]

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "answer": answer,
                "cited_nodes": cited_ids,
                "alerts": alerts,
            },
            metadata={
                "nodes_used": len(packed),
                "token_budget": self.token_budget,
            },
        )

    def _bias_aware_reorder(
        self, results: List[QueryResult]
    ) -> List[QueryResult]:
        """Reorder nodes for positional bias mitigation.

        High-salience items → start and end of context.
        Background context → middle.

        This implements the "Lost-in-the-Middle" mitigation from the
        architecture spec: place highest-scoring nodes and active
        corrections at P₀…Pₖ and P_{n-k}…Pₙ.
        """
        if len(results) <= 4:
            return results

        # Categorize nodes
        high_priority: List[QueryResult] = []
        normal: List[QueryResult] = []

        for r in results:
            is_high = (
                r.score > 0.6
                or r.node.status in (NodeStatus.CONTESTED, "contested")
                or r.node.superseded_by is not None
            )
            if is_high:
                high_priority.append(r)
            else:
                normal.append(r)

        if not high_priority:
            return results

        # Split high-priority between front and back
        mid = len(high_priority) // 2 + len(high_priority) % 2
        front = high_priority[:mid]
        back = high_priority[mid:]

        return front + normal + back

    def _pack_within_budget(
        self, results: List[QueryResult]
    ) -> List[QueryResult]:
        """Greedily pack results within the token budget."""
        chars_per_token = 4
        max_chars = self.token_budget * chars_per_token

        packed: List[QueryResult] = []
        total_chars = 0

        for r in results:
            node_chars = len(r.node.content) + len(r.node.summary or "")
            if total_chars + node_chars > max_chars:
                continue
            total_chars += node_chars
            packed.append(r)

        return packed

    def _build_prompt_context(
        self, results: List[QueryResult]
    ) -> str:
        """Build the formatted context block for the LLM prompt."""
        parts: List[str] = []

        for r in results:
            status_marker = ""
            if r.node.status in (NodeStatus.SUPERSEDED, "superseded"):
                status_marker = " [SUPERSEDED]"
            elif r.node.status in (NodeStatus.CONTESTED, "contested"):
                status_marker = " [CONTESTED]"

            text = r.node.summary if r.node.summary else r.node.content[:400]
            parts.append(
                f"[Node:{r.node.id}]{status_marker} "
                f"(type={r.node.node_type}, score={r.score:.3f}):\n{text}"
            )

        return "\n\n---\n\n".join(parts)

    def _synthesize_with_llm(self, query: str, context: str) -> str:
        """Generate answer using the LLM."""
        assert self._llm is not None

        prompt = f"Question: {query}\n\nContext:\n{context}"
        try:
            return self._llm(prompt, system=_SYNTHESIS_SYSTEM).strip()
        except Exception:
            logger.warning("LLM synthesis failed", exc_info=True)
            return f"[LLM synthesis failed] {_NO_LLM_HEADER}{context}"

    def _synthesize_heuristic(
        self, query: str, results: List[QueryResult]
    ) -> str:
        """Fallback: build a structured response without LLM."""
        parts = [_NO_LLM_HEADER]

        for r in results:
            status_note = ""
            if r.node.status in (NodeStatus.SUPERSEDED, "superseded"):
                status_note = " ⚠️ (superseded)"
            elif r.node.status in (NodeStatus.CONTESTED, "contested"):
                status_note = " ⚠️ (contested)"

            text = r.node.summary if r.node.summary else r.node.content[:300]
            parts.append(f"• [{r.node.id}]{status_note}: {text}")

        return "\n".join(parts)

    def _collect_alerts(
        self, results: List[QueryResult]
    ) -> List[Dict[str, Any]]:
        """Collect supersession and contradiction alerts."""
        alerts: List[Dict[str, Any]] = []

        for r in results:
            if r.node.status in (NodeStatus.SUPERSEDED, "superseded"):
                alerts.append({
                    "type": "superseded",
                    "node_id": r.node.id,
                    "superseded_by": r.node.superseded_by,
                    "message": f"Claim [{r.node.id}] has been superseded.",
                })
            elif r.node.status in (NodeStatus.CONTESTED, "contested"):
                alerts.append({
                    "type": "contested",
                    "node_id": r.node.id,
                    "message": f"Claim [{r.node.id}] is contested.",
                })

        return alerts
