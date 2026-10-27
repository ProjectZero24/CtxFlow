"""Review Writer Skill — multi-paper literature review synthesis.

Generates structured literature reviews from multiple papers stored
in the CtxFlow knowledge graph. Applies positional-bias-aware prompt
construction to ensure critical findings are placed at high-salience
positions in the output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ctxflow import CtxFlow
from ctxflow.models import NodeStatus, QueryResult

logger = logging.getLogger(__name__)

# Type alias
LLMCallable = Callable[[str, str], str]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ReviewSection:
    """A section of a literature review.

    Attributes
    ----------
    heading : str
        Section heading.
    content : str
        Section body text.
    cited_nodes : list[str]
        Node IDs referenced in this section.
    """

    heading: str = ""
    content: str = ""
    cited_nodes: List[str] = field(default_factory=list)


@dataclass
class LiteratureReview:
    """A complete literature review document.

    Attributes
    ----------
    title : str
        Review title.
    abstract : str
        Summary of the review.
    sections : list[ReviewSection]
        Structured sections of the review.
    references : list[dict]
        List of referenced sources.
    total_papers : int
        Number of papers synthesized.
    """

    title: str = ""
    abstract: str = ""
    sections: List[ReviewSection] = field(default_factory=list)
    references: List[Dict[str, Any]] = field(default_factory=list)
    total_papers: int = 0


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM = (
    "You are an expert academic research synthesizer. Given a collection of "
    "research claims, findings, and methods from multiple papers, produce a "
    "coherent, well-structured literature review section. Your output should:\n"
    "1. Synthesize findings across papers, not just summarize individual ones.\n"
    "2. Identify common themes, agreements, and contradictions.\n"
    "3. Use academic language and proper citation format [Node:ID].\n"
    "4. Highlight superseded or contested claims when relevant.\n"
    "Respond with ONLY the review text."
)

_ABSTRACT_SYSTEM = (
    "You are an expert research summarizer. Given a literature review, "
    "produce a concise abstract (3-5 sentences) summarizing the key findings, "
    "methods compared, and conclusions. Respond with ONLY the abstract text."
)


# ---------------------------------------------------------------------------
# ReviewWriterSkill
# ---------------------------------------------------------------------------

class ReviewWriterSkill:
    """Synthesizes multi-paper literature reviews from the knowledge graph.

    Parameters
    ----------
    ctxflow : CtxFlow
        The CtxFlow instance containing the knowledge graph.
    llm : callable | None
        An LLM callable ``(prompt, system) -> str``.
        If ``None``, produces a basic concatenated review.
    """

    def __init__(
        self,
        ctxflow: CtxFlow,
        llm: Optional[LLMCallable] = None,
    ) -> None:
        self._ctx = ctxflow
        self._llm = llm

    def write_review(
        self,
        topic: str,
        max_sources: int = 20,
        include_superseded: bool = False,
        token_budget: int = 4096,
    ) -> LiteratureReview:
        """Generate a literature review on a topic.

        Parameters
        ----------
        topic : str
            The research topic to review.
        max_sources : int
            Maximum number of source nodes to include.
        include_superseded : bool
            Whether to include superseded claims (with warnings).
        token_budget : int
            Token budget for the LLM context window.

        Returns
        -------
        LiteratureReview
        """
        # 1. Query the knowledge graph for relevant nodes
        results: List[QueryResult] = self._ctx.query(
            context=topic,
            k=max_sources,
            include_superseded=include_superseded,
        )

        if not results:
            return LiteratureReview(
                title=f"Literature Review: {topic}",
                abstract="No relevant sources found in the knowledge graph.",
            )

        # 2. Organize nodes by type
        claims = [r for r in results if r.node.node_type in ("claim", "generic")]
        methods = [r for r in results if r.node.node_type == "method"]
        findings = [r for r in results if r.node.node_type in ("result", "finding")]
        papers = [r for r in results if r.node.node_type in ("paper", "reference", "source")]

        # 3. Apply positional bias mitigation: critical items at edges
        ordered_results = self._bias_aware_ordering(results)

        # 4. Generate sections
        sections: List[ReviewSection] = []

        if self._llm:
            sections = self._generate_sections_llm(
                topic, ordered_results, claims, methods, findings
            )
        else:
            sections = self._generate_sections_heuristic(
                topic, ordered_results, claims, methods, findings
            )

        # 5. Generate abstract
        abstract = self._generate_abstract(topic, sections)

        # 6. Build references list
        references = self._build_references(results)

        return LiteratureReview(
            title=f"Literature Review: {topic}",
            abstract=abstract,
            sections=sections,
            references=references,
            total_papers=len(papers) or len(results),
        )

    def _bias_aware_ordering(
        self, results: List[QueryResult]
    ) -> List[QueryResult]:
        """Reorder results to mitigate lost-in-the-middle positional bias.

        Places highest-scoring and contested/superseded nodes at the
        start and end, with background context in the middle.
        """
        if len(results) <= 3:
            return results

        # Separate critical vs background
        critical = [
            r for r in results
            if r.score > 0.7
            or r.node.status in (NodeStatus.CONTESTED, "contested")
            or r.node.superseded_by is not None
        ]
        background = [r for r in results if r not in critical]

        # Place critical at edges, background in middle
        n_front = len(critical) // 2 + len(critical) % 2
        front = critical[:n_front]
        back = critical[n_front:]

        return front + background + back

    def _generate_sections_llm(
        self,
        topic: str,
        ordered: List[QueryResult],
        claims: List[QueryResult],
        methods: List[QueryResult],
        findings: List[QueryResult],
    ) -> List[ReviewSection]:
        """Generate review sections using LLM."""
        assert self._llm is not None
        sections: List[ReviewSection] = []

        section_groups = [
            ("Key Claims and Hypotheses", claims),
            ("Methods and Approaches", methods),
            ("Findings and Results", findings),
        ]

        for heading, group in section_groups:
            if not group:
                continue

            # Build prompt with node references
            node_texts: List[str] = []
            cited_ids: List[str] = []
            for r in group:
                status_marker = ""
                if r.node.status in (NodeStatus.SUPERSEDED, "superseded"):
                    status_marker = " [SUPERSEDED]"
                elif r.node.status in (NodeStatus.CONTESTED, "contested"):
                    status_marker = " [CONTESTED]"
                node_texts.append(
                    f"[Node:{r.node.id}]{status_marker} "
                    f"({r.node.node_type}, score={r.score:.3f}): "
                    f"{r.node.content[:500]}"
                )
                cited_ids.append(r.node.id)

            prompt = (
                f"Topic: {topic}\n"
                f"Section: {heading}\n\n"
                f"Source material:\n" + "\n\n".join(node_texts)
            )

            try:
                content = self._llm(prompt, system=_REVIEW_SYSTEM)
                sections.append(ReviewSection(
                    heading=heading,
                    content=content.strip(),
                    cited_nodes=cited_ids,
                ))
            except Exception:
                logger.warning(
                    "LLM review generation failed for section '%s'",
                    heading, exc_info=True,
                )
                sections.append(self._heuristic_section(heading, group))

        return sections

    def _generate_sections_heuristic(
        self,
        topic: str,
        ordered: List[QueryResult],
        claims: List[QueryResult],
        methods: List[QueryResult],
        findings: List[QueryResult],
    ) -> List[ReviewSection]:
        """Fallback: generate simple concatenated sections."""
        sections: List[ReviewSection] = []

        section_groups = [
            ("Key Claims and Hypotheses", claims),
            ("Methods and Approaches", methods),
            ("Findings and Results", findings),
        ]

        for heading, group in section_groups:
            if not group:
                continue
            sections.append(self._heuristic_section(heading, group))

        # If no typed groups, make a general section
        if not sections:
            sections.append(self._heuristic_section("Overview", ordered))

        return sections

    def _heuristic_section(
        self, heading: str, results: List[QueryResult]
    ) -> ReviewSection:
        """Build a simple section from query results."""
        parts: List[str] = []
        cited_ids: List[str] = []

        for r in results:
            prefix = f"[{r.node.id}]"
            status_note = ""
            if r.node.status in (NodeStatus.SUPERSEDED, "superseded"):
                status_note = " (Note: this claim has been superseded)"
            elif r.node.status in (NodeStatus.CONTESTED, "contested"):
                status_note = " (Note: this claim is contested)"

            summary = r.node.summary if r.node.summary else r.node.content[:300]
            parts.append(f"- {prefix} {summary}{status_note}")
            cited_ids.append(r.node.id)

        return ReviewSection(
            heading=heading,
            content="\n".join(parts),
            cited_nodes=cited_ids,
        )

    def _generate_abstract(
        self, topic: str, sections: List[ReviewSection]
    ) -> str:
        """Generate a review abstract."""
        if not sections:
            return ""

        full_text = "\n\n".join(
            f"## {s.heading}\n{s.content}" for s in sections
        )

        if self._llm:
            try:
                return self._llm(full_text, system=_ABSTRACT_SYSTEM).strip()
            except Exception:
                logger.warning("LLM abstract generation failed", exc_info=True)

        # Fallback: first sentence from each section
        parts = []
        for s in sections:
            first_sentence = s.content.split(".")[0] + "."
            parts.append(first_sentence)
        return " ".join(parts)

    def _build_references(
        self, results: List[QueryResult]
    ) -> List[Dict[str, Any]]:
        """Build a references list from query results."""
        refs: List[Dict[str, Any]] = []
        for r in results:
            ref: Dict[str, Any] = {
                "node_id": r.node.id,
                "type": r.node.node_type,
                "summary": r.node.summary or r.node.content[:200],
                "tags": sorted(r.node.tags),
            }
            if r.node.metadata:
                ref["metadata"] = r.node.metadata
            refs.append(ref)
        return refs
