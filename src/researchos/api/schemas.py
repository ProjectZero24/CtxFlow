"""API Schemas — Pydantic request/response models for the FastAPI backend.

Defines all the request/response types used by the API routes,
ensuring strong type validation and automatic OpenAPI documentation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """User chat message request."""

    query: str = Field(..., description="Natural-language query or instruction.")
    session_id: Optional[str] = Field(
        None, description="Session ID for conversation tracking."
    )
    include_trace: bool = Field(
        False, description="Whether to include research trace in the response."
    )
    token_budget: int = Field(
        2048, description="Token budget for context assembly."
    )


class ChatResponse(BaseModel):
    """Response to a chat query."""

    answer: str = Field(..., description="Generated answer.")
    intent: str = Field("", description="Classified query intent.")
    cited_nodes: List[str] = Field(
        default_factory=list, description="IDs of cited nodes."
    )
    alerts: List[Dict[str, Any]] = Field(
        default_factory=list, description="Supersession/contradiction alerts."
    )
    trace: Optional[Dict[str, Any]] = Field(
        None, description="Research trace if requested."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Execution metadata."
    )


# ---------------------------------------------------------------------------
# Paper Ingestion
# ---------------------------------------------------------------------------

class PaperIngestRequest(BaseModel):
    """Request to ingest a paper."""

    title: str = Field("", description="Paper title.")
    abstract: str = Field("", description="Paper abstract.")
    authors: List[str] = Field(
        default_factory=list, description="Author names."
    )
    year: Optional[int] = Field(None, description="Publication year.")
    doi: str = Field("", description="DOI identifier.")
    arxiv_id: str = Field("", description="arXiv identifier.")
    url: str = Field("", description="Paper URL.")
    content: str = Field(
        "", description="Full paper text (alternative to PDF upload)."
    )


class PaperIngestResponse(BaseModel):
    """Response after ingesting a paper."""

    success: bool = True
    paper_node_id: str = Field("", description="ID of the paper reference node.")
    claim_node_ids: List[str] = Field(
        default_factory=list, description="IDs of extracted claim nodes."
    )
    contradictions_found: int = Field(
        0, description="Number of contradictions detected."
    )
    message: str = ""


# ---------------------------------------------------------------------------
# Graph / Node
# ---------------------------------------------------------------------------

class NodeResponse(BaseModel):
    """A single node in the knowledge graph."""

    id: str
    content: str
    summary: str = ""
    node_type: str = "generic"
    status: str = "active"
    tags: List[str] = Field(default_factory=list)
    superseded_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = 0.0


class EdgeResponse(BaseModel):
    """A single edge in the knowledge graph."""

    source_id: str
    target_id: str
    relation_type: str = "related_to"
    weight: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class GraphStatsResponse(BaseModel):
    """Knowledge graph statistics."""

    total_nodes: int = 0
    total_edges: int = 0
    status_distribution: Dict[str, int] = Field(default_factory=dict)
    type_distribution: Dict[str, int] = Field(default_factory=dict)


class GraphDataResponse(BaseModel):
    """Full graph data for visualization."""

    nodes: List[NodeResponse] = Field(default_factory=list)
    edges: List[EdgeResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Research Trace
# ---------------------------------------------------------------------------

class TraceRequest(BaseModel):
    """Request for a research trace."""

    node_id: str = Field(..., description="Node ID to trace.")


class TraceStepResponse(BaseModel):
    """A step in a provenance chain."""

    node_id: str
    content: str
    summary: str = ""
    node_type: str = ""
    status: str = "active"
    edge_relation: Optional[str] = None
    edge_weight: Optional[float] = None


class TraceResponse(BaseModel):
    """Full research trace response."""

    answer_node_id: str
    provenance_chain: List[TraceStepResponse] = Field(default_factory=list)
    superseded_claims: List[NodeResponse] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    source_papers: List[NodeResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    """Knowledge graph query request."""

    query: str = Field(..., description="Natural-language query.")
    k: int = Field(5, description="Number of results.")
    anchor: Optional[str] = Field(None, description="Anchor node for proximity.")
    include_superseded: bool = Field(False, description="Include superseded nodes.")


class QueryResultResponse(BaseModel):
    """A single query result."""

    node_id: str
    content: str
    summary: str = ""
    score: float = 0.0
    node_type: str = ""
    status: str = "active"
    tags: List[str] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    """Query response with ranked results."""

    results: List[QueryResultResponse] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Literature Search
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    """External literature search request."""

    query: str = Field(..., description="Search query.")
    max_results: int = Field(5, description="Max results per provider.")
    provider: str = Field(
        "both", description="Search provider: arxiv, semantic_scholar, or both."
    )


class SearchResultResponse(BaseModel):
    """A single search result."""

    title: str = ""
    authors: List[str] = Field(default_factory=list)
    abstract: str = ""
    year: Optional[int] = None
    doi: str = ""
    arxiv_id: str = ""
    url: str = ""
    source: str = ""


class SearchResponse(BaseModel):
    """Literature search response."""

    results: List[SearchResultResponse] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

class SkillInfoResponse(BaseModel):
    """Information about a registered skill."""

    name: str
    description: str = ""
    version: str = "0.1.0"
    tags: List[str] = Field(default_factory=list)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class SkillListResponse(BaseModel):
    """List of all registered skills."""

    skills: List[SkillInfoResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """API health check response."""

    status: str = "ok"
    version: str = ""
    graph_nodes: int = 0
    graph_edges: int = 0
