# Abinav — Frontend, Integration & Evaluation Handbook
## Workspace UI, API Contracts, End-to-End Tests & Honest Measurement

| | |
|---|---|
| **Role** | UI/API integration owner and evaluation lead; secondary: context/token efficiency |
| **Seminar** | *Context Window Utilization and Positional Bias in LLMs* |
| **Primary skill** | [`researchos_team_skills/researchos-frontend-integration-evaluation/SKILL.md`](../../researchos_team_skills/researchos-frontend-integration-evaluation/SKILL.md) |
| **Secondary reading** | `researchos-orchestration/SKILL.md` (SSE/run contract) and `researchos-evidence-retrieval/SKILL.md` (source/access fields). Read only; do not edit their areas. |
| **Working branch** | `feat/abinav-ui-eval` |
| **Baseline** | `Adi/feat/v1` @ `e1f43c6` (PR #3 merged); `144 passed, 6 skipped` (verified 25 Oct 2026) |
| **Contract freeze** | Fri 30 Oct 2026, 18:00 |

---

## 0. Read this first

1. This file is your complete brief. The primary skill contains the verified code audit; where they differ, the **skill's code facts** win.
2. There is **no React/Next app** and no npm build step. The UI is vanilla HTML/CSS/JS in `src/researchos/web/`, served by FastAPI. Keep it that way for the MVP.
3. The UI already works end to end for the implemented steps: ingest a paper/PDF, save notes, ask a question, see cited node IDs, inspect the graph, open a trace.
4. Your job is **not** to make it prettier. It is to make the flow complete, honest, inspectable, and measured.
5. Never render mock data as research. If a backend endpoint is missing, build the backend contract with its owner first, or show an explicit "not implemented" state.
6. Do not mark steps 3, 4, or 9 in the target flow complete until they are implemented and verified.

---

## 1. Context in 60 seconds

ResearchOS is a FastAPI backend plus a bundled static workspace.

```text
src/researchos/api/server.py     create_app(), lifespan DI, static mount at "/"
src/researchos/api/schemas.py    all Pydantic request/response models
src/researchos/api/routes/       chat.py, papers.py, notes.py
src/researchos/web/              index.html, styles.css, app.js (no build step)
src/researchos/eval/             dataset, baselines, benchmark, metrics, CLI
```

Key endpoints the UI uses:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | status, version, node/edge counts |
| `POST` | `/api/chat` | answer, intent, cited nodes, alerts, optional trace |
| `GET` | `/api/stream?query=` | SSE: `start`, `agent_completed`, `done` |
| `POST` | `/api/papers/ingest` | metadata/abstract ingestion |
| `POST` | `/api/papers/upload` | PDF upload (multipart) |
| `POST` | `/api/trace` | provenance chain, superseded, contradictions, sources |
| `GET` | `/api/graph/data` | nodes + edges for the SVG |
| `GET` | `/api/graph/stats` | counts and distributions |
| `POST`/`GET` | `/api/notes` | per-project notes only |

The UI:

- Top bar: project-id text input, node/edge counts, health dot.
- Left: Library (paper form, PDF upload, note form, lists).
- Centre: chat (message stream, composer, intent badge).
- Right: hand-rolled SVG knowledge graph + Research Trace panel.
- Citations (`[Node:ID]`) open the trace; the graph node click opens the trace.
- **The UI does not use `/api/stream`.** It uses `/api/chat` and waits.
- The static mount is registered **last** so `/api`, `/docs`, and `/openapi.json` win.

What does not exist:

- Project creation/persistence (project id is free text).
- Plan generation/editing/confirmation, a run resource (`/api/runs/...`), resume.
- Per-agent live progress in the chat view.
- Source access/download status, report export.
- Persistence across restart (`CtxFlow` is in memory).
- A meaningful evaluation suite (default: **3 papers / 2 questions**).

---

## 2. Your mandate

> Deliver the usable end-to-end ResearchOS experience, with visible state and honest numbers.

Four outcomes:

1. **Flow completeness** — a researcher can go from project → question → answer → evidence → trace without developer tools, and unimplemented steps are visibly unimplemented.
2. **Truthful UI** — sources, failures, partial results, and unresolvable citations are shown, not hidden.
3. **Integration discipline** — the UI consumes documented schemas; schema changes ship once with all consumers.
4. **Credible evaluation** — enough questions to mean something, identical settings across systems, committed reports, limitations stated.

Secondary (seminar) outcome: measure **token efficiency and positional effects** honestly — tokens per query, context reduction, and citation stability. Do not promise embedding-based retrieval; the MVP defers it.

---

## 3. Skill assignment (what to load and why)

### Load this

`researchos_team_skills/researchos-frontend-integration-evaluation/SKILL.md`

It defines:
- the current-vs-target user flow (9 steps, 3 of them missing),
- the endpoint/schema table,
- UI rules (states, citations, errors),
- the shipped evaluation harness and its limitations,
- the acceptance criteria.

### Read for contracts only

- `researchos-orchestration/SKILL.md` — SSE events, run states, plan/confirmation shapes.
- `researchos-evidence-retrieval/SKILL.md` — `access_status`, page/section, citation resolver.

### Do not use as instructions

- `researchos-evidence-retrieval` — providers/PDF parsing are Adithyan's.
- `researchos-ctxflow-memory` — persistence/memory is Christo's.
- `researchos-orchestration` — router/run state is Harikesh's.

### Ownership reconciliation (decide in S0)

Commit `6ae8b0f` assigns you frontend/integration/evaluation. The MVP plan §7.2 also names you owner of `query.py`, `llm_extractor.py`, `synthesizer.py`, `prompts/`, and `paper_reader.py`.

Recommended split, to be recorded in the S0 notes:

| Area | Recommendation |
|---|---|
| `ui/` + `api/` integration + `eval/` | **You keep** |
| `ctxflow/query.py` + `researchos/prompts/` | **You keep** — they determine the token efficiency you measure |
| `agents/synthesizer.py` | **You keep** — positional-bias placement is your seminar |
| `skills/paper_reader.py` | Hand to Adithyan (evidence owner) |
| `ctxflow/llm_extractor.py` | Keep only if extraction schema work is on your plate; otherwise Adithyan |

Do not silently drop the L2 files, and do not silently take them either. One written decision by S0 Friday.

---

## 4. Ownership map

### You own — write access

| Path | Responsibility |
|---|---|
| `src/researchos/web/index.html`, `app.js`, `styles.css` | Workspace shell, chat, graph, trace panel, states |
| `tests/test_workspace_api.py`, `tests/test_api.py` (UI/API portions) | End-to-end and contract tests |
| `src/researchos/eval/dataset.py`, `baselines.py`, `benchmark.py`, `metrics.py`, `__main__.py` | Evaluation harness |
| `docs/eval/**` (new) | Committed reports and limitations |
| `README.md` quickstart/demo section | Setup and demo instructions |
| `ctxflow/query.py`, `researchos/prompts/**`, `agents/synthesizer.py` (if confirmed) | Scoring, prompt registry, token packing, positional layout |

### Shared — edit only with the named owner in the PR

| Path | Owner | Why |
|---|---|---|
| `src/researchos/api/schemas.py` | You, with all consumers | Every field change affects API/UI/tests |
| `src/researchos/api/server.py`, `routes/*` | Adithyan / Harikesh | Endpoint behaviour and wiring |
| `src/researchos/skills/review_writer.py` | Adithyan (evidence) | Report synthesis consumes citation helpers |
| `src/ctxflow/query.py` | Christo (data) / you (scoring) | Scoring changes need benchmark review |
| `tests/contract/**` | All | Frozen interfaces |
| `pyproject.toml` | Adithyan | No UI dependency without an ADR |

### Read-only for you

`src/ctxflow/models.py`, `graph.py`, `memory/**`, `src/researchos/agents/router.py`, `skills/literature_search.py`, `skills/paper_reader.py`, `mcp/`, `gateway/`.

---

## 5. P0 deliverables

### UI and integration

| # | Deliverable | Acceptance |
|---|---|---|
| 1 | Workspace state machine: loading, awaiting-confirmation, running, success, partial, failure as **distinct** states | No spinner that silently becomes "no results" |
| 2 | Real API integration only; mocks clearly labelled and never rendered as research | A missing endpoint shows an explicit unavailable state |
| 3 | Project selection/persistence (with backend owner) | Reopening a project restores its papers/notes/graph, or the limitation is visible |
| 4 | SSE progress consumer (`/api/stream`) after Harikesh publishes event names | UI shows per-step progress; cancel/resume only if backend supports it |
| 5 | Plan display/confirmation (only when backend exists) | Edit/confirm/cancel work; feature-flagged; not faked |
| 6 | Source/evidence inspection: title, authors, year, DOI/arXiv, page/section, `access_status` | Abstract-only vs full-text is visible |
| 7 | Citation navigation: `[Node:ID]` → trace; unresolvable citation visibly flagged | No dead citation rendered as verified |
| 8 | Trace panel: supporting chain, superseded nodes in red, contradiction edges, blocked-step badge | Demo step 3 passes without dev tools |
| 9 | Report display + Markdown export (if feasible) | Export works from the real answer, not a mock |
| 10 | E2E test with a controlled provider/mock **plus** a real-setup smoke test | Tests green; mocks isolated |
| 11 | Root-relative assets, empty/error handling, no secret/prompt leakage | Static mount at `/` keeps working |

### Evaluation

| # | Deliverable | Acceptance |
|---|---|---|
| 12 | Expand the suite to 10–20 questions, with a reason for each | Rationale committed with the dataset |
| 13 | Identical models/prompts/settings across the three systems | Config captured in the report |
| 14 | Run and commit the actual report | `python -m researchos.eval --json --out docs/eval/<date>.json` |
| 15 | State limitations explicitly | Synthetic suite, substring metrics, hashed embedder, manual supersession injection, `ctxflow_graph` does not run agents |
| 16 | Add context-efficiency measurement if you keep `query.py` | Token reduction vs full-text stuffing at equal correctness; golden prompt determinism |
| 17 | Prompt hash appears in the trace/run events (if `PromptRegistry` lands) | Hash reproducible from the prompt file |

### What the numbers must not do

- Do not cherry-pick examples.
- Do not report only the best system.
- Do not claim statistical significance from 10–20 synthetic items.
- Do not call the hashing baseline "semantic retrieval".
- Do not claim the graph system "runs four agents" — `_evaluate_ctxflow()` queries the graph directly.

---

## 6. Implementation order

1. **Audit in a running app.** Start `researchos-api`, walk the 9-step target flow, and record what actually works and which endpoint each UI action calls.
2. **Run the baseline.** `pytest -q tests/test_workspace_api.py tests/test_api.py`; report the result.
3. **Fix state honesty first.** Loading/success/empty/partial/failure; no silent fallbacks.
4. **Align schemas.** Read `api/schemas.py`; list missing fields (access status, page/section, citation status, run id) and request them in one coordinated PR.
5. **Wire real data.** Project shell → library → evidence → trace.
6. **Add SSE progress** after the event contract is stable. Do not invent event names.
7. **Add plan/confirmation UI** only after Harikesh ships the backend; feature-flag it.
8. **Add report export** only from a real answer, with resolvable citations.
9. **Expand the evaluation suite** and commit the report with the exact command.
10. **Update the README and the skill's endpoint table** so the next person does not guess.

---

## 7. UI rules

- Keep the existing static stack. No bundler or framework migration without a concrete blocker and an ADR.
- Keep states distinct: loading, awaiting confirmation, running, success, partial success, failure.
- **Escape all model/paper/note text.** Use `textContent`, not `innerHTML`, for untrusted content. Papers are untrusted input.
- A citation must navigate to evidence via `/api/trace`; a dead citation must be visible.
- Surface missing/failed sources; do not silently omit them.
- Make the trace informative without exposing secrets or full internal prompts.
- Prefer a small complete workspace over dashboard decoration.
- Use root-relative asset paths (`/app.js`, `/styles.css`); the mount is at `/`.
- Do not disable accessibility basics (labels, focus states, keyboard operation) while restyling.

---

## 8. What NOT to do

Hard prohibitions.

1. **Do not migrate to React/Next/Vite** or add a build step. The MVP explicitly cuts a separate frontend.
2. **Do not render mock data as real research.** Mock only in tests, or label it unmistakably.
3. **Do not invent endpoints or response shapes.** Use `api/schemas.py`; request changes through its owner.
4. **Do not mark plan confirmation, run resume, or restart persistence as done** before they exist.
5. **Do not edit providers, PDF parsing, router logic, memory algorithms, or MCP/gateway internals.**
6. **Do not add a second backend or duplicate API layer.**
7. **Do not cherry-pick evaluation results** or hide a failing baseline.
8. **Do not change models/prompts/settings between systems** in the benchmark.
9. **Do not use `innerHTML` for untrusted text.** Paper content is an injection vector.
10. **Do not expose API keys, full system prompts, or raw tool payloads** in the UI/trace.
11. **Do not add a UI dependency without a measured need** and an approved extra.
12. **Do not let visual polish replace a working end-to-end flow.**
13. **Do not exceed 400 changed lines per PR**, and keep schema changes isolated.
14. **Do not describe the evaluation as semantic or statistically strong** when it is substring-based and synthetic.

---

## 9. Contracts you publish / consume

### You publish by S0 Friday

- UI state vocabulary and the exact endpoint each state depends on.
- SSE consumption contract (event names and payload fields) — jointly with Harikesh.
- Evaluation report schema and the command that reproduces it.
- Prompt/token accounting method (with whoever owns `query.py`).
- Field requests to `api/schemas.py` (in one note, not scattered PRs).

### You consume

| From | Contract |
|---|---|
| Harikesh | `RunState`, `RunEvent`, `PlanStep`, SSE event names, failure/partial semantics |
| Adithyan | `PaperResult`, `access_status`, page/section, citation resolver |
| Christo | graph stats/data shapes, persistence/resume availability, `project_id` scoping |
| All | `api/schemas.py`; `tests/contract/` |

### Evaluation report shape (current harness)

```json
{
  "suite": "...",
  "questions": 2,
  "papers": 3,
  "k": 5,
  "systems": {
    "ctxflow_graph": { "...metrics": "..." },
    "flat_rag": { "...metrics": "..." },
    "flat_rag_multi_agent": { "...metrics": "..." }
  }
}
```

Four headline metrics: `answer_accuracy`, `supersession_defense_rate`, `provenance_accuracy`, `avg_context_tokens`.

When you report, include: commit SHA, date, command, `k`, provider/model, suite size, and limitations.

---

## 10. Sprint plan (yours only)

| Sprint | Deliverable | Gate |
|---|---|---|
| **S0** 26–30 Oct | Audit running app; endpoint/state map; schema field requests; S0 ownership decision on L2 files | Contract note published |
| **S1** 2–6 Nov | UI state honesty; error/empty/partial; schema alignment | No silent fallback |
| **S2** 9–13 Nov | Project shell; library/evidence inspection; access-status display | Source status visible |
| **S3** 16–20 Nov | SSE progress consumer; trace panel completion (superseded/contradiction) | Demo step 3 passes |
| **S4** 23–27 Nov | Plan/confirmation UI behind flag (if backend exists); report export; eval suite v1 (10–20 Q) | Feature-flagged; report committed |
| **S5** 30 Nov–4 Dec | Full eval run; E2E mock + smoke; prompt hash/token accounting | Numbers reproducible |
| **S6** 7–11 Dec | README/demo docs; empty/error polish; limitations section | Setup works from scratch |
| **S7** 14–18 Dec | Freeze; demo rehearsal | Frozen build |

---

## 11. Definition of Done

- [ ] The implemented project-to-answer flow works in the UI; unimplemented steps are not presented as done.
- [ ] Progress and errors are understandable, including partial failure.
- [ ] Sources and citations are inspectable; unresolvable citations are visible.
- [ ] Empty/error API responses render correctly.
- [ ] E2E test uses a controlled provider; smoke test covers the real setup where practical.
- [ ] Evaluation can be rerun from documented steps; results committed honestly.
- [ ] `pytest -q` green; exact command/result reported.
- [ ] README/demo instructions updated.

### Commands

```bash
python -m pytest -q
python -m pytest -q tests/test_workspace_api.py tests/test_api.py
python -m researchos.eval
python -m researchos.eval --json --out docs/eval/report.json
researchos-api
```

---

## 12. Known landmines in your area

| Landmine | Consequence | Action |
|---|---|---|
| Static mount is last | Moving it earlier shadows `/api` and `/docs` | Keep the order; test `/health` and `/` |
| UI uses `/api/chat`, not SSE | No live progress | Add SSE deliberately after event contract |
| `project_id` filters notes only | UI implies project isolation that does not exist | Label the limitation, or wait for Christo |
| `CtxFlow` is in memory | Refresh/restart loses the workspace | Show it; do not imply persistence |
| `ChatRequest.session_id` / `token_budget` accepted but ignored | False sense of control | Do not expose controls that do nothing |
| Eval default suite is 3 papers / 2 questions | Numbers are not credible | Expand and document |
| `_evaluate_ctxflow()` queries the graph, does not run agents | "4-agent" claim is false | Report the actual method |
| Supersession is manually injected in the eval | Does not test the detector | State it in limitations |
| Metrics are substring-based | Sensitive to wording, not semantics | Do not overclaim |
| Baselines use `HashingEmbedder` (hashed bag-of-words) | Not semantic retrieval | Say "hashed lexical baseline" |
| Token estimate is 4 chars/token | Under/over-counts | Use `SimpleTokenizer` if comparing across systems |
| Module-level `_app_state` | Two apps in one process collide | Do not build test state on it |
| Graph rendering is hand-rolled | Degrades on large graphs | Cap rendered nodes; do not add a graph library without an ADR |
| Paper text rendered in DOM | XSS/injection | `textContent` + escaping |
| CI/live jobs | Nightly failures can surprise demo | Record which tests need a live provider |

---

## 13. Coordination and escalation

| Topic | Person | Rule |
|---|---|---|
| SSE events, run ids, plan/confirm | Harikesh | Agree names before UI work |
| Endpoints, server wiring | Adithyan | One schema PR, all consumers |
| Persistence/project scope | Christo | Do not fake isolation in the UI |
| Source/access fields | Adithyan | Display what exists; mark unknown |
| Contract change after 30 Oct | All | ADR + approval + contract test |

**Escalate immediately if:** an API field you need does not exist, a benchmark number cannot be reproduced, or a demo requires mock data.

---

## 14. Copy-paste kickoff prompt

```text
You are Abinav, frontend/integration/evaluation owner for ResearchOS in D:\DEEPLEARNIING\CtxFlow.

Read, in this order:
1. docs/team/ABINAV.md
2. researchos_team_skills/researchos-frontend-integration-evaluation/SKILL.md
3. docs/MVP_IMPLEMENTATION_PLAN.md sections 1, 2, 8, 12, 13, 15
4. REPO_HANDOFF_SUMMARY.md sections 7, 8, 11
5. src/researchos/api/server.py, api/schemas.py, web/app.js, eval/benchmark.py, eval/metrics.py

Then start the app, walk the 9-step target flow, and run
`python -m pytest -q tests/test_workspace_api.py tests/test_api.py`. Report the real result.

First task: map each UI action to its endpoint and fix state honesty (loading/empty/partial/failure).
Do not add a framework or bundler. Do not render mocks as research. Do not edit providers, PDF
parsing, the router, memory, or MCP internals. Do not expand the eval suite until settings are
pinned. Report exact commands, results, and limitations.
```

---

## 15. One-screen summary

- **Own:** static workspace UI, API integration tests, evaluation harness/report, docs; optionally `query.py`/prompts/synthesizer.
- **Ship:** complete honest flow, visible source/access status, live progress, trace panel, 10–20 question eval, committed numbers.
- **Never:** framework migration, mocked research, invented endpoints, fake persistence, cherry-picked metrics, `innerHTML` for papers.
- **Skills:** `researchos-frontend-integration-evaluation` (primary); others read-only for contracts.
- **Done means:** demo steps 1–6 pass in the UI, evaluation reproducible, limitations stated.
