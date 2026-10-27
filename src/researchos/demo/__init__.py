"""Curated, offline demo corpus for the ResearchOS workspace.

The corpus contains real arXiv metadata (titles, authors, abstracts, IDs) so a
demo can populate the graph without depending on a live search provider. The
seed function uses the same ingest path as ``POST /api/papers/ingest``: one
paper node plus one claim node per abstract sentence, linked with an
``extracted_from`` edge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from ctxflow import CtxFlow

_CORPUS_PATH = Path(__file__).with_name("corpus.json")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_CLAIMS_PER_PAPER = 8


def load_corpus(path: Path | None = None) -> List[Dict[str, Any]]:
    """Load the checked-in demo papers."""
    corpus_path = path or _CORPUS_PATH
    if not corpus_path.exists():
        raise FileNotFoundError(f"demo corpus does not exist: {corpus_path}")
    with corpus_path.open("r", encoding="utf-8") as handle:
        papers = json.load(handle)
    if not isinstance(papers, list) or not papers:
        raise ValueError("demo corpus must be a non-empty JSON array")
    return papers


def _existing_arxiv_ids(ctxflow: CtxFlow) -> set[str]:
    ids: set[str] = set()
    for node in ctxflow.graph.all_nodes():
        if node.node_type != "paper":
            continue
        arxiv_id = (node.metadata or {}).get("arxiv_id")
        if arxiv_id:
            ids.add(str(arxiv_id))
    return ids


def _claim_sentences(abstract: str) -> List[str]:
    sentences = []
    for sentence in _SENTENCE_RE.split(abstract or ""):
        cleaned = " ".join(sentence.split())
        if len(cleaned) >= 20:
            sentences.append(cleaned)
        if len(sentences) >= _MAX_CLAIMS_PER_PAPER:
            break
    return sentences


def seed_demo_corpus(
    ctxflow: CtxFlow,
    *,
    project_id: str = "default",
    papers: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Ingest the demo corpus into ``ctxflow`` (idempotent per arXiv ID)."""
    records = papers if papers is not None else load_corpus()
    existing = _existing_arxiv_ids(ctxflow)

    papers_ingested = 0
    claims_ingested = 0
    skipped = 0
    for record in records:
        arxiv_id = str(record.get("arxiv_id") or "").strip()
        title = str(record.get("title") or "").strip()
        if not title:
            skipped += 1
            continue
        if arxiv_id and arxiv_id in existing:
            skipped += 1
            continue

        authors = list(record.get("authors") or [])
        year = record.get("year")
        url = str(record.get("url") or "")
        metadata = {
            "project_id": project_id,
            "title": title,
            "authors": authors,
            "year": year,
            "arxiv_id": arxiv_id,
            "url": url,
            "demo_corpus": True,
        }
        paper_content = f"Paper: {title}"
        if authors:
            paper_content += f"\nAuthors: {', '.join(authors[:5])}"
        if year:
            paper_content += f"\nYear: {year}"
        if arxiv_id:
            paper_content += f"\narXiv: {arxiv_id}"

        tags = ctxflow.extractor.extract_tags(f"{title} {record.get('abstract', '')}")
        paper_id = ctxflow.ingest(
            content=paper_content,
            node_type="paper",
            tags=tags,
            metadata=metadata,
            check_contradictions=False,
        )
        papers_ingested += 1

        for sentence in _claim_sentences(str(record.get("abstract") or "")):
            ctxflow.ingest(
                content=sentence,
                node_type="claim",
                source_id=paper_id,
                relation_type="extracted_from",
                tags=tags,
                metadata={
                    **metadata,
                    "source_paper": title,
                    "source_paper_node_id": paper_id,
                },
                check_contradictions=False,
            )
            claims_ingested += 1

        if arxiv_id:
            existing.add(arxiv_id)

    return {
        "papers_ingested": papers_ingested,
        "claims_ingested": claims_ingested,
        "papers_skipped": skipped,
        "project_id": project_id,
        "nodes": ctxflow.graph.node_count,
        "edges": ctxflow.graph.edge_count,
    }
