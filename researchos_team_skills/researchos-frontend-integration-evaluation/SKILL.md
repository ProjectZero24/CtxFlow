---
name: researchos-frontend-integration-evaluation
description: Build and integrate the ResearchOS research workspace UI, connect it to the existing FastAPI API, expose progress and evidence, and evaluate the MVP against the shipped RAG baselines.
---

# ResearchOS Frontend, Integration & Evaluation Skill

## Mission

Deliver the usable end-to-end ResearchOS experience in this repository (`ProjectZero24/CtxFlow`, integration branch `Adi/feat/v1`). Extend the existing static workspace and FastAPI app; do not build a second backend.

There is no LangGraph and no separate frontend framework. The UI is vanilla HTML/CSS/JS served by FastAPI.

## Current implementation (verified at `34cf19f`)

Backend:

- `src/researchos/api/server.py` → `create_app()`; lifespan builds `CtxFlow`, `SkillRegistry`, and `SkillRouter`; mounts `src/researchos/web/` with `StaticFiles(..., html=True)` at `/` **last**, so `/api`, `/docs`, and `/openapi.json` win.
- `src/researchos/api/schemas.py` → all request/response Pydantic models.
- Routes:

| Method | Path | Schema / notes |
|---|---|---|
| GET | `/health` | `HealthResponse` (`status`, `version`, `graph_nodes`, `graph_edges`) |
| GET | `/api/skills` | `SkillListResponse` |
| POST | `/api/chat` | `ChatRequest` → `ChatResponse` (`answer`, `intent`, `cited_nodes`, `alerts`, `trace`, `metadata`) |
| GET | `/api/stream?query=...` | SSE: `start`, one `agent_completed` per agent, `done` |
| POST | `/api/query` | `QueryRequest` → `QueryResponse` |
| POST | `/api/search` | `SearchRequest` → `SearchResponse` |
| POST | `/api/papers/ingest` | `PaperIngestRequest` → `PaperIngestResponse` |
| POST | `/api/papers/upload` | multipart (`file`, `project_id`, `title`) → `PaperIngestResponse` |
| GET | `/api/graph/stats` | `GraphStatsResponse` |
| GET | `/api/graph/data` | `GraphDataResponse` (nodes + edges) |
| POST | `/api/trace` | `TraceRequest` → `TraceResponse` (provenance chain, superseded, contradictions, source papers) |
| POST | `/api/notes` | `NoteCreateRequest` → `NoteResponse` |
| GET | `/api/notes?project_id=...` | `NoteListResponse` |

Frontend (`src/researchos/web/`):

- `index.html` — top bar with project text input and graph stats; left "Library" (add paper, upload PDF, add note, paper/note lists); centre "Ask the pipeline" chat; right "Knowledge graph" SVG + research-trace panel.
- `app.js` — calls `/api/chat`, `/api/papers/ingest`, `/api/papers/upload`, `/api/notes`, `/api/graph/data`, `/api/trace`, `/health`.
- `styles.css` — layout and states.
- Tests: `tests/test_workspace_api.py` (index/assets, notes, trace, claim verification), `tests/test_api.py`.

What already works end-to-end: ingest a paper (text, or PDF when `pymupdf` is installed), save notes, ask a question, see cited node IDs and alerts, inspect the graph, and open a research trace.

What does **not** exist: project creation/persistence (it is a free-text `project_id`), plan generation/editing/confirmation, a run resource (`/api/runs/...`), per-agent live progress in the chat view (the UI uses `/api/chat`, not SSE), source access/download status, report export, and persistence across restarts (`CtxFlow` is in-memory).

## Before coding

1. Read `src/researchos/api/server.py`, `src/researchos/api/schemas.py`, every route module, and `src/researchos/web/app.js`.
2. Start the app (`researchos-api` or `uvicorn researchos.api.main:app --reload`) and record what actually works, including which endpoints the UI calls.
3. Run `pytest -q tests/test_workspace_api.py tests/test_api.py` and report the real result.
4. Read the shared schemas before building views. Do not invent endpoint shapes.
5. Use mocked responses only while a backend endpoint is genuinely missing; never render mocks as real research.

## Ownership

- Project selection and workspace shell.
- Research question entry and (if built) editable-plan confirmation.
- Run status/progress and research trace presentation.
- Paper/source library and evidence inspection.
- Report display and Markdown export if feasible.
- API integration and visible error/partial-failure states.
- End-to-end tests and a reproducible evaluation run.

Out of scope: provider internals, PDF parsing, router logic, and memory algorithms.

## Required user flow (current vs target)

| Step | Status at `34cf19f` | Where to work |
|---|---|---|
| 1. Create/select a project | text input only; not persisted | `index.html` + a new API resource (coordinate) |
| 2. Enter a research question | works (`/api/chat`) | `app.js` |
| 3. Review/edit a proposed plan | **missing** | needs orchestration + new schema |
| 4. Confirm and start a run | **missing**; chat starts immediately | orchestration + API |
| 5. See status and meaningful progress | partial: SSE exists, UI does not use it | `app.js` + `/api/stream` |
| 6. Inspect papers and access/read status | ingest works; no access status field | evidence + API |
| 7. Open evidence excerpts and source metadata | `/api/trace` + node metadata | `app.js`, trace panel |
| 8. Read a report with linked citations | `answer` with `[Node:ID]`; no export | `app.js` |
| 9. Reopen a project after restart | **missing** (in-memory graph) | persistence/import-export |

Do not mark steps 3, 4, or 9 complete in docs or UI copy until they are implemented and verified.

## UI rules

- Keep the existing static stack; no bundler or framework migration without a concrete blocker.
- Keep loading, awaiting-confirmation, running, success, partial success, and failure states distinct.
- Do not show mock data as real research results.
- A citation (`[Node:ID]`) should navigate to the saved node/evidence detail via `/api/trace`.
- Surface missing/failed sources instead of hiding them; the API returns empty lists today, so add explicit status fields rather than guessing.
- Make the trace informative without exposing secrets or full internal prompts.
- Prefer a small, complete workspace over dashboard decoration.
- Keep static paths root-relative (`/app.js`, `/styles.css`); the mount is at `/`.

## Integration responsibilities

- Coordinate with the orchestration owner on chat/run creation, confirmation, status, and resume endpoints.
- Coordinate with the evidence owner on paper/evidence/report fields and on access status.
- Coordinate with the memory owner before exposing context diagnostics.
- Use `src/researchos/api/schemas.py`; if a schema change is required, ship it in one small PR and update all consumers.
- Add at least one end-to-end test using a controlled/mock provider (`tests/test_workspace_api.py` style), plus a smoke test for the real setup where practical.
- When you add an endpoint, add it to this skill's table and to the README so the next person does not guess.

## Evaluation

Use the shipped harness instead of inventing one:

- `src/researchos/eval/benchmark.py` → `BenchmarkRunner(suite, k).run_benchmark()` compares:
  1. `ctxflow_graph` — CtxFlow graph memory. The docstring says "+ four agents", but `_evaluate_ctxflow()` queries the graph directly and does not run the agents; do not overclaim.
  2. `flat_rag` — flat vector retrieval, single agent.
  3. `flat_rag_multi_agent` — flat vector retrieval, multi-agent shape.
- `src/researchos/eval/dataset.py` → `get_default_contradiction_benchmark()` is only 3 papers / 2 questions.
- `src/researchos/eval/metrics.py` → deterministic, LLM-free: `answer_accuracy`, `supersession_defense_rate`, `provenance_accuracy`, `avg_context_tokens` (4 chars/token).
- `python -m researchos.eval` prints a markdown table; `--json --out benchmark-report.json` writes the full report; `--k` changes retrieval depth.
- `tests/test_eval_harness.py` is the regression suite.

To make the evaluation meaningful:

1. Expand the suite to 10–20 questions and record why each is included.
2. Keep models/prompts/settings identical across systems.
3. Report actual numbers from a committed report file, not hand-picked examples.
4. If you add LLM-judged metrics, report them alongside the deterministic ones and document the judge/model/version.
5. State limitations: the default suite is synthetic, metrics are substring-based, and the baselines use a deterministic 256-dim `HashingEmbedder` (hashed bag-of-words), not a semantic model.

## Non-goals

- Do not implement scholarly providers or PDF parsing.
- Do not rewrite the router or add a graph runtime.
- Do not replace the persistence layer independently.
- Do not implement advanced memory algorithms.
- Do not treat visual polish as a substitute for a working end-to-end flow.

## Acceptance criteria

- The user can complete the implemented project-to-answer workflow in the UI, and unimplemented steps are not presented as done.
- Progress and errors are understandable, including partial failures.
- Sources and citations are inspectable; unresolvable citations are visible.
- Notes/papers behave per project as documented (today only notes are filtered).
- The UI works with documented API schemas and handles empty/error responses.
- The evaluation can be rerun from documented steps and its results are honestly reported.
- Setup/demo instructions are updated.
- `pytest -q` passes and the exact command/result is reported.

## Working agreement

Use a feature branch and small PRs. Maintain a runnable integration branch. Coordinate interface changes with the other owners and test the full flow before declaring completion.
