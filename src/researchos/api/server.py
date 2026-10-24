"""FastAPI Application Server for ResearchOS.

Creates and configures the FastAPI application instance:
- CORS middleware
- Lifespan context for initializing CtxFlow, Skills, and Agents
- SSE (Server-Sent Events) streaming endpoint for live research updates
- REST routes mounting (/api/chat, /api/query, /api/papers, /api/graph, /api/trace, etc.)
- Health checks and skill registry discovery
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from ctxflow import CtxFlow
from ctxflow.models import CtxFlowConfig
from researchos.agents.critic import CriticAgent
from researchos.agents.reader import ReaderAgent
from researchos.agents.retriever import RetrieverAgent
from researchos.agents.router import SkillRouter
from researchos.agents.synthesizer import SynthesizerAgent
from researchos.api.routes import chat as chat_routes
from researchos.api.routes import papers as papers_routes
from researchos.api.schemas import HealthResponse, SkillInfoResponse, SkillListResponse
from researchos.skills.graph_query import GraphQuerySkill
from researchos.skills.literature_search import LiteratureSearchSkill
from researchos.skills.paper_reader import PaperReaderSkill
from researchos.skills.registry import SkillRegistry
from researchos.skills.review_writer import ReviewWriterSkill

logger = logging.getLogger(__name__)


def create_app(
    ctxflow: Optional[CtxFlow] = None,
    skill_registry: Optional[SkillRegistry] = None,
    router_agent: Optional[SkillRouter] = None,
    enable_cors: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    ctxflow : CtxFlow | None
        Existing CtxFlow instance. If None, initialized with in-memory graph.
    skill_registry : SkillRegistry | None
        Existing SkillRegistry instance. If None, created and populated.
    router_agent : SkillRouter | None
        Existing SkillRouter instance. If None, composed with all agents.
    enable_cors : bool
        Whether to enable permissive CORS for web frontends.
    """

    # Shared state container
    state: Dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. Initialize CtxFlow core
        nonlocal ctxflow, skill_registry, router_agent
        if ctxflow is None:
            ctxflow = CtxFlow()
        state["ctxflow"] = ctxflow

        # 2. Initialize Skills
        lit_search = LiteratureSearchSkill()
        paper_reader = PaperReaderSkill()
        graph_query = GraphQuerySkill(ctxflow)
        review_writer = ReviewWriterSkill(ctxflow)

        state["literature_search"] = lit_search
        state["paper_reader"] = paper_reader
        state["graph_query"] = graph_query
        state["review_writer"] = review_writer

        # 3. Populate SkillRegistry
        if skill_registry is None:
            skill_registry = SkillRegistry()

            skill_registry.register_function(
                name="literature_search",
                fn=lit_search.search,
                description="Search academic papers on arXiv and Semantic Scholar.",
                tags=["search", "literature", "arxiv"],
            )
            skill_registry.register_function(
                name="paper_reader",
                fn=paper_reader.read_pdf,
                description="Extract structured sections and text from PDF documents.",
                tags=["pdf", "parsing", "reader"],
            )
            skill_registry.register_function(
                name="graph_query",
                fn=graph_query.query,
                description="Search internal CtxFlow knowledge graph with multi-signal ranking.",
                tags=["graph", "query", "memory"],
            )
            skill_registry.register_function(
                name="research_trace",
                fn=graph_query.research_trace,
                description="Trace provenance, supersession, and contradictions for a claim node.",
                tags=["trace", "provenance", "audit"],
            )
            skill_registry.register_function(
                name="review_writer",
                fn=review_writer.write_review,
                description="Synthesize structured multi-paper literature reviews.",
                tags=["synthesis", "review", "writing"],
            )
        state["skill_registry"] = skill_registry

        # 4. Initialize Multi-Agent Pipeline
        if router_agent is None:
            retriever = RetrieverAgent(ctxflow=ctxflow, literature_search=lit_search)
            reader = ReaderAgent(ctxflow=ctxflow)
            synthesizer = SynthesizerAgent(ctxflow=ctxflow)
            critic = CriticAgent(ctxflow=ctxflow)

            router_agent = SkillRouter(
                agents={
                    "retriever": retriever,
                    "reader": reader,
                    "synthesizer": synthesizer,
                    "critic": critic,
                }
            )
        state["router"] = router_agent

        # 5. Inject dependencies into routes
        chat_routes.set_app_state(state)
        papers_routes.set_app_state(state)

        yield

        # Teardown
        try:
            lit_search.close()
        except Exception:
            pass

    app = FastAPI(
        title="ResearchOS API",
        description="Autonomous Multi-Agent Scientific Research Operating System powered by CtxFlow",
        version="0.2.0",
        lifespan=lifespan,
    )

    if enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Mount Route Modules
    app.include_router(chat_routes.router)
    app.include_router(papers_routes.router)

    # Root & Health Endpoints
    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        c = state.get("ctxflow")
        nodes = c.graph.node_count if c else 0
        edges = c.graph.edge_count if c else 0
        return HealthResponse(
            status="ok",
            version="0.2.0",
            graph_nodes=nodes,
            graph_edges=edges,
        )

    @app.get("/api/skills", response_model=SkillListResponse, tags=["skills"])
    async def list_skills() -> SkillListResponse:
        reg: Optional[SkillRegistry] = state.get("skill_registry")
        if not reg:
            return SkillListResponse(skills=[])
        schemas = reg.list_skills()
        return SkillListResponse(
            skills=[
                SkillInfoResponse(
                    name=s.name,
                    description=s.description,
                    version=s.version,
                    tags=s.tags,
                    input_schema=s.input_schema,
                    output_schema=s.output_schema,
                )
                for s in schemas
            ]
        )

    @app.get("/api/stream", tags=["stream"])
    async def stream_query(query: str, request: Request):
        """SSE streaming endpoint for real-time multi-agent execution events."""
        skill_router: Optional[SkillRouter] = state.get("router")
        if not skill_router:
            raise HTTPException(503, detail="Router agent not initialized")

        async def event_generator() -> AsyncGenerator[Dict[str, Any], None]:
            yield {
                "event": "start",
                "data": json.dumps({"query": query, "message": "Classifying query intent..."}),
            }
            await asyncio.sleep(0.01)

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: skill_router.run(query=query))

            # Stream pipeline progress events
            pipeline_results = (result.data or {}).get("pipeline_results", [])
            for pr in pipeline_results:
                yield {
                    "event": "agent_completed",
                    "data": json.dumps(pr),
                }
                await asyncio.sleep(0.01)

            yield {
                "event": "done",
                "data": json.dumps({
                    "success": result.success,
                    "data": result.data,
                    "metadata": result.metadata,
                }),
            }

        return EventSourceResponse(event_generator())

    return app
