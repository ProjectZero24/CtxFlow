---
name: researchos-orchestration
description: "Implement and maintain ResearchOS research-agent orchestration in the CtxFlow repository: deterministic intent routing, agent pipelines, run lifecycle, human confirmation, and resumable runs."
---

# ResearchOS Orchestration Skill

## Mission

Own the agent workflow for ResearchOS. Extend the existing orchestration in `src/researchos/agents/`; do not rewrite working architecture without evidence that it is necessary.

This repository does **not** use LangGraph, checkpointing, or a Laya model. Orchestration is a deterministic keyword router that executes an ordered list of `BaseAgent` subclasses. If the team wants a graph runtime or a learned router later, that is a new, separately justified decision — not an assumption to build on.

## Current implementation (verified at `34cf19f`)

Read these files before planning:

- `src/researchos/agents/base.py` — `BaseAgent` (`run()` adds timing/error handling and calls the abstract `execute()`), `AgentResult`, `AgentMessage`, `AgentStatus`.
- `src/researchos/agents/router.py` — `QueryIntent` (`NEW_LITERATURE`, `EXISTING_KNOWLEDGE`, `CLAIM_VERIFICATION`, `EXPLORATORY_TRACE`, `UNKNOWN`), `classify_intent()` (regex keyword scoring, no model call), `_EXECUTION_PLANS`, `SkillRouter`.
- `src/researchos/agents/{retriever,reader,synthesizer,critic,trace}.py` — the five agents.
- `src/researchos/api/server.py` — `create_app()` wires CtxFlow, skills, and agents in `lifespan`; `/api/chat` and SSE `/api/stream` call the router.
- `src/researchos/api/schemas.py` — the only Pydantic API schema module today.
- `tests/test_agents.py`, `tests/test_api.py`, `tests/test_workspace_api.py`.

Behavior that already exists:

- `classify_intent(query) -> QueryIntent` by counting regex matches in `_INTENT_PATTERNS`.
- `_EXECUTION_PLANS` maps intent → ordered agent names:
  - `NEW_LITERATURE`: `retriever → reader → synthesizer → critic`
  - `EXISTING_KNOWLEDGE`: `synthesizer → critic`
  - `CLAIM_VERIFICATION`: `critic` (with a standalone `verify_claim()` fallback)
  - `EXPLORATORY_TRACE`: `graph_query` (`TraceAgent`)
  - `UNKNOWN`: `synthesizer → critic`
- `SkillRouter` (invoked as `BaseAgent.run(query=...)`) runs the plan sequentially, passes `previous_results` and `context` forward, skips failed agents (logging the error), and returns an `AgentResult` with `data = {intent, plan, result, pipeline_results}`.
- `POST /api/chat` returns `answer`, `intent`, `cited_nodes`, `alerts`, optional `trace`.
- `GET /api/stream?query=...` emits SSE events `start`, one `agent_completed` per agent, then `done`.
- `create_app()` registers agents by name: `retriever`, `reader`, `synthesizer`, `critic`, `graph_query`.

What does **not** exist: run records, run IDs, status persistence, checkpointing, resume-after-crash, plan generation, user plan confirmation, retry policy, cancellation, parallel branches, or a learned/Laya router. Do not describe those as implemented.

## Before coding

1. Read `src/researchos/agents/router.py`, `src/researchos/agents/base.py`, `src/researchos/api/server.py`, `src/researchos/api/routes/chat.py`, and the five agents.
2. Run `pytest -q tests/test_agents.py tests/test_api.py tests/test_workspace_api.py` and report the actual result.
3. Identify what is implemented versus documented/planned. Never claim unverified features work.
4. Read `src/researchos/api/schemas.py` and agree any interface change with the other owners before editing it.
5. Write a short implementation plan referencing actual file paths and the specific gap it closes.

## Ownership

- `SkillRouter`, intent classification, and `_EXECUTION_PLANS`.
- Agent composition and the `execute()` contract shared by agents.
- Run lifecycle additions: plan, confirmation state, status, cancellation, retries, resume.
- Invocation of retrieval, reading, context, synthesis, and critique through agent interfaces.
- Unit and workflow tests for routing, transitions, failures, and resume.

Out of scope: CtxFlow graph internals, PDF parsing, citation validation, the static UI, and the CtxFlow memory adapter.

## Required workflow

Preserve the current deterministic pipeline as the baseline. If you add confirmation/resume, implement this bounded flow rather than rebuilding the router:

`plan -> await confirmation -> retrieve -> read -> extract evidence -> retrieve project context -> synthesize -> critique -> persist run`

Design constraints:

- Represent `planning`, `awaiting_confirmation`, `running`, `completed`, `failed`, and `cancelled` explicitly. Today only `AgentStatus` (`idle/running/completed/failed`) exists, and it is per-agent, not per-run.
- Persist enough run state to resume without repeating expensive retrieval/reading. `CtxFlow.export()`/`import_()` is graph-only; it is not a run store. Prefer a small `ResearchRun` record (in `src/researchos/api/schemas.py` or a new `src/researchos/runs/` module) behind an agreed interface; do not silently add a database.
- Keep failure visible: an agent returning `success=False` is currently swallowed by the pipeline. If you change that, update `/api/chat` and SSE consumers in the same PR.
- `/api/chat` currently calls the synchronous `run()` directly inside an `async def`, which blocks the event loop. `GET /api/stream` correctly offloads with `run_in_executor`. If you touch run execution, fix this consistently and add a test.

## Contracts

Use the existing types; do not invent a parallel schema package.

```python
# src/researchos/agents/base.py
class BaseAgent(ABC):
    def run(self, **kwargs) -> AgentResult: ...
    @abstractmethod
    def execute(self, **kwargs) -> AgentResult: ...

# src/researchos/agents/router.py
class SkillRouter(BaseAgent):
    def register_agent(self, name: str, agent: BaseAgent) -> None: ...
    def execute(self, **kwargs: Any) -> AgentResult: ...
    # reads kwargs["query"] (required) and kwargs["context"] (optional)
```

Agents receive `query: str`, `context: dict`, and `previous_results: list[AgentResult]`; they return an `AgentResult` whose `.data` is a plain dict. Preserve these keys because the API and UI read them:

- `data["answer"]`, `data["cited_nodes"]`, `data["alerts"]`, `data["trace"]` (trace/verification paths)
- router envelope: `data["intent"]`, `data["plan"]`, `data["result"]`, `data["pipeline_results"]`

For cross-workstream data:

- Retrieval output: `data["internal_results"]`, `data["external_results"]`, `data["knowledge_gap"]`.
- Memory/context: the memory owner proposes an adapter over `ctxflow.memory.MemoryStore` (see the memory skill). There is no `ContextProvider` in this repo yet; do not import one that does not exist.
- Shared models: `src/researchos/api/schemas.py` today. If a new run/plan model is needed, add it there (or a `src/researchos/api/schemas/` package) in one small PR and update all consumers.

Do not independently invent duplicate schemas. Propose changes to the team and update shared models once.

## Router boundary

`classify_intent()` is a strong baseline: deterministic, testable, and free. Keep it unless measurement shows it fails. If a learned router (including anything Laya-derived) is proposed later, it must:

- return one of the existing `QueryIntent` values (or an explicitly added one),
- be validated against an allowlist,
- fall back to `classify_intent()` on error or low confidence,
- ship with a comparison against the keyword baseline.

Do not make a model call on the critical path of the MVP baseline.

## Non-goals

- Do not add LangGraph, a checkpointing framework, or an agent swarm to match old design docs.
- Do not build paper search, PDF parsing, or citation validation inside orchestration; call the evidence interfaces.
- Do not build the frontend.
- Do not rewrite `CtxFlow` or replace `SkillRouter` in the same change that adds run state.
- Do not introduce unbounded loops or new infrastructure without a measured need.

## Acceptance criteria

- A user can submit a question and get a routed answer from the existing pipeline without regressions.
- Any new lifecycle states/transitions are explicit, validated, and covered by tests (normal, invalid transition, failed agent, retry/resume).
- Search/evidence/context/synthesis are called through agreed interfaces, not duplicated.
- If run persistence/resume is added, it works after a process restart and is documented.
- Tool/model failures are visible and never fabricated into results.
- `pytest -q` still passes, and the exact command/result is reported.

## Working agreement

Use a feature branch (`feat/<short-name>`), keep changes within orchestration-owned files where possible, and make small PRs. Coordinate before modifying shared schemas, `create_app()`, or API routes. Keep the integration branch runnable and report actual test results.
