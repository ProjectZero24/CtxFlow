# Harikesh — Orchestration & Truth Maintenance Handbook
## Deterministic Control Plane, Run Lifecycle & Audit

| | |
|---|---|
| **Role** | Orchestration owner: routing, agent pipeline, run lifecycle, resumability; plus truth-maintenance policy and audit |
| **Seminar** | *Data Lineage and Correction Propagation for Responsible AI Systems* |
| **Primary skill** | [`researchos_team_skills/researchos-orchestration/SKILL.md`](../../researchos_team_skills/researchos-orchestration/SKILL.md) |
| **Secondary skill** | None as an edit mandate. Read `researchos-frontend-integration-evaluation` for the SSE/UI contract and `researchos-ctxflow-memory` for run-state persistence constraints. |
| **Working branch** | `feat/harikesh-orchestration` |
| **Baseline** | `Adi/feat/v1` @ `810dd54`; `120 passed, 1 skipped` (verified 25 Oct 2026) |
| **Contract freeze** | Fri 30 Oct 2026, 18:00 |

---

## 0. Read this first

1. This file is your complete brief. The primary skill is the verified audit of the code; where they differ, the **skill's code facts** win.
2. Do **not** add LangGraph, checkpointing, or an agent swarm just because the older docs mention them. The repository does not use them today. The MVP plan wants them; the skills forbid them without justification. That is **ADR-001**, and it is the first thing you resolve (§6).
3. Preserve the existing deterministic router until a measurement shows it is wrong. It is the cheapest, most testable part of the system.
4. Run state is the feature; the router is the baseline. Do not rewrite both in one PR.
5. Any change to `src/researchos/api/schemas.py`, `create_app()`, or a route is a shared change. Coordinate with Abinav and Adithyan in the PR.
6. Anything not in MVP plan §1 is out of scope. New ideas go to the deferred list.

---

## 1. Context in 60 seconds

ResearchOS today:

```text
POST /api/chat
  → SkillRouter.run(query=..., context=...)
      → classify_intent()          # regex keyword scoring, no LLM
      → _EXECUTION_PLANS[intent]   # ordered agent names
      → run each agent sequentially, thread data forward
  → return {answer, intent, cited_nodes, alerts, trace?}
```

Intents and plans:

| Intent | Plan |
|---|---|
| `NEW_LITERATURE` | `retriever → reader → synthesizer → critic` |
| `EXISTING_KNOWLEDGE` | `synthesizer → critic` |
| `CLAIM_VERIFICATION` | `critic` (with standalone `verify_claim`) |
| `EXPLORATORY_TRACE` | `graph_query` → `TraceAgent` |
| `UNKNOWN` | `synthesizer → critic` |

What exists:

- `BaseAgent.run()` owns timing and catches **all** exceptions into `AgentResult(success=False)`.
- `SkillRouter` runs plans sequentially, skips failed agents with a log, and envelopes `data` as `{intent, plan, result, pipeline_results}`.
- `/api/chat` calls the synchronous `run()` directly inside an `async def` → **blocks the event loop**.
- `/api/stream` offloads with `run_in_executor` but emits only coarse events: `start`, one `agent_completed` per agent, `done`.
- `CriticAgent` validates cited nodes against graph status/edges; `TraceAgent` produces a provenance answer.

What does **not** exist:

- Run IDs, run records, status persistence, checkpoints, resume-after-crash.
- Plan generation, plan editing, user confirmation.
- Retry policy, cancellation, parallel branches.
- A learned or LLM-based router.
- Live per-agent progress in the UI (the UI does not consume SSE).
- Citation-string validation (Adithyan provides the resolver; you own the verdict).

---

## 2. Your mandate

> Turn five independent Python modules into one deterministic, guarded, replayable pipeline — and prove that the system knows what changed its mind.

Two halves:

**A. Control plane (primary).**
- Deterministic routing: same query + same recorded tool responses ⇒ same plan and same cited node IDs.
- Explicit run states and transitions.
- Visible failures: an agent failing must not look like a successful empty answer.
- Bounded execution: no free-roaming ReAct loop, no unbounded retries, no model-authored plans.

**B. Truth maintenance (secondary, from the L3 mandate).**
- Supersession policy with confidence thresholds.
- `verify_citations` gate before finalize.
- Trace that shows supporting chain, superseded nodes, contradicting edges.
- Honest measurement definitions for correction propagation and provenance.

The control plane ships first. Truth maintenance must not block it.

---

## 3. Skill assignment (what to load and why)

### Load this

`researchos_team_skills/researchos-orchestration/SKILL.md`

It defines:
- the exact `BaseAgent` / `SkillRouter` contracts,
- the existing data keys the API and UI read,
- the bounded target flow (`plan → confirm → retrieve → read → evidence → context → synthesize → critique → persist`),
- the router boundary rules,
- acceptance criteria for run states and resume.

### Read for contracts only

- `researchos-frontend-integration-evaluation/SKILL.md` — SSE events, progress states, what the UI expects.
- `researchos-ctxflow-memory/SKILL.md` — why run persistence cannot assume `CtxFlow.export()` is a run store.
- `researchos-evidence-retrieval/SKILL.md` — citation resolver and evidence fields, if you wire the Critic.

### Do not use as instructions

- `researchos-evidence-retrieval` — do not build search/PDF parsing inside orchestration.
- `researchos-ctxflow-memory` — do not design the memory schema.
- `researchos-frontend-integration-evaluation` — do not build UI in this workstream.

### Assignment reconciliation (S0)

Commit `6ae8b0f` assigns orchestration to you. The MVP plan §7.4 assigns Layer 4 to Adithyan. The split that keeps both true:

| Area | Owner |
|---|---|
| `agents/base.py`, `agents/router.py`, run state machine, plan/confirmation, retries, cancellation | **Harikesh** |
| `agents/retriever.py` orchestration behaviour | Harikesh (evidence internals Adithyan) |
| `contradiction.py`, `critic.py`, trace/audit policy | **Harikesh** |
| `orchestration/` package, `mcp/`, `guardrails/`, `gateway/`, `api/`, `web/` | Adithyan / Abinav |
| Persistence tables, checkpoints, `run_events` storage | Christo |

If the team instead confirms the old L1–L4 split, the orchestration files move to Adithyan and you return to `contradiction.py`, `critic.py`, `trace_provenance`, `research_trace`, and evaluation. **Do not start run-state code before this is written down in the S0 notes.**

---

## 4. Ownership map

### You own — write access

| Path | Responsibility |
|---|---|
| `src/researchos/agents/base.py` | `BaseAgent`, `AgentResult`, status, error capture, timing |
| `src/researchos/agents/router.py` | `QueryIntent`, `classify_intent`, `_EXECUTION_PLANS`, `SkillRouter` |
| New `src/researchos/runs/` (or agreed module) | Run record, state machine, transitions, cancellation |
| `src/researchos/agents/critic.py` | Citation verdict, supersession/contradiction gate |
| `src/ctxflow/contradiction.py` | Detection pipeline, confidence policy (coordinate with Christo on atomicity) |
| `src/ctxflow/graph.py` → `trace_provenance` | Backward lineage walk (coordinate with Christo) |
| `src/ctxflow/__init__.py` → `research_trace` | Facade trace (coordinate with Christo) |
| `tests/test_agents.py`, new `tests/test_runs.py`, `tests/test_provenance.py`, `tests/test_contradiction.py` | Regression surface |

### Shared — edit only with the named owner in the PR

| Path | Owner | Why |
|---|---|---|
| `src/researchos/api/routes/chat.py` | Adithyan / Abinav | `/api/chat` blocking fix and new run endpoints |
| `src/researchos/api/server.py` | Adithyan | `create_app()` wiring, SSE |
| `src/researchos/api/schemas.py` | Abinav | `ResearchRun`, `PlanStep`, `RunStatus` models |
| `src/researchos/agents/retriever.py` | Adithyan | Provider calls; you only own the sequence |
| `src/ctxflow/models.py` | Christo | `Node.status`, `ContradictionVerdict`, trace dataclasses |
| `src/researchos/eval/*` | Abinav | You define metric semantics; he runs/reports |
| `pyproject.toml` | Adithyan | Any orchestration extra |

### Read-only for you

`src/researchos/skills/**`, `src/ctxflow/memory/**`, `src/researchos/web/**`, `src/researchos/eval/*` implementation, prompts.

---

## 5. P0 deliverables

| # | Deliverable | Acceptance |
|---|---|---|
| 1 | Preserve the deterministic pipeline baseline | Existing `test_agents.py` / `test_api.py` stay green; plan for 100 fixture queries is stable |
| 2 | Explicit run states: `planning`, `awaiting_confirmation`, `running`, `completed`, `failed`, `cancelled` | Invalid transitions rejected; normal + failed + cancelled + resume tests |
| 3 | Plan generation from the 4 intents, frozen after creation | Plan never mutates mid-run; repair loops are counters, not replans |
| 4 | Optional confirmation gate | A run can wait, be confirmed, edited within the allowed plan, or cancelled |
| 5 | Resume without re-running retrieval/reading | Kill/restart test resumes from persisted state; expensive steps not repeated |
| 6 | Failure visibility | An agent failure appears as `failed`/partial in `/api/chat` and SSE; no silent "success" |
| 7 | Event-loop fix | `/api/chat` no longer blocks; `test_no_blocking_io` or equivalent detects regression |
| 8 | Bounded retry policy | `max_attempts=2`, exponential 0.5 s, only transient/timeouts/rate limits |
| 9 | Supersession policy: `≥0.80` auto-supersede, `0.50–0.80` contested, `<0.50` ignore | Policy table unit-tested; every transition emitted as an event |
| 10 | Schema-constrained contradiction verdict `{relation, confidence, rationale}` | Invalid JSON triggers one repair, never propagates; 100-run fault test |
| 11 | `verify_citations` gate using Adithyan's resolver | Unsupported claim stripped/flagged; `unsupported_claim_rate` emitted |
| 12 | `research_trace` completeness | Demo trace renders ≥1 real supersession, the supporting chain, and contradictions |
| 13 | Truth-maintenance metric definitions | `correction_propagation`, `provenance_precision`, `unsupported_claim_rate` documented and handed to Abinav |
| 14 | Determinism measurement | 20 identical runs: plan hash equal, citation Jaccard ≥ 0.95 (harness run by Abinav) |

---

## 6. ADR-001 — runtime decision (do this in S0)

**The conflict:** `docs/MVP_IMPLEMENTATION_PLAN.md` promotes LangGraph + `AsyncPostgresSaver` into the MVP. `researchos_team_skills/*` says LangGraph does not exist and must not be reintroduced without a measured need. Both cannot be silently true.

Write `docs/adr/001-orchestration-runtime.md` with two options:

### Option A — keep the deterministic `SkillRouter` (default)

- Zero new dependencies.
- Explicit run record + state machine + events around the existing sequential pipeline.
- Meets determinism, resume, and audit goals for the MVP.
- Cost: no graph-runtime features (parallel branches, interrupts, checkpoint library).

### Option B — adopt LangGraph as a wrapper

- New `[orchestration]` extra; fixed 8-node topology (`guard_input → route → retrieve → read → synthesize → verify_citations → check_contradictions → guard_output → finalize`).
- `ResearchState` is a `TypedDict`; `plan` frozen after `route`; budget middleware on every model/tool call; `AsyncPostgresSaver`, `thread_id = run_id`; replay from recorded events.
- `SkillRouter` remains as a fallback and for tests.
- Cost: 8–10 engineer-days, new failure modes, demo risk.

**Decision rule:** if the team cannot demo Option B end to end by M2 (13 Nov), revert to Option A and report it as a limitation. Do not run both in parallel. Do not put LangGraph in `pyproject.toml` before the ADR is approved.

### If Option B is approved

- Christo owns the checkpoint tables and retention; you own the graph, nodes, and state.
- Adithyan owns the API run endpoints; Abinav owns the trace UI.
- Publish `ResearchState`, `RunEvent`, and `PlanStep` before writing nodes.
- `plan` is computed once; repair is an edge counter (max 2), not a replan.
- Every node declares `allowed_tools` (least privilege).
- Budget exhaustion routes to `guard_output` with a truncation notice, never an exception.

---

## 7. Required workflow (bounded)

```text
create run
  → plan (4 intents; rules first)
  → [optional] await confirmation / edit / cancel
  → retrieve → read → extract evidence → retrieve project context
  → synthesize → verify citations → check contradictions
  → finalize → persist run + events
```

Rules:

- One model call per node. If a node needs two, redesign it.
- No model call on the critical path of the baseline router; LLM fallback only for `UNKNOWN`, constrained to the 4 labels, `temperature=0`, confidence < 0.7 ⇒ default plan.
- Repair loops are bounded (`≤2`) and counted per node.
- A failed agent is visible; partial results are allowed if labelled.
- Persist enough state to resume **without** repeating retrieval/reading.
- Do not create a new database silently. Prefer a small `ResearchRun` record behind an interface; if it needs Postgres, use Christo's schema and migration process.

---

## 8. What NOT to do

Hard prohibitions.

1. **Do not add LangGraph, a checkpoint framework, or an agent swarm before ADR-001 is approved.**
2. **Do not make a model call on the critical path of the baseline router.** The keyword classifier stays until measured otherwise.
3. **Do not rewrite `CtxFlow` or replace `SkillRouter` in the same PR that adds run state.**
4. **Do not create a second schema package.** Extend `api/schemas.py` (or a package it becomes) in one PR and update all consumers.
5. **Do not swallow agent failures.** If you change failure propagation, update `/api/chat` and SSE consumers in the same PR.
6. **Do not run the synchronous `run()` directly in an `async def`.** Use the executor/`to_thread`; add a test.
7. **Do not add unbounded loops, unbounded retries, or parallel branches without a bounded budget.**
8. **Do not build search, PDF parsing, citation resolution, memory algorithms, or UI inside orchestration.** Call the owners' interfaces.
9. **Do not persist prompts, secrets, or full tool payloads in run events.** Hash and reference them.
10. **Do not claim resume, confirmation, cancellation, or replay works** until a process-restart test proves it.
11. **Do not use `CtxFlow.export()` as a run store.** It is graph-only and does not capture plan/step state.
12. **Do not edit the UI, providers, memory store, or evaluation harness.**
13. **Do not let a failing trace look verified.** A missing resolver result is `unsupported`, not "probably fine".
14. **Do not exceed 400 changed lines per PR** or mix a runtime decision with a feature.

---

## 9. Contracts you publish / consume

### You publish by S0 Friday

```python
# proposed; adjust names only with team agreement
class RunState(str, Enum):
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class PlanStep:
    agent: str
    purpose: str
    allowed_tools: tuple[str, ...] = ()

@dataclass(frozen=True)
class RunEvent:
    run_id: str
    seq: int
    ts: float
    type: str                 # route | agent_start | agent_end | tool_call | guard | error
    agent: str | None = None
    prompt_hash: str | None = None
    model_id: str | None = None
    tool: str | None = None
    args_hash: str | None = None
    output_hash: str | None = None
    duration_ms: float | None = None
    cache_hit: bool | None = None
```

Also publish:
- `QueryIntent` and plan mapping (unchanged unless measured).
- `AgentResult` envelope and the preserved keys: `answer`, `cited_nodes`, `alerts`, `trace`; router envelope `intent`, `plan`, `result`, `pipeline_results`.
- Retry policy and state-transition table.
- `ContradictionVerdict` and `TraceView` shapes (with Christo).
- Metric definitions for truth maintenance.

### You consume

| From | Contract |
|---|---|
| Adithyan | `PaperResult`, `access_status`, citation resolver, agent data keys |
| Christo | `CtxFlow.ingest/query/research_trace`, `MemoryStore`, `RunEvent` persistence |
| Abinav | `EvidenceCard`, `Claim`, UI/SSE expectations, eval report |
| All | `tests/contract/` |

### Preserved data keys (do not rename casually)

- `data["answer"]`, `data["cited_nodes"]`, `data["alerts"]`, `data["trace"]`.
- `data["internal_results"]`, `data["external_results"]`, `data["knowledge_gap"]`.
- Router envelope: `data["intent"]`, `data["plan"]`, `data["result"]`, `data["pipeline_results"]`.

The API and UI read these. Rename only with a coordinated PR.

---

## 10. Sprint plan (yours only)

| Sprint | Deliverable | Gate |
|---|---|---|
| **S0** 26–30 Oct | Audit; ADR-001; publish run/event/plan contracts; failure-visibility test plan | Runtime decision recorded |
| **S1** 2–6 Nov | Run record + state machine + transitions; `/api/chat` non-blocking fix | Tests for normal/invalid/failed |
| **S2** 9–13 Nov | Plan generation + optional confirmation; retry policy | Confirm/edit/cancel tested |
| **S3** 16–20 Nov | Persist/resume; event emission; failure propagation to API | Restart test passes |
| **S4** 23–27 Nov | Supersession policy + `verify_citations`; trace completeness | Policy + unsupported-citation tests |
| **S5** 30 Nov–4 Dec | Red-team claim pairs; determinism fixture; metric definitions handed to Abinav | Plan hash + citation Jaccard reported |
| **S6** 7–11 Dec | Docs, limitations, demo trace rehearsal | Demo step 3 passes |
| **S7** 14–18 Dec | Freeze; no risky changes | Frozen build |

---

## 11. Definition of Done

- [ ] Happy path + one failure path tested.
- [ ] `pytest -q` green; exact command and result reported.
- [ ] Every state transition explicit, validated, and tested.
- [ ] No blocking I/O on the event loop.
- [ ] Tool/model failures visible; never fabricated into results.
- [ ] No new dependency outside an approved ADR/extra.
- [ ] Trace event names stable and documented.
- [ ] Docs updated; no "planned" feature described as working.
- [ ] Cost/latency impact in the PR.

### Commands

```bash
python -m pytest -q
python -m pytest -q tests/test_agents.py tests/test_api.py tests/test_workspace_api.py
python -m pytest -q tests/test_provenance.py tests/test_contradiction.py   # when present
python -m researchos.eval
```

---

## 12. Known landmines in your area

| Landmine | Consequence | Action |
|---|---|---|
| Router is regex-only and returns `UNKNOWN` easily | Silent fallback to the wrong pipeline | Measure misclassification on a fixture; only then add bounded LLM fallback |
| PR #3 classifier is 59 % accurate with a dead class | Auto-routing/ingestion would be unreliable | Do not use `classify_memory` as a gate |
| `SkillRouter` skips failed agents | Partial answer looks complete | Surface `success=False` and label partial results |
| `/api/chat` calls sync `run()` in `async def` | Blocks every request | Fix consistently, add regression test |
| `previous_results` and `context["previous_output"]` carry different shapes | Agents disagree about input | Document one precedence rule; test it |
| `graph_query` is a TraceAgent name collision | Confusing registration | Rename only in a coordinated PR; document now |
| SSE emits only coarse events | UI cannot show real progress | Keep event contract stable; add per-step events deliberately |
| Module-level `_app_state` in routes | Two apps collide; not task-safe | Do not build run state on it |
| `CtxFlow.export()` is graph-only | Cannot resume a run | Use a run store; coordinate with Christo |
| Critic parses status/edges, not citation strings | Dead citations pass as verified | Wire Adithyan's resolver; own the verdict |
| Eval harness injects supersession edges manually | Benchmark does not exercise the LLM detector | Report that limitation honestly |
| LangGraph is in the MVP plan but absent in code | Team builds two control planes | Resolve ADR-001 before coding |

---

## 13. Coordination and escalation

| Topic | Person | Rule |
|---|---|---|
| Run endpoints, SSE, create_app | Adithyan | One schema PR; he owns serving |
| Run UI, trace panel, report | Abinav | Publish event names before UI work |
| Run tables, checkpoints, events | Christo | He owns storage; you own semantics |
| Citation resolver | Adithyan | He resolves; you decide strip/flag |
| Evidence payload | Adithyan | Agree `data` keys before wiring |
| Metric numbers | Abinav | He runs the harness; you define truth-maintenance metrics |

**Escalate immediately if:** ADR-001 is still open after S0, a run cannot be resumed without a new database, or a failure must be hidden to make the demo pass.

---

## 14. Copy-paste kickoff prompt

```text
You are Harikesh, orchestration and truth-maintenance owner for ResearchOS in D:\DEEPLEARNIING\CtxFlow.

Read, in this order:
1. docs/team/HARIKESH.md
2. researchos_team_skills/researchos-orchestration/SKILL.md
3. docs/MVP_IMPLEMENTATION_PLAN.md sections 1, 4, 6, 7.3, 8, 9 (G8, G9, G10), 12, 13
4. REPO_HANDOFF_SUMMARY.md sections 6, 8, 11
5. src/researchos/agents/{base,router,retriever,critic}.py and api/routes/chat.py

Then run `python -m pytest -q tests/test_agents.py tests/test_api.py tests/test_workspace_api.py`
and report the real result. Do not change code yet.

First task: write docs/adr/001-orchestration-runtime.md and publish the run/event/plan contract.
Do not add LangGraph before the ADR is approved. Do not rewrite the router and add run state in
the same PR. Do not swallow agent failures. Report exact commands, results, and limitations.
```

---

## 15. One-screen summary

- **Own:** router, agent contract, run state machine, resume, retries, critic, contradiction policy, trace.
- **Ship:** explicit run states, visible failures, non-blocking chat, bounded retries, citation gate, auditable supersession.
- **Never:** LangGraph without ADR, LLM on the critical routing path, silent agent failure, duplicate schemas, unbounded loops, unverified resume claims.
- **Skills:** `researchos-orchestration` (primary); others read-only for contracts.
- **Done means:** green tests, restart-resume proven, failure visible, plan/citations deterministic.
