"""Reader Agent — ingests papers and distils them into CtxFlow nodes.

The Reader takes paper results from the Retriever, downloads/parses PDFs
(when available), extracts structured claims using the PaperReaderSkill,
and ingests them into the CtxFlow knowledge graph with contradiction
detection.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from ctxflow import CtxFlow
from researchos.agents.base import AgentResult, BaseAgent
from researchos.skills.paper_reader import PaperReaderSkill

logger = logging.getLogger(__name__)


class ReaderAgent(BaseAgent):
    """Agent that reads papers and ingests claims into CtxFlow.

    Parameters
    ----------
    ctxflow : CtxFlow
        The CtxFlow instance for knowledge graph ingestion.
    llm : callable | None
        LLM callable for claim extraction.
    """

    def __init__(
        self,
        ctxflow: CtxFlow,
        llm: Optional[Callable[[str, str], str]] = None,
        paper_reader: Optional[PaperReaderSkill] = None,
    ) -> None:
        super().__init__(name="reader", llm=llm)
        self._ctx = ctxflow
        self._paper_reader = paper_reader or PaperReaderSkill(llm=llm)

    def execute(self, **kwargs: Any) -> AgentResult:
        """Read papers and ingest their claims into the knowledge graph.

        Expects ``previous_results`` from the Retriever containing
        ``external_results`` with paper abstracts.

        Parameters
        ----------
        query : str
            The original query.
        context : dict
            Context from the pipeline.
        previous_results : list[AgentResult]
            Previous agent results (expects Retriever output).

        Returns
        -------
        AgentResult
            Contains list of ingested node IDs and paper metadata.
        """
        query: str = kwargs.get("query", "")
        context: Dict[str, Any] = kwargs.get("context", {})
        previous_results: List[AgentResult] = kwargs.get("previous_results", [])

        # Extract external results from retriever output
        papers_data: List[Dict[str, Any]] = []
        for prev in previous_results:
            if prev.agent_name == "retriever" and prev.data:
                papers_data = prev.data.get("external_results", [])
                break

        # Also check context for previous output
        if not papers_data and isinstance(context.get("previous_output"), dict):
            papers_data = context["previous_output"].get("external_results", [])

        ingested_nodes: List[Dict[str, Any]] = []

        for paper in papers_data:
            try:
                node_ids = self._ingest_paper(paper, query)
                ingested_nodes.append({
                    "title": paper.get("title", ""),
                    "node_ids": node_ids,
                    "source": paper.get("source", ""),
                })
            except Exception as exc:
                logger.warning(
                    "Failed to ingest paper '%s': %s",
                    paper.get("title", "unknown"), exc,
                )

        return AgentResult(
            agent_name=self.name,
            success=True,
            data={
                "ingested_papers": ingested_nodes,
                "total_nodes_created": sum(
                    len(p["node_ids"]) for p in ingested_nodes
                ),
            },
            metadata={
                "papers_processed": len(papers_data),
                "papers_ingested": len(ingested_nodes),
            },
        )

    def _ingest_paper(
        self, paper: Dict[str, Any], query: str
    ) -> List[str]:
        """Ingest a single paper's data into the knowledge graph.

        Creates a paper reference node and individual claim nodes
        linked to it.
        """
        title = paper.get("title", "Unknown Paper")
        abstract = paper.get("abstract", "")
        authors = paper.get("authors", [])
        year = paper.get("year")
        doi = paper.get("doi", "")
        arxiv_id = paper.get("arxiv_id", "")

        # Prefer the Paper Reader skill when a local PDF is available.
        extracted_claims: List[Dict[str, Any]] = []
        pdf_path = paper.get("pdf_path")
        if pdf_path:
            try:
                info = self._paper_reader.read_pdf(str(pdf_path))
                if not paper.get("title") and info.get("title"):
                    title = info["title"]
                extracted_claims = [
                    {
                        "type": claim.claim_type,
                        "text": claim.text,
                        "confidence": claim.confidence,
                        "tags": claim.tags,
                    }
                    for claim in self._paper_reader.extract_claims(str(pdf_path))
                ]
            except Exception as exc:
                logger.warning(
                    "Paper Reader failed for %s (%s); falling back to abstract",
                    pdf_path,
                    exc,
                )

        # 1. Create paper reference node
        paper_content = f"Paper: {title}"
        if authors:
            paper_content += f"\nAuthors: {', '.join(authors[:5])}"
        if year:
            paper_content += f"\nYear: {year}"
        if doi:
            paper_content += f"\nDOI: {doi}"

        existing = self._find_duplicate(title, arxiv_id, doi)
        if existing is not None:
            return [existing]

        paper_metadata = {
            "title": title,
            "authors": authors,
            "year": year,
            "doi": doi,
            "arxiv_id": arxiv_id,
            "url": paper.get("url", ""),
        }

        paper_tags = set()
        # Extract tags from title
        for word in title.lower().split():
            cleaned = word.strip(".,;:!?()[]{}\"'")
            if len(cleaned) > 3:
                paper_tags.add(cleaned)

        paper_node_id = self._ctx.ingest(
            content=paper_content,
            node_type="paper",
            tags=paper_tags,
            metadata=paper_metadata,
            check_contradictions=False,
        )

        node_ids = [paper_node_id]

        # 2. Ingest claims from the PDF, full content, or abstract.
        if not extracted_claims:
            source_text = paper.get("content") or abstract
            if source_text:
                extracted_claims = self._extract_abstract_claims(source_text)

        for claim in extracted_claims:
            claim_text = claim.get("text", "").strip()
            if not claim_text:
                continue
            claim_tags = set(claim.get("tags", []))
            claim_tags.update(paper_tags)

            claim_node_id = self._ctx.ingest(
                content=claim_text[:500],
                node_type=claim.get("type", "claim"),
                source_id=paper_node_id,
                relation_type="extracted_from",
                tags=claim_tags,
                metadata={
                    "confidence": claim.get("confidence", 0.5),
                    "source_paper": title,
                    "source_doi": doi,
                },
                check_contradictions=True,
            )
            node_ids.append(claim_node_id)

        return node_ids

    def _find_duplicate(self, title: str, arxiv_id: str, doi: str) -> Optional[str]:
        title_key = " ".join(title.lower().split())
        for node in self._ctx.graph.all_nodes():
            if node.node_type != "paper":
                continue
            meta = node.metadata or {}
            if arxiv_id and str(meta.get("arxiv_id") or "") == arxiv_id:
                return node.id
            if doi and str(meta.get("doi") or "") == doi:
                return node.id
            existing_title = " ".join(str(meta.get("title") or "").lower().split())
            if title_key and existing_title == title_key:
                return node.id
        return None

    def _extract_abstract_claims(
        self, abstract: str
    ) -> List[Dict[str, Any]]:
        """Extract claims from an abstract using LLM or heuristics."""
        if self._llm:
            try:
                from ctxflow.llm_extractor import LLMExtractor
                extractor = LLMExtractor(llm=self._llm)
                return extractor.extract_claims(abstract)
            except Exception as exc:
                logger.warning(
                    "LLM claim extraction failed (%s), using heuristic", exc
                )

        # Heuristic fallback: split abstract into sentences
        import re
        sentences = re.split(r'(?<=[.!?])\s+', abstract)
        claims: List[Dict[str, Any]] = []

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 20:
                continue

            words = re.findall(r'\b[a-zA-Z]{4,}\b', sentence.lower())
            stop = {"this", "that", "with", "from", "have", "been", "also", "which", "their"}
            tags = [w for w in words if w not in stop][:5]

            claims.append({
                "type": "claim",
                "text": sentence[:500],
                "confidence": 0.5,
                "tags": tags,
            })

        return claims
