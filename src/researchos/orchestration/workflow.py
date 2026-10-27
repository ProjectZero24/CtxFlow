"""Bounded agentic research workflow.

Stages A–H from the MVP brief. Control flow is ordinary Python (and a
LangGraph StateGraph when the optional extra is installed). Models only
fill typed slots; tool calls are allowlisted.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ctxflow import CtxFlow
from researchos.agents.router import QueryIntent, classify_intent
from researchos.guardrails import (
    ALLOWED_TOOLS,
    GuardVerdict,
    allow_tool,
    detect_injection,
    guard_query,
    wrap_untrusted,
)
from researchos.orchestration.state import ResearchState, make_event
from researchos.pipeline import make_router, redact_secrets
from researchos.skills.literature_search import LiteratureSearchSkill
from researchos.skills.paper_reader import PaperReaderSkill

logger = logging.getLogger(__name__)

STAGES = (
    "plan",
    "retrieve",
    "read",
    "memory",
    "pack",
    "synthesize",
    "verify",
    "persist",
)

EventCallback = Callable[[Dict[str, Any]], None]

_SYNTHESIS_JSON_SYSTEM = (
    "You are a research synthesizer. Use ONLY the supplied evidence nodes. "
    "Do not invent citations, papers, or node IDs. If evidence is insufficient, "
    "say so. Return JSON with keys: direct_answer, supporting_evidence "
    "(list of {node_id, note}), contradictory_evidence (list of {node_id, note}), "
    "uncertainties (list of strings), citation_ids (list of node id strings that "
    "appear in the evidence), follow_ups (list of strings)."
)


class ResearchWorkflow:
    """Execute one research run against a project graph."""

    def __init__(
        self,
        ctxflow: CtxFlow,
        *,
        literature_search: Optional[LiteratureSearchSkill] = None,
        paper_reader: Optional[PaperReaderSkill] = None,
        llm: Any = None,
        persist: Optional[Callable[[], None]] = None,
        max_wall_s: float = 90.0,
        max_tool_calls: int = 12,
    ) -> None:
        self.ctxflow = ctxflow
        self.literature_search = literature_search
        self.paper_reader = paper_reader
        self.llm = llm
        self.persist = persist
        self.max_wall_s = max_wall_s
        self.max_tool_calls = max_tool_calls

    def run(
        self,
        query: str,
        *,
        run_id: str,
        project_id: str = "default",
        token_budget: int = 2048,
        on_event: Optional[EventCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, Any]:
        started = time.monotonic()
        events: List[Dict[str, Any]] = []

        def emit(stage: str, status: str, message: str = "", data: Optional[Dict[str, Any]] = None) -> None:
            event = make_event(
                run_id=run_id,
                stage=stage,
                status=status,
                message=message,
                data=redact_secrets(data or {}),
            )
            events.append(event)
            if on_event is not None:
                on_event(event)

        guard = guard_query(query)
        state: ResearchState = {
            "run_id": run_id,
            "project_id": project_id,
            "query": query,
            "token_budget": max(1, int(token_budget)),
            "plan": list(STAGES),
            "allowed_tools": sorted(ALLOWED_TOOLS),
            "alerts": [],
            "errors": [],
            "cited_nodes": [],
            "packed_node_ids": [],
            "excluded_node_ids": [],
            "ingested_papers": [],
            "internal_results": [],
            "external_results": [],
            "degraded": False,
            "cancelled": False,
            "verdict": "",
            "answer": "",
        }

        if not guard.allowed:
            emit("plan", "blocked", guard.reason, guard.to_dict())
            state["verdict"] = "INSUFFICIENT_EVIDENCE"
            state["answer"] = guard.reason
            state["alerts"] = [
                {"type": "guardrail", "message": guard.reason, **guard.to_dict()}
            ]
            return self._finalize(state, events, success=False, status="failed")

        router = make_router(
            self.ctxflow,
            literature_search=self.literature_search,
            paper_reader=self.paper_reader,
            llm=self.llm,
            token_budget=state["token_budget"],
        )
        retriever = router._agents["retriever"]
        reader = router._agents["reader"]
        synthesizer = router._agents["synthesizer"]
        critic = router._agents["critic"]

        try:
            if self._timed_out(started) or self._cancelled(cancel_event, state, emit):
                return self._finalize(state, events, success=False, status="cancelled" if state.get("cancelled") else "failed")

            emit("plan", "started", "Classifying intent and building a bounded plan.")
            intent = classify_intent(query)
            state["intent"] = intent.value
            need_external = intent in (
                QueryIntent.NEW_LITERATURE,
                QueryIntent.UNKNOWN,
                QueryIntent.CLAIM_VERIFICATION,
            )
            state["need_external"] = need_external
            emit(
                "plan",
                "completed",
                f"Intent {intent.value}; external retrieval {'enabled' if need_external else 'only if memory is insufficient'}.",
                {"intent": intent.value, "plan": list(STAGES), "allowed_tools": state["allowed_tools"]},
            )

            if self._timed_out(started) or self._cancelled(cancel_event, state, emit):
                return self._finalize(state, events, success=False, status="cancelled" if state.get("cancelled") else "failed")

            emit("retrieve", "started", "Querying project memory.")
            tool_guard = allow_tool("graph_query")
            if not tool_guard.allowed:
                raise RuntimeError(tool_guard.reason)
            retrieve_result = retriever.run(query=query, max_results=8)
            retrieve_data = retrieve_result.data or {}
            state["internal_results"] = retrieve_data.get("internal_results") or []
            knowledge_gap = bool(retrieve_data.get("knowledge_gap"))
            external_search = retrieve_data.get("external_search")
            if not need_external and not knowledge_gap:
                # Memory is sufficient; skip live literature search even if the
                # retriever would have searched (it already decided via gap).
                pass
            if knowledge_gap:
                search_guard = allow_tool("literature_search")
                if not search_guard.allowed:
                    retrieve_data["external_search"] = {
                        "status": "error",
                        "errors": {"guardrail": search_guard.reason},
                    }
            state["external_results"] = retrieve_data.get("external_results") or []
            state["external_search"] = external_search
            if isinstance(external_search, dict) and external_search.get("status") in {
                "error",
                "partial",
            }:
                state["degraded"] = True
            if not retrieve_result.success:
                state["degraded"] = True
                state["errors"].append(retrieve_result.error or "retriever failed")
            emit(
                "retrieve",
                "completed" if retrieve_result.success else "degraded",
                "Memory search finished.",
                {
                    "knowledge_gap": knowledge_gap,
                    "internal_count": len(state["internal_results"]),
                    "external_count": len(state["external_results"]),
                    "external_search": external_search,
                },
            )

            if self._timed_out(started) or self._cancelled(cancel_event, state, emit):
                return self._finalize(state, events, success=False, status="cancelled" if state.get("cancelled") else "failed")

            emit("read", "started", "Extracting claims from retrieved papers.")
            if state["external_results"]:
                read_guard = allow_tool("paper_reader")
                if read_guard.allowed:
                    read_result = reader.run(
                        query=query,
                        context={"previous_output": retrieve_data},
                        previous_results=[retrieve_result],
                    )
                    read_data = read_result.data or {}
                    state["ingested_papers"] = read_data.get("ingested_papers") or []
                    emit(
                        "read",
                        "completed",
                        f"Ingested {len(state['ingested_papers'])} paper(s).",
                        {
                            "ingested_papers": state["ingested_papers"],
                            "total_nodes_created": read_data.get("total_nodes_created", 0),
                        },
                    )
                else:
                    emit("read", "blocked", read_guard.reason, read_guard.to_dict())
            else:
                emit("read", "skipped", "No new papers to read; using project memory.")

            emit("memory", "started", "Persisting project graph.")
            if self.persist is not None:
                self.persist()
            emit(
                "memory",
                "completed",
                "Project graph saved.",
                {
                    "nodes": self.ctxflow.graph.node_count,
                    "edges": self.ctxflow.graph.edge_count,
                },
            )

            if self._timed_out(started) or self._cancelled(cancel_event, state, emit):
                return self._finalize(state, events, success=False, status="cancelled" if state.get("cancelled") else "failed")

            emit("pack", "started", "Packing evidence into the token budget.")
            synth_result = synthesizer.run(
                query=query,
                context={"token_budget": state["token_budget"]},
            )
            synth_data = synth_result.data or {}
            packed_ids = list(synth_data.get("cited_nodes") or [])
            state["packed_node_ids"] = packed_ids
            usage = synth_result.metadata or {}
            retrieved_n = int(usage.get("nodes_retrieved") or 0)
            used_n = int(usage.get("nodes_used") or len(packed_ids))
            state["context_usage"] = {
                "nodes_retrieved": retrieved_n,
                "nodes_used": used_n,
                "nodes_dropped": int(usage.get("nodes_dropped") or max(0, retrieved_n - used_n)),
                "tokens_used": usage.get("tokens_used"),
                "token_budget": usage.get("token_budget", state["token_budget"]),
                "selected_node_ids": packed_ids,
            }
            emit(
                "pack",
                "completed",
                "Context packer selected evidence nodes.",
                state["context_usage"],
            )

            emit("synthesize", "started", "Generating an evidence-grounded answer.")
            structured = self._maybe_structured_answer(query, packed_ids)
            if structured:
                state["structured"] = structured
                answer = self._format_structured(structured)
                cited = [
                    item
                    for item in structured.get("citation_ids") or packed_ids
                    if isinstance(item, str)
                ]
                state["answer"] = answer
                state["cited_nodes"] = cited or packed_ids
            else:
                state["answer"] = synth_data.get("answer") or ""
                state["cited_nodes"] = packed_ids
                if not synth_result.success:
                    state["degraded"] = True
                    state["errors"].append(synth_result.error or "synthesis failed")
            state["alerts"] = list(synth_data.get("alerts") or [])
            emit(
                "synthesize",
                "completed" if not state.get("degraded") else "degraded",
                "Answer drafted from packed evidence.",
                {
                    "cited_nodes": state["cited_nodes"],
                    "structured": bool(structured),
                    "degraded": state.get("degraded"),
                },
            )

            emit("verify", "started", "Resolving citations against persisted evidence.")
            critic_result = critic.run(
                query=query,
                context={
                    "previous_output": {
                        "answer": state["answer"],
                        "cited_nodes": state["cited_nodes"],
                        "alerts": state["alerts"],
                    },
                    "packed_node_ids": packed_ids,
                },
                previous_results=[synth_result],
            )
            critic_data = critic_result.data or {}
            extra_alerts = self._citation_guard(
                state["cited_nodes"], packed_ids, self.ctxflow
            )
            alerts = list(critic_data.get("alerts") or []) + extra_alerts
            verdict = str(critic_data.get("verdict") or "INSUFFICIENT_EVIDENCE")
            if extra_alerts:
                if any(item.get("type") == "invalid_citation" for item in extra_alerts):
                    verdict = "WARNINGS_FOUND"
                if not state["cited_nodes"]:
                    verdict = "INSUFFICIENT_EVIDENCE"
            state["verdict"] = verdict
            state["validations"] = critic_data.get("validations") or []
            state["alerts"] = alerts
            emit(
                "verify",
                "completed",
                f"Verification verdict: {verdict}",
                {
                    "verdict": verdict,
                    "validations": state["validations"],
                    "alerts": alerts,
                },
            )

            emit("persist", "started", "Saving the research run.")
            if self.persist is not None:
                self.persist()
            emit("persist", "completed", "Run record ready.")
        except Exception as exc:  # noqa: BLE001 — surface as a failed run, never fake success
            logger.exception("Research workflow failed")
            state["errors"].append(str(exc))
            state["degraded"] = True
            emit("persist", "failed", str(exc))
            return self._finalize(state, events, success=False, status="failed")

        success = not state.get("errors")
        status = "degraded" if state.get("degraded") and success else ("completed" if success else "failed")
        return self._finalize(state, events, success=success, status=status)

    def _maybe_structured_answer(
        self, query: str, packed_ids: List[str]
    ) -> Optional[Dict[str, Any]]:
        llm = self.llm
        complete_json = getattr(llm, "complete_json", None)
        if not callable(complete_json) or not packed_ids:
            return None
        evidence_blocks = []
        for node_id in packed_ids:
            node = self.ctxflow.graph.get_node(node_id)
            if node is None:
                continue
            evidence_blocks.append(
                wrap_untrusted(
                    f"[Node:{node.id}] ({node.node_type}) {node.summary or node.content[:400]}",
                    source=f"node:{node.id}",
                )
            )
        prompt = (
            f"Question: {query}\n\nEvidence:\n"
            + "\n\n".join(evidence_blocks)
            + "\n\nAllowed node IDs: "
            + ", ".join(packed_ids)
        )
        try:
            parsed = complete_json(prompt, system=_SYNTHESIS_JSON_SYSTEM)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Structured synthesis failed: %s", exc)
            return None
        if not isinstance(parsed, dict):
            return None
        citations = parsed.get("citation_ids") or []
        if isinstance(citations, list):
            parsed["citation_ids"] = [
                item for item in citations if isinstance(item, str) and item in packed_ids
            ]
        return parsed

    @staticmethod
    def _format_structured(payload: Dict[str, Any]) -> str:
        parts = [str(payload.get("direct_answer") or "").strip()]
        supporting = payload.get("supporting_evidence") or []
        if supporting:
            parts.append("Supporting evidence:")
            for item in supporting:
                if isinstance(item, dict):
                    parts.append(
                        f"- [{item.get('node_id')}] {item.get('note') or ''}".strip()
                    )
        contradictory = payload.get("contradictory_evidence") or []
        if contradictory:
            parts.append("Contradictory or limiting evidence:")
            for item in contradictory:
                if isinstance(item, dict):
                    parts.append(
                        f"- [{item.get('node_id')}] {item.get('note') or ''}".strip()
                    )
        uncertainties = payload.get("uncertainties") or []
        if uncertainties:
            parts.append("Uncertainties:")
            for item in uncertainties:
                parts.append(f"- {item}")
        follow_ups = payload.get("follow_ups") or []
        if follow_ups:
            parts.append("Suggested follow-ups:")
            for item in follow_ups:
                parts.append(f"- {item}")
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _citation_guard(
        cited: List[str], packed_ids: List[str], ctxflow: CtxFlow
    ) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        packed = set(packed_ids)
        for node_id in cited:
            node = ctxflow.graph.get_node(node_id)
            if node is None:
                alerts.append(
                    {
                        "type": "invalid_citation",
                        "node_id": node_id,
                        "message": f"Cited node [{node_id}] does not exist in project memory.",
                    }
                )
                continue
            status = node.status if isinstance(node.status, str) else node.status.value
            if status == "superseded":
                alerts.append(
                    {
                        "type": "superseded",
                        "node_id": node_id,
                        "superseded_by": node.superseded_by,
                        "message": f"Cited node [{node_id}] is superseded and is not current evidence.",
                    }
                )
            if packed and node_id not in packed:
                alerts.append(
                    {
                        "type": "invalid_citation",
                        "node_id": node_id,
                        "message": (
                            f"Cited node [{node_id}] was not in the packed context."
                        ),
                    }
                )
        return alerts

    def _timed_out(self, started: float) -> bool:
        return (time.monotonic() - started) > self.max_wall_s

    @staticmethod
    def _cancelled(
        cancel_event: Optional[threading.Event],
        state: ResearchState,
        emit: EventCallback,
    ) -> bool:
        if cancel_event is not None and cancel_event.is_set():
            state["cancelled"] = True
            emit("persist", "cancelled", "Run cancelled.")
            return True
        return False

    def _finalize(
        self,
        state: ResearchState,
        events: List[Dict[str, Any]],
        *,
        success: bool,
        status: str,
    ) -> Dict[str, Any]:
        return {
            "run_id": state.get("run_id"),
            "project_id": state.get("project_id"),
            "query": state.get("query"),
            "status": status,
            "success": success,
            "intent": state.get("intent"),
            "plan": state.get("plan"),
            "stage": events[-1]["stage"] if events else "plan",
            "answer": state.get("answer") or "",
            "verdict": state.get("verdict") or "",
            "cited_nodes": state.get("cited_nodes") or [],
            "packed_node_ids": state.get("packed_node_ids") or [],
            "alerts": state.get("alerts") or [],
            "validations": state.get("validations") or [],
            "context_usage": state.get("context_usage") or {},
            "external_search": state.get("external_search"),
            "ingested_papers": state.get("ingested_papers") or [],
            "structured": state.get("structured") or {},
            "errors": state.get("errors") or [],
            "degraded": bool(state.get("degraded")),
            "events": events,
            "graph_nodes": self.ctxflow.graph.node_count,
            "graph_edges": self.ctxflow.graph.edge_count,
        }


def maybe_langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return False
    return True
