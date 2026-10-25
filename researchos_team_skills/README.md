# ResearchOS Team Skills

Four independent agent skills for parallel implementation of the ResearchOS MVP in **this** repository.

- **Repository:** `ProjectZero24/CtxFlow` (this checkout; integration branch `Adi/feat/v1`)
- **Audit baseline:** commit `34cf19f`. Re-audit before trusting any statement below.
- **Detailed map:** see `REPO_HANDOFF_SUMMARY.md` at the repository root.

> These skills previously pointed at `quantum-coderX/Research_Agent` and assumed LangGraph, checkpointing, and a Laya model. **None of those exist here.** Everything below was verified against the code in `src/`.

## Skills

1. `researchos-orchestration/SKILL.md` — Person 1: `SkillRouter` intent routing, agent pipelines, run lifecycle, resumability.
2. `researchos-evidence-retrieval/SKILL.md` — Person 2: arXiv/Semantic Scholar search, PDF parsing, evidence, citations.
3. `researchos-ctxflow-memory/SKILL.md` — Person 3: `ctxflow.memory` integration, project memory, token-budgeted context.
4. `researchos-frontend-integration-evaluation/SKILL.md` — Person 4: workspace UI, API integration, end-to-end tests, evaluation.

## Shared repository facts

| Area | Reality at `34cf19f` |
|---|---|
| Core engine | `src/ctxflow/__init__.py` → `CtxFlow` (`ingest`, `query`, `prune`, `research_trace`, `export`, `import_`) over `ContextGraph` in `src/ctxflow/graph.py` |
| Memory layer | `src/ctxflow/memory/` → async `MemoryStore`, `InMemoryMemoryStore`, `PostgresMemoryStore`, `EventIngestor`, `HashEmbedder`, SQL in `migrations/001_memory_schema.sql` |
| Orchestration | `src/researchos/agents/router.py` → `QueryIntent`, `classify_intent()`, `_EXECUTION_PLANS`, `SkillRouter` (keyword routing, **no LLM, no LangGraph**) |
| Agents | `retriever`, `reader`, `synthesizer`, `critic`, `graph_query` (`TraceAgent`) under `src/researchos/agents/` |
| Skills | `literature_search`, `paper_reader`, `graph_query`, `research_trace`, `review_writer` under `src/researchos/skills/`; registered in `src/researchos/api/server.py` |
| API | `create_app()` in `src/researchos/api/server.py`; routes in `src/researchos/api/routes/`; schemas in `src/researchos/api/schemas.py` |
| UI | `src/researchos/web/` (`index.html`, `styles.css`, `app.js`), served by FastAPI `StaticFiles` at `/` |
| Evaluation | `src/researchos/eval/` → `BenchmarkRunner`; `python -m researchos.eval`; 3 systems, default suite = 3 papers / 2 questions |
| Tests | `tests/` (pytest, `pythonpath = src`) |

### Known gaps (do not describe these as working)

- `ctxflow.memory` is implemented but **not wired** into `CtxFlow` or ResearchOS. There is no `ContextProvider` anywhere.
- `CtxFlow` is in-memory. Nothing auto-persists or auto-resumes it; only `export()`/`import_()` to JSON/binary exist. `ctxflow.memory` has a PostgreSQL path, but it is not wired to `CtxFlow` or ResearchOS.
- No plan generation or human plan-confirmation step; `/api/chat` is single-shot.
- `project_id` is stored in node metadata, but `query()` does not filter by it. Only `/api/notes` filters by project.
- `ReaderAgent` only parses a PDF when the paper dict already contains `pdf_path`; there is no PDF downloader.
- Search deduplicates by lowercased title only (not DOI / arXiv ID).
- No citation-string validator; `ReviewWriterSkill` emits `[Node:ID]` references, not DOI citations.
- Evaluation default suite is small and deterministic (no LLM judge).

## Team-wide rules

- Audit the current repository before editing; preserve working code.
- Re-run the relevant tests before and after your change, and report the actual command and result.
- Agree shared schemas and API contracts before parallel implementation. The single schema module today is `src/researchos/api/schemas.py`.
- Add new dependencies or frameworks only with a measured need. Do not reintroduce LangGraph/Laya to match old docs.
- Use feature branches and small pull requests.
- Do not invent features, citations, test results, or evaluation improvements.
- Keep the integration branch runnable.
- Each skill defines ownership, boundaries, sequence, and acceptance criteria.

## Verification commands

```bash
pip install -e ".[dev,researchos]"
pytest -q                                   # full suite
pytest -q tests/test_agents.py tests/test_skills.py tests/test_api.py tests/test_workspace_api.py
python -m researchos.eval                   # markdown comparison table
python -m researchos.eval --json --out benchmark-report.json
researchos-api                              # UI at http://127.0.0.1:8000/
```

The full suite reported **120 passed, 1 skipped** at `34cf19f`; the skip is `tests/test_postgres_integration.py` (needs a live PostgreSQL + pgvector instance, marker `postgres`). Treat that as a baseline to compare against, not a guarantee.

## How to use

Copy the relevant skill folder into the coding agent's supported skills directory, or paste its `SKILL.md` as that agent's project instructions. Exact installation paths depend on the coding agent.
