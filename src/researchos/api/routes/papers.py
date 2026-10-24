"""Paper & Graph Routes — paper ingestion, graph data, and trace endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from researchos.api.schemas import (
    EdgeResponse,
    GraphDataResponse,
    GraphStatsResponse,
    NodeResponse,
    PaperIngestRequest,
    PaperIngestResponse,
    TraceRequest,
    TraceResponse,
    TraceStepResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["papers", "graph"])


# ---------------------------------------------------------------------------
# Shared app state (injected at startup)
# ---------------------------------------------------------------------------
_app_state: dict = {}


def set_app_state(state: dict) -> None:
    """Inject application state."""
    global _app_state
    _app_state = state


# ---------------------------------------------------------------------------
# Paper Ingestion
# ---------------------------------------------------------------------------

@router.post("/papers/ingest", response_model=PaperIngestResponse)
async def ingest_paper(request: PaperIngestRequest) -> PaperIngestResponse:
    """Ingest a paper into the knowledge graph."""
    ctxflow = _app_state.get("ctxflow")
    if ctxflow is None:
        raise HTTPException(503, detail="CtxFlow not initialized")

    try:
        # Create paper reference node
        paper_content = f"Paper: {request.title}"
        if request.authors:
            paper_content += f"\nAuthors: {', '.join(request.authors[:5])}"
        if request.year:
            paper_content += f"\nYear: {request.year}"
        if request.doi:
            paper_content += f"\nDOI: {request.doi}"

        paper_tags = set()
        for word in request.title.lower().split():
            cleaned = word.strip(".,;:!?()[]{}\"'")
            if len(cleaned) > 3:
                paper_tags.add(cleaned)

        paper_node_id = ctxflow.ingest(
            content=paper_content,
            node_type="paper",
            tags=paper_tags,
            metadata={
                "title": request.title,
                "authors": request.authors,
                "year": request.year,
                "doi": request.doi,
                "arxiv_id": request.arxiv_id,
                "url": request.url,
            },
            check_contradictions=False,
        )

        # Ingest claims from abstract/content
        claim_ids: list = []
        contradictions = 0
        text_to_process = request.abstract or request.content

        if text_to_process:
            import re
            sentences = re.split(r'(?<=[.!?])\s+', text_to_process)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 20:
                    continue

                claim_id = ctxflow.ingest(
                    content=sentence[:500],
                    node_type="claim",
                    source_id=paper_node_id,
                    relation_type="extracted_from",
                    tags=paper_tags,
                    metadata={
                        "source_paper": request.title,
                        "source_doi": request.doi,
                    },
                    check_contradictions=True,
                )
                claim_ids.append(claim_id)

        return PaperIngestResponse(
            success=True,
            paper_node_id=paper_node_id,
            claim_node_ids=claim_ids,
            contradictions_found=contradictions,
            message=f"Ingested paper '{request.title}' with {len(claim_ids)} claims.",
        )
    except Exception as exc:
        logger.error("Paper ingest failed: %s", exc, exc_info=True)
        raise HTTPException(500, detail=str(exc))


# ---------------------------------------------------------------------------
# Graph Data
# ---------------------------------------------------------------------------

@router.get("/graph/stats", response_model=GraphStatsResponse)
async def graph_stats() -> GraphStatsResponse:
    """Get knowledge graph statistics."""
    ctxflow = _app_state.get("ctxflow")
    if ctxflow is None:
        raise HTTPException(503, detail="CtxFlow not initialized")

    graph = ctxflow.graph
    all_nodes = graph.all_nodes()

    status_dist: dict = {}
    type_dist: dict = {}
    for node in all_nodes:
        status = node.status if isinstance(node.status, str) else node.status.value
        status_dist[status] = status_dist.get(status, 0) + 1
        type_dist[node.node_type] = type_dist.get(node.node_type, 0) + 1

    return GraphStatsResponse(
        total_nodes=graph.node_count,
        total_edges=graph.edge_count,
        status_distribution=status_dist,
        type_distribution=type_dist,
    )


@router.get("/graph/data", response_model=GraphDataResponse)
async def graph_data() -> GraphDataResponse:
    """Get full graph data for visualization."""
    ctxflow = _app_state.get("ctxflow")
    if ctxflow is None:
        raise HTTPException(503, detail="CtxFlow not initialized")

    graph = ctxflow.graph
    all_nodes = graph.all_nodes()

    nodes = []
    edges = []

    for node in all_nodes:
        nodes.append(NodeResponse(
            id=node.id,
            content=node.content[:500],
            summary=node.summary,
            node_type=node.node_type,
            status=node.status if isinstance(node.status, str) else node.status.value,
            tags=sorted(node.tags),
            superseded_by=node.superseded_by,
            metadata=node.metadata,
            timestamp=node.timestamp,
        ))

        for edge in graph.get_edges_from(node.id):
            edges.append(EdgeResponse(
                source_id=edge.source_id,
                target_id=edge.target_id,
                relation_type=edge.relation_type,
                weight=edge.weight,
                metadata=edge.metadata,
            ))

    return GraphDataResponse(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# Research Trace
# ---------------------------------------------------------------------------

@router.post("/trace", response_model=TraceResponse)
async def research_trace(request: TraceRequest) -> TraceResponse:
    """Build a research trace for a node."""
    ctxflow = _app_state.get("ctxflow")
    if ctxflow is None:
        raise HTTPException(503, detail="CtxFlow not initialized")

    try:
        trace = ctxflow.research_trace(request.node_id)

        chain_steps = []
        for step in trace.supporting_chain.steps:
            chain_steps.append(TraceStepResponse(
                node_id=step.node.id,
                content=step.node.content[:500],
                summary=step.node.summary,
                node_type=step.node.node_type,
                status=step.node.status if isinstance(step.node.status, str) else step.node.status.value,
                edge_relation=step.edge.relation_type if step.edge else None,
                edge_weight=step.edge.weight if step.edge else None,
            ))

        superseded = [
            NodeResponse(
                id=n.id,
                content=n.content[:500],
                summary=n.summary,
                node_type=n.node_type,
                status=n.status if isinstance(n.status, str) else n.status.value,
                superseded_by=n.superseded_by,
            )
            for n in trace.superseded_claims
        ]

        contradictions = [
            {
                "node_id": n.id,
                "content": n.content[:500],
                "relation": e.relation_type,
                "confidence": e.metadata.get("confidence", 0.0),
                "evidence": e.metadata.get("evidence", ""),
            }
            for n, e in trace.contradicting_claims
        ]

        sources = [
            NodeResponse(
                id=n.id,
                content=n.content[:500],
                summary=n.summary,
                node_type=n.node_type,
                status=n.status if isinstance(n.status, str) else n.status.value,
                tags=sorted(n.tags),
            )
            for n in trace.source_papers
        ]

        return TraceResponse(
            answer_node_id=trace.answer_node_id,
            provenance_chain=chain_steps,
            superseded_claims=superseded,
            contradictions=contradictions,
            source_papers=sources,
        )
    except Exception as exc:
        logger.error("Trace endpoint failed: %s", exc, exc_info=True)
        raise HTTPException(500, detail=str(exc))
