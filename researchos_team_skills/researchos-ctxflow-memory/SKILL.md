---
name: researchos-ctxflow-memory
description: Integrate the existing CtxFlow memory engine with ResearchOS project persistence, provenance-aware research memory, retrieval, supersession handling, and token-budgeted context selection.
---

# ResearchOS CtxFlow & Memory Skill

## Mission

Make ResearchOS retain useful project knowledge across research runs. Reuse the existing memory layer in `src/ctxflow/memory/`; do not replace it with a new memory platform.

Critical fact: the memory layer is **implemented but not wired**. `CtxFlow` (`src/ctxflow/__init__.py`) uses `ContextGraph`, not `MemoryStore`. ResearchOS reads and writes that in-memory graph only. There is no `ContextProvider`, no project-scoped memory, and no persistence across restarts. Wiring that gap is the core of this workstream.

## Current implementation (verified at `34cf19f`)

- `src/ctxflow/memory/store.py`
  - Enums: `MemoryType`, `MemoryTier` (`working`/`episodic`/`semantic`), `ValidityState` (`valid`, `stale`, `contradicted`, `requires_review`, `superseded`), `Relation` (incl. `SUPERSEDES`, `CONTRADICTS`, `DERIVED_FROM`), `SourceType`.
  - Records: `Memory`, `MemoryVersion`, `Edge`, `Provenance`, `ScoredId`, `Subgraph`.
  - `MemoryStore` protocol (async): `add`, `get(memory_id, version=None, as_of=None)`, `create_version(...)`, `search(query_emb, query_text, k, *, types, include_archived, include_history, as_of)`, `neighbors(...)`, `get_version_history(...)`.
  - Optional capabilities used by `EventIngestor` when present: `add_edge`, `add_provenance`, `claim_event`, `persist_ingestion`.
- `src/ctxflow/memory/inMemorystore.py` — deterministic store; `search()` fuses keyword and dense signals with reciprocal-rank fusion (k=60), then sorts by `(-score, memory_id)`.
- `src/ctxflow/memory/postgres_store.py` — pgvector store. With a query embedding it does dense cosine search (`1 - (embedding <=> $1)`); without one it does `ILIKE` keyword search and returns `score = 0.0`. It honours `types` and `archived`, and excludes `superseded` unless `include_history` is set.
- `src/ctxflow/memory/ingestion.py` — `Event`, `IngestResult`, `EventIngestor.ingest(event)`; idempotent by SHA-256 of `event_id`; classifies `MemoryType` by simple text rules; embeds; adds a `FOLLOWS` edge per session; records `Provenance`.
- `src/ctxflow/memory/tokens.py` — `TokenizerAdapter`, `SimpleTokenizer` (`simple-v1`, regex word/punctuation tokens), `count_tokens(memory, tokenizer)` which caches into `memory.token_counts`.
- `src/ctxflow/memory/embeddings.py` — `Embedder` protocol, deterministic `HashEmbedder(dimension=128)`, `embed_text()`.
- `src/ctxflow/memory/runtime.py` — `DatabaseConfig`, `load_database_config()` (reads `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` from `.env`/env), `create_pool()`, `PostgresMemoryRuntime.create()` / `close()`.
- `migrations/001_memory_schema.sql` — `ingestion_events`, `memories`, `memory_versions`, `graph_edges`, `provenance`; `VECTOR(128)`; HNSW cosine index.
- Tests: `tests/test_memory_vertical_slice.py`, `tests/test_postgres_runtime.py`, `tests/test_postgres_integration.py` (marker `postgres`).

Known constraints you must design around:

- `Memory` has `session_id` but **no `project_id`**, and the `memories` table has no project column. Project isolation does not exist yet.
- The existing `CtxFlow` graph stores `project_id` in paper/note metadata, but `CtxFlow.query()` has no project filter. Only `GET /api/notes` filters by project.
- Postgres keyword-only search returns `score = 0.0` for every row and orders by `created_at`; it is not ranked relevance. Do not present it as hybrid retrieval.
- `InMemoryMemoryStore.search()` currently ignores `include_history` and does **not** filter `superseded`; `PostgresMemoryStore` does. Either fix the in-memory store or filter explicitly in the adapter, and add a parity test.
- No background re-embedding or migration tool; schema changes are manual SQL.

## Before coding

1. Read `store.py`, `inMemorystore.py`, `postgres_store.py`, `ingestion.py`, `tokens.py`, `runtime.py`, and the migration.
2. Confirm which parts actually run here: `pytest -q tests/test_memory_vertical_slice.py tests/test_postgres_runtime.py`.
3. Read how ResearchOS currently persists research artifacts: `src/researchos/agents/reader.py`, `src/researchos/api/routes/papers.py`, `src/researchos/api/routes/notes.py`.
4. Agree the adapter contract and the project-key decision with orchestration and the UI/API owner **before** writing code.
5. Write a short plan naming the exact file and gap.

## Ownership

- The adapter between ResearchOS artifacts and `ctxflow.memory`.
- Project-level memory mapping and retrieval.
- Context candidate ranking and token-budgeted selection.
- Provenance, supersession, contradiction, and history handling.
- Persistence and isolation tests.
- Retrieval diagnostics (selected/excluded records, token estimates, reason).

Out of scope: the `SkillRouter`/run lifecycle, PDF parsing, citation validation, and the UI.

## Adapter contract (proposed; it does not exist yet)

Create a new, narrow module, for example `src/researchos/memory/context.py`. Keep it optional so ResearchOS still runs when memory is disabled.

```python
from dataclasses import dataclass
from typing import Protocol

# NOTE: `Memory` has no `superseded_by` field. Derive it from a
# `Relation.SUPERSEDES` edge (or a future column), and keep the raw
# `validity` value so callers can distinguish superseded from stale.

@dataclass(frozen=True)
class ContextRecord:
    memory_id: str
    text: str
    tokens: int
    memory_type: str
    validity: str
    score: float
    source_type: str | None = None
    source_id: str | None = None
    superseded_by: str | None = None

class ContextProvider(Protocol):
    async def retrieve(
        self,
        project_id: str,
        query: str,
        token_budget: int,
    ) -> list[ContextRecord]: ...
```

Implementation notes:

- Build on `MemoryStore.search()` + `get()` + `neighbors()`; do not re-implement search.
- Score with `ScoredId.score`; if you add signals (validity, evidence quality, recency), keep them explainable and log them.
- Count tokens with `SimpleTokenizer` / `count_tokens()` from `ctxflow.memory`, not `len(text) // 4`. The rest of the repo currently uses 4 chars/token (`GraphQuerySkill`, `SynthesizerAgent`, `src/researchos/eval/metrics.py`); if you standardize, update those call sites and say so.
- Return provenance fields (`source_type`, `source_id`, `superseded_by`) plus a `tokens` estimate. Do not return opaque strings.
- Never return `ValidityState.SUPERSEDED` rows as current truth; expose them only with an explicit flag/history view.

## Project scope decision (do this first)

Choose one and document it in the PR:

1. **`session_id` as the project key (smallest change).** Works today, no migration. It conflates chat sessions with projects, so state the limitation.
2. **Add `project_id` to memory (correct model).** Requires a migration (e.g. `migrations/002_memory_scope.sql`), changes to `Memory`, both stores, `search()`, and `EventIngestor`, plus tests for cross-project isolation. Coordinate this as a shared schema change.

Do not silently filter in the adapter by fetching everything and discarding rows in Python; that does not isolate data and will not scale.

## Implementation order

1. Decide the project key and, if needed, add the migration + store support.
2. Map existing ResearchOS artifacts to memory records with stable IDs and provenance:
   - paper → `MemoryType.DOCUMENT`, `SourceType.DOCUMENT`
   - claim/evidence → `MemoryType.FACT` or `OBSERVATION`, `Relation.DERIVED_FROM` → paper
   - note → `MemoryType.OBSERVATION`, `SourceType.USER_MESSAGE`
   - decision → `MemoryType.DECISION`
3. Implement the baseline adapter using `search()`; add graph expansion via `neighbors()` only if measured useful.
4. Rank with query relevance plus explainable signals (validity, source type, evidence confidence). Use recency only where it is meaningful.
5. Estimate tokens and fill the budget deterministically (e.g. score order, stop at budget); record excluded candidates and why.
6. Handle supersession through `ValidityState` + `Relation.SUPERSEDES` and `create_version()`; preserve history.
7. Expose diagnostics (selected/excluded, scores, token estimates) through the agreed API or a debug method.
8. Wire the adapter behind a flag in `create_app()` only after coordination; keep the default path working.
9. Test persistence across restart with `PostgresMemoryStore` (marked `postgres`); test the rest with `InMemoryMemoryStore`.

## Important constraints

- Keep CtxFlow behind the adapter so ResearchOS can run without advanced memory.
- Do not build a second vector database, embedding service, or ORM. pgvector and `asyncpg` are already dependencies.
- Do not implement PCST, cache-aware serving, or complex reranking until a simple baseline is measured.
- Do not confuse LLM KV-cache behaviour with application-level context retrieval.
- Do not claim context improves quality without evaluation.
- Do not take ownership of the router, source parsing, or the UI.

## Acceptance criteria

- Orchestration can request project context through the agreed, documented interface.
- Returned records include stable IDs, provenance, token estimates, and validity state.
- Retrieval respects the token budget within the documented estimator's tolerance.
- Superseded items are handled explicitly without erasing historical records.
- Project data is isolated; a test proves project A cannot retrieve project B's records.
- Selected/excluded records, scores, and token estimates are inspectable.
- Tests cover empty projects, budget edge cases, duplicates, supersession, isolation, and persistence (Postgres test marked `postgres`).
- The app still works with the adapter disabled.
- `pytest -q` passes and the exact command/result is reported.

## Working agreement

Own the adapter and memory-related files. Coordinate schema changes (especially the project-scope migration) with the team. Avoid modifying shared orchestration/UI code unless required and agreed. Use feature branches and small PRs.
