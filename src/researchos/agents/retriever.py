"""Retriever Agent — orchestrates internal graph search vs external API fetch.

The Retriever first checks the CtxFlow knowledge graph for existing
relevant knowledge. If a knowledge gap is identified (too few results
or low scores), it falls back to external literature search via the
LiteratureSearchSkill.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ctxflow import CtxFlow
from researchos.agents.base import AgentResult, BaseAgent
from researchos.skills.graph_query import GraphQueryResult, GraphQuerySkill
from researchos.skills.literature_search import (
    LiteratureSearchSkill,
    PaperResult,
)

logger = logging.getLogger(__name__)


class RetrieverAgent(BaseAgent):
    """Agent that retrieves knowledge from internal graph or external APIs.

    Parameters
    ----------
    ctxflow : CtxFlow
        The CtxFlow instance for internal graph queries.
    literature_search : LiteratureSearchSkill | None
        External search skill. If ``None``, external search is disabled.
    min_internal_results : int
        Minimum graph results before triggering external search.
    min_score_threshold : float
        Minimum average score to consider internal results sufficient.
    """

    def __init__(
        self,
        ctxflow: CtxFlow,
        literature_search: Optional[LiteratureSearchSkill] = None,
        min_internal_results: int = 2,
        min_score_threshold: float = 0.3,
        llm: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        super().__init__(name="retriever", llm=llm)
        self._graph_skill = GraphQuerySkill(ctxflow)
        self._search_skill = literature_search
        self.min_internal_results = min_internal_results
        self.min_score_threshold = min_score_threshold

    def execute(self, **kwargs: Any) -> AgentResult:
        """Retrieve relevant knowledge for a query.

        Parameters
        ----------
        query : str
            The search query.
        context : dict | None
            Additional context.
        max_results : int
            Maximum results to return.

        Returns
        -------
        AgentResult
            Contains ``internal_results`` and optionally ``external_results``.
        """
        query: str = kwargs.get("query", "")
        max_results: int = kwargs.get("max_results", 10)

        if not query:
            return AgentResult(
                agent_name=self.name,
                success=False,
                error="No query provided.",
            )

        # 1. Query internal knowledge graph
        internal_results = self._graph_skill.query(
            query_text=query, k=max_results
        )

        # 2. Evaluate knowledge sufficiency
        has_gap = self._has_knowledge_gap(internal_results)

        result_data: Dict[str, Any] = {
            "internal_results": [
                {
                    "node_id": r.node_id,
                    "content": r.content,
                    "summary": r.summary,
                    "score": r.score,
                    "node_type": r.node_type,
                    "status": r.status,
                    "tags": r.tags,
                }
                for r in internal_results
            ],
            "knowledge_gap": has_gap,
        }

        # 3. If gap detected, search externally
        if has_gap and self._search_skill:
            logger.info(
                "Knowledge gap detected for '%s', searching externally",
                query[:80],
            )
            external_results = self._search_skill.search(
                query=query, max_results=max_results
            )
            result_data["external_results"] = [
                {
                    "title": p.title,
                    "authors": p.authors,
                    "abstract": p.abstract,
                    "year": p.year,
                    "doi": p.doi,
                    "arxiv_id": p.arxiv_id,
                    "url": p.url,
                    "source": p.source,
                }
                for p in external_results
            ]
        else:
            result_data["external_results"] = []

        return AgentResult(
            agent_name=self.name,
            success=True,
            data=result_data,
            metadata={
                "internal_count": len(internal_results),
                "has_knowledge_gap": has_gap,
                "external_count": len(result_data.get("external_results", [])),
            },
        )

    def _has_knowledge_gap(
        self, results: List[GraphQueryResult]
    ) -> bool:
        """Determine if internal results are insufficient."""
        if len(results) < self.min_internal_results:
            return True

        if not results:
            return True

        avg_score = sum(r.score for r in results) / len(results)
        return avg_score < self.min_score_threshold
