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

**S0 status (26 Oct 2026):** Completed on `feat/abinav-ui-eval`. UI actions use
`/health`, `/api/graph/data`, `/api/notes`, `/api/papers/ingest`,
`/api/papers/upload`, `/api/chat`, and `/api/trace`; at S0, the UI did not use
`/api/stream`. Smoke verified these routes and assets return 200. S0 observed
SSE events `start`, `agent_completed`, and `done`; S3 consumes the event fields
documented in the orchestration skill. The stream still has no run ID or formal
partial-result semantics.

Ownership: Abinav keeps the UI/tests/eval, query scoring, prompts, and
synthesizer positional work; Adithyan owns paper reader and extractor unless
otherwise agreed. Other-owner contracts still needed: orchestration outcomes
and progress, evidence metadata/access/page/section/citation resolution,
project scoping/persistence, and `python-multipart` packaging. Trace currently
returns 200 for an unknown ID; trace source metadata is omitted.

S0 baseline: focused tests **11 passed** (55 warnings). Test dependencies,
including `python-multipart`, were installed in `.venv` only. At S0,
plan/confirmation, restart persistence, source access status, and report export
were not implemented.

**S1 status (26 Oct 2026):** UI states for loading, empty, failure, and running
are explicit; malformed API responses and failed health checks do not display
as success/empty. Citation IDs are checked against the loaded graph; stale
graph/notes responses are ignored. The UI does not infer partial success:
`ChatResponse` has no partial-result field, so completion-vs-partial remains
pending schema agreement. Project scope and missing plan confirmation are
disclosed in the UI. Focused tests: **12 passed** (60 warnings); JS syntax,
diff checks, and browser smoke passed.

**S2 status (26 Oct 2026):** Project labels can be opened from an accessible
recent-label list and the current label is remembered in browser localStorage.
Only labels persist; the UI states that project data is in-memory, and graph
and chat remain globally scoped. The library exposes real graph papers and
expandable extracted evidence. Evidence inspection shows available title,
authors, year, DOI/arXiv, URL, PDF page count, claim page/section, and access
status; absent API fields are labelled “Not provided by API” and full-text
access remains explicitly unverified. No project, evidence, or schema endpoint
was invented. Focused tests: **13 passed** (65 warnings); browser smoke verified
metadata, evidence navigation, unknown source status, and label restoration.
Actual access-status classification remains pending Adithyan's API contract.

**S3 status (26 Oct 2026):** The workspace consumes the documented
`/api/stream?query=` SSE sequence: `start` (`query`, `message`),
`agent_completed` (`agent`, `success`, `duration_ms`, optional `error`), and
`done` (`success`, `data`, `metadata`). Per-agent status and elapsed time are
shown; raw error payloads are not rendered. Disconnects and malformed events
are reported, and a disconnect explicitly notes that server-side work may
continue. The API has no run ID, cancellation/resume, or formal partial-result
contract; the UI does not claim those capabilities or definite completion.

Trace now shows counts and explicit empty states for provenance, superseded
claims, contradictions, and sources. Superseded claims use the existing red
trace style; contradictions use the warning style. Blocked-step data is
explicitly marked “not reported by API.” Concurrent trace requests cannot
overwrite a newer selection. Focused tests: **14 passed** (70 deprecation
warnings); `node --check src\researchos\web\app.js` and `git diff --check`
passed. TestClient verified the live SSE event sequence and payload shapes.
Browser smoke exercised a live stream with both an empty-graph result and an
ingested claim, verified its citation opened the two-step provenance trace,
and confirmed the empty supersession/contradiction states and source metadata.

**S4 status (26 Oct 2026):** No plan/confirmation interface was added because
the orchestration API still has no plan or confirmation contract; questions
continue to run immediately and this limitation remains visible. A real
non-empty streamed answer can now be exported as Markdown. API-provided and
inline `[Node:ID]` citations are resolved against loaded graph data and checked
through `/api/trace` before they are included; export fails visibly when a
citation cannot be verified. Answers with no citations are clearly labelled
as such in the export.

The evaluation suite now has **5 synthetic papers and 10 questions**, with a
documented rationale per question. The run uses identical question suite and
final `k=5` across three deterministic systems, with no provider/model/prompts;
the report records system-specific retrieval details, token estimation,
limitations, command, date, source commit, and dirty-tree status. An audit
found that citation lists without a provenance trace were incorrectly earning
provenance credit; the metric now requires a trace. The rerun report records
graph direct-query accuracy **0.80**, single-agent flat accuracy **0.50**, and
multi-agent-shaped flat accuracy **0.50**; provenance accuracy is **0.80** for
the graph and **0.00** for both flat systems. These are descriptive results
from a small synthetic suite, not statistically significant findings. The
dated report is [2026-10-26.json](../eval/2026-10-26.json). Command:
`.venv\Scripts\python.exe -m researchos.eval --json --out docs\eval\2026-10-26.json`.
The report marks the overall tree dirty because concurrent S0–S4 UI/document
changes remain outside the evaluation commit; its source SHA identifies the
committed evaluation code and dataset (`f450868`). The evaluator and dataset
were committed in `f450868`; the generated report was committed separately in
`0772188`. Focused evaluation, workspace, and API tests:
**23 passed** (70 deprecation warnings); JavaScript syntax and diff checks
passed. Browser smoke confirmed a live answer can produce a Markdown download
containing the answer, resolved citation, and provenance/source details.

**S5 status (26 Oct 2026):** The evaluation now counts context tokens with
`SimpleTokenizer` (`simple-v1`) rather than a four-characters-per-token
estimate. The Synthesizer records the SHA-256 fingerprint of its system prompt,
the estimated system and combined prompt token counts, and tokenizer ID in its
agent result metadata. These are reproducible estimates, not provider token
counts. The report includes the fingerprint and token counts as a
`used_by_benchmark: false` reference: the benchmark remains deterministic and
does not execute the production synthesis prompt. No `PromptRegistry` exists,
and the current API does not expose agent metadata in trace/run events, so the
plan's conditional trace/run-event fingerprint integration remains pending
that contract; no router or API behavior was changed.

A controlled-provider TestClient E2E verifies the served workspace, ingestion,
chat answer/citation/trace, SSE completion, and prompt fingerprint/accounting.
A second provider-free smoke exercises the default app through ingestion,
chat, SSE, and trace. The full deterministic 5-paper/10-question evaluation
was rerun and committed as [2026-10-26-s5.json](../eval/2026-10-26-s5.json)
in `4fab11b`.
Focused tests: **26 passed** (80 deprecation warnings). Full suite:
**151 passed, 6 skipped** (85 deprecation warnings). `node --check
src\researchos\web\app.js` and `git diff --check` passed. The report identifies
the source commit, dirty worktree, command, estimates, and benchmark
limitations. It is intentionally a separate report from the S4 report.

**S6 status (26 Oct 2026):** README now documents fresh-checkout installation
and launch commands for Windows and macOS/Linux, a truthful workspace demo
path, API docs/endpoints, test commands, and the S5 evaluation rerun. Its
limitations section explains volatile in-memory data and project-label scope,
missing run/confirmation lifecycle and access-status contracts, and all
benchmark caveats. Corrected the README's prior claim that the graph
benchmark runs four agents: it is a direct graph query, as the report states.

The UI now gives the API health label an accessible live status and retains
the health-check failure reason for inspection. Structured API validation
details are rendered as field-specific messages instead of `[object Object]`;
existing empty, unavailable, failure, and partial-result states remain
distinct. Focused workspace/API tests: **17 passed** (80 deprecation
warnings); `node --check src\researchos\web\app.js` and `git diff --check`
passed. Browser smoke verified API-offline status with the health error detail,
field-specific messages for a controlled 422 response, then the default
workspace's real ingestion and streamed-answer flow. Full suite: **151 passed,
6 skipped** (85 deprecation warnings).

**S7 status (26 Oct 2026):** Rehearsed the documented demo against a fresh
local server: health/UI startup, real paper ingestion, streamed synthesis,
citation-to-trace navigation, and Markdown export with verified citation and
source details. Also rehearsed explicit API-offline and structured validation
error states. Re-ran `python -m researchos.eval --json`; all three systems
reproduced the committed report metrics (graph accuracy/provenance **0.80 /
0.80**, each flat baseline accuracy/provenance **0.50 / 0.00**) with `k=5`,
10 questions, and 5 papers. Full suite: **151 passed, 6 skipped**; focused
workspace/API suite: **17 passed**. No live provider or database is required
for these checks.

The local worktree passes the freeze checks, but it is not a clean committed
release: accumulated Abinav S0–S6 implementation changes remain uncommitted.
Keep the build as a freeze candidate pending review and integration; do not
present missing cross-owner contracts (durable projects/runs, plan
confirmation, formal partial-result semantics, or source access guarantees) as
implemented.

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
- At S0 the UI used `/api/chat` and waited. S3 now consumes `/api/stream` for
  live per-agent progress; the REST `/api/chat` route remains available.
- The static mount is registered **last** so `/api`, `/docs`, and `/openapi.json` win.

What does not exist:

- Project creation/persistence (project id is free text).
- Plan generation/editing/confirmation, a run resource (`/api/runs/...`), resume.
- Run IDs, status persistence, cancellation, or resume.
- Source access/download status.
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

### Ownership reconciliation (recorded in S0)

Commit `6ae8b0f` assigns you frontend/integration/evaluation. The MVP plan §7.2 also names you owner of `query.py`, `llm_extractor.py`, `synthesizer.py`, `prompts/`, and `paper_reader.py`.

Recommended split, to be recorded in the S0 notes:

| Area | Recommendation |
|---|---|
| `ui/` + `api/` integration + `eval/` | **You keep** |
| `ctxflow/query.py` + `researchos/prompts/` | **You keep** — they determine the token efficiency you measure |
| `agents/synthesizer.py` | **You keep** — positional-bias placement is your seminar |
| `skills/paper_reader.py` | Hand to Adithyan (evidence owner) |
| `ctxflow/llm_extractor.py` | Adithyan — evidence/extraction scope |

The S0 ownership decision is recorded at the top of this handbook. Shared
changes still require coordination with their listed owners.

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
| 4 | SSE progress consumer (`/api/stream`) after Harikesh publishes event names (**UI complete S3; cancel/resume unavailable**) | UI shows per-step progress; cancel/resume only if backend supports it |
| 5 | Plan display/confirmation (only when backend exists) | Edit/confirm/cancel work; feature-flagged; not faked |
| 6 | Source/evidence inspection: title, authors, year, DOI/arXiv, page/section, `access_status` | Abstract-only vs full-text is visible |
| 7 | Citation navigation: `[Node:ID]` → trace; unresolvable citation visibly flagged | No dead citation rendered as verified |
| 8 | Trace panel: supporting chain, superseded nodes in red, contradiction edges, blocked-step badge (**counts/empty states complete S3; blocked data unavailable**) | Demo step 3 passes without dev tools |
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
6. **Add SSE progress** after the event contract is stable. Do not invent event names. (**UI complete S3; no run IDs or cancellation/resume.**)
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
| **S1** 2–6 Nov | UI state honesty; error/empty/partial; schema alignment (**UI complete 26 Oct; partial-result schema pending owner agreement**) | No silent fallback |
| **S2** 9–13 Nov | Project shell; library/evidence inspection; access-status display (**UI complete 26 Oct; actual access-status contract pending Adithyan**) | Source status visible |
| **S3** 16–20 Nov | SSE progress consumer; trace panel completion (superseded/contradiction) (**UI complete 26 Oct; run/partial semantics remain unavailable**) | Demo step 3 passes |
| **S4** 23–27 Nov | Plan/confirmation UI behind flag (if backend exists); report export; eval suite v1 (10–20 Q) (**report export + 10Q suite complete 26 Oct; plan UI pending API; evaluation code/report committed separately**) | Feature-flagged; report committed |
| **S5** 30 Nov–4 Dec | Full eval run; E2E mock + smoke; prompt hash/token accounting (**implemented 26 Oct; registry-to-trace/run-event integration awaits a PromptRegistry/API contract**) | Numbers reproducible |
| **S6** 7–11 Dec | README/demo docs; empty/error polish; limitations section (**implemented 26 Oct**) | Setup works from scratch |
| **S7** 14–18 Dec | Freeze; demo rehearsal (**rehearsal and validation complete 26 Oct; freeze candidate awaits review/integration of uncommitted S0–S6 changes**) | Frozen build |

---

## 11. Definition of Done

- [x] The implemented project-to-answer flow works in the UI; unimplemented steps are not presented as done.
- [x] Progress and errors are understandable; partial-result semantics remain explicitly limited by the API contract.
- [x] Sources and citations are inspectable; unresolvable citations are visible.
- [x] Empty/error API responses render correctly.
- [x] E2E test uses a controlled provider; smoke test covers the default setup without a live provider.
- [x] Evaluation can be rerun from documented steps; results are reported with limitations.
- [x] `pytest -q` green; exact command/result reported.
- [x] README/demo instructions updated.

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
| SSE emits per-agent events only after each agent returns | No intra-agent progress; no run IDs/cancel/resume | Show event states, and disclose the missing lifecycle contract |
| `project_id` filters notes only | UI implies project isolation that does not exist | Label the limitation, or wait for Christo |
| `CtxFlow` is in memory | Refresh/restart loses the workspace | Show it; do not imply persistence |
| `ChatRequest.session_id` / `token_budget` accepted but ignored | False sense of control | Do not expose controls that do nothing |
| Eval default suite is 3 papers / 2 questions | Numbers are not credible | Expand and document |
| `_evaluate_ctxflow()` queries the graph, does not run agents | "4-agent" claim is false | Report the actual method |
| Supersession is manually injected in the eval | Does not test the detector | State it in limitations |
| Metrics are substring-based | Sensitive to wording, not semantics | Do not overclaim |
| Baselines use `HashingEmbedder` (hashed bag-of-words) | Not semantic retrieval | Say "hashed lexical baseline" |
| Synthesizer context packing still budgets at 4 chars/token; evaluation estimates use `SimpleTokenizer` | Runtime budget and reported token estimates are different measures; neither is a provider token count | Keep the distinction explicit; do not present either as actual provider usage |
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
