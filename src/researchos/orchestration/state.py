"""Typed workflow state and event records."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, TypedDict

StageName = Literal[
    "plan",
    "retrieve",
    "read",
    "memory",
    "pack",
    "synthesize",
    "verify",
    "persist",
]

RunStatus = Literal[
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "degraded",
]


class ResearchState(TypedDict, total=False):
    run_id: str
    project_id: str
    query: str
    intent: str
    plan: List[str]
    token_budget: int
    need_external: bool
    allowed_tools: List[str]
    internal_results: List[Dict[str, Any]]
    external_results: List[Dict[str, Any]]
    external_search: Optional[Dict[str, Any]]
    ingested_papers: List[Dict[str, Any]]
    packed_node_ids: List[str]
    excluded_node_ids: List[str]
    context_usage: Dict[str, Any]
    answer: str
    cited_nodes: List[str]
    structured: Dict[str, Any]
    verdict: str
    alerts: List[Dict[str, Any]]
    validations: List[Dict[str, Any]]
    errors: List[str]
    degraded: bool
    cancelled: bool
    trace: List[Dict[str, Any]]


def now_ts() -> float:
    return time.time()


def make_event(
    *,
    run_id: str,
    stage: str,
    status: str,
    message: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "event": "stage",
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "message": message,
        "ts": now_ts(),
        "data": data or {},
    }
