# CtxFlow

A schema-agnostic, incrementally-built graph memory framework for LLM agents.

## Core Principles

1. **Schema-Agnostic Model**: Generic `Node` and `Edge` schemas with free-form `node_type` and `relation_type` strings. Fits any agent domain without hardcoding node types.
2. **Incremental Ingestion**: Single entry point `ingest(content)` operating in $O(1)$ time relative to graph size. Supports explicit linking (`source_id`) and implicit tag-based top-$k$ linking.
3. **Query Engine**: Lightweight composite scoring combining tag overlap (Jaccard), recency decay, and BFS shortest-path proximity from an anchor node:
   $$\text{score}(n) = \alpha \cdot \text{tag\_overlap}(n, q) + \beta \cdot \text{recency}(n) + \gamma \cdot \text{proximity}(n, \text{anchor})$$
4. **Graph Governance**: Degree cap enforcement during ingestion to prevent hubs from dominating retrieval, plus optional query-time degree normalization.
5. **Decoupled Pruning**: Separate maintenance pass supporting `drop` and `summarize` (cluster compaction) strategies based on staleness signals.
6. **Persistence**: Export and import graphs via JSON or MessagePack binary formats.

---

## Installation

```bash
pip install -e .
# Optional extras:
# pip install -e ".[nlp]"     # spaCy support
# pip install -e ".[binary]"  # MessagePack binary serialization
```

---

## Quickstart

```python
from ctxflow import CtxFlow, CtxFlowConfig

# Initialize framework facade
ctx = CtxFlow()

# 1. Ingest context units
obs_id = ctx.ingest(
    "The agent detected a wall obstacle directly ahead at distance 2 meters.",
    node_type="observation",
)

dec_id = ctx.ingest(
    "The agent decided to turn left to avoid the obstacle.",
    node_type="decision",
    source_id=obs_id,  # Explicit edge: dec_id follows obs_id
)

# 2. Query graph memory
results = ctx.query("What obstacle was detected?", k=3, anchor=dec_id)
for r in results:
    print(f"[{r.node.node_type}] Score: {r.score:.3f} | {r.node.summary}")

# 3. Prune stale nodes
removed_ids = ctx.prune(threshold=0.8, strategy="summarize")

# 4. Export state
ctx.export("agent_memory.json")
```

---

## Configuration

Customize framework knobs using `CtxFlowConfig`:

```python
config = CtxFlowConfig(
    degree_cap=30,             # Max fan-out per node
    max_link_k=3,              # Top-k tag similarity auto-links
    alpha=0.6,                 # Tag overlap score weight
    beta=0.2,                  # Recency score weight
    gamma=0.2,                 # Proximity score weight
    bfs_max_depth=3,           # Max BFS hops from anchor
    degree_normalization=True, # Dampen hub scores by degree
)

ctx = CtxFlow(config=config)
```

---

## Testing

Run the full test suite with `pytest`:

```bash
pytest tests
```

## Memory vertical slice

The `ctxflow.memory` package includes the production memory path while
retaining the deterministic in-memory implementation for local tests:

```python
from ctxflow.memory import (
    Event, EventIngestor, HashEmbedder, InMemoryMemoryStore, utc_now,
)

store = InMemoryMemoryStore()
ingestor = EventIngestor(store, HashEmbedder())
result = await ingestor.ingest(Event(
    event_id="event-1",
    session_id="session-1",
    ts=utc_now(),
    role="user",
    content="The deployment uses the blue environment.",
))
matches = await store.search(
    await HashEmbedder().embed("blue deployment"),
    "blue deployment",
    k=5,
)
neighbors = await store.neighbors(result.memory_ids[0], depth=2)
```

`PostgresMemoryStore` uses the schema in
`migrations/001_memory_schema.sql` and pgvector cosine search. Embeddings,
tokenizers, and the PostgreSQL driver are intentionally adapter boundaries;
`HashEmbedder` and `SimpleTokenizer` provide deterministic development
fallbacks without requiring a model server or database in CI.

Each ingested memory is classified, embedded, token-counted, importance-scored,
and checked for duplicate links before persistence. An `LLMEdgeProposer` can be passed to `EventIngestor` when semantic graph edges
are desired. Core memories and deterministic edges are persisted atomically;
LLM-proposed edges are added in a separate post-commit enrichment step so
provider failures cannot roll back committed ingestion.

Deduplication retrieves at most five same-type ANN candidates, then applies a
cosine similarity threshold of `>= 0.95`. A qualifying candidate is
treated as the canonical memory: the new memory is retained, a `duplicate_of`
edge is added, and the canonical memory's access count and importance are
updated. PostgreSQL uses the `memories_embedding_hnsw_idx` pgvector HNSW index
for current-memory retrieval. Historical `as_of` searches use version rows and
are not HNSW-indexed.

For the PostgreSQL-backed event path, place `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, and optionally `GROQ_API_KEY` in the project-root
`.env` file. Groq uses the `openai/gpt-oss-20b` model for structured memory
extraction and graph edge proposals. No embedding API key is required.
Provider behavior can be configured through `create_groq_extractor`,
`create_groq_edge_proposer`, and `PostgresMemoryRuntime.create`, including the
LLM request timeout, extraction retries, ingestion provider timeout, and
ingestion provider retries.

CtxFlow uses one embedding implementation: the local
`BAAI/bge-small-en-v1.5` Sentence Transformers model. It produces normalized
384-dimensional vectors for both stored memories and retrieval queries. This
replaces the earlier 128-dimensional embedding configuration; existing
databases must run the migration and re-embedding process below. It
does not make embedding API calls during inference after the model is cached.
The first initialization may download the model into the Sentence Transformers
cache; verify it locally with:

```powershell
python -c "from sentence_transformers import SentenceTransformer; m=SentenceTransformer('BAAI/bge-small-en-v1.5'); print(m.get_sentence_embedding_dimension())"
```

The PostgreSQL schema must use `vector(384)` for both `memories.embedding` and
`memory_versions.embedding`. Before applying
`migrations/004_bge_small_384_dimension.sql`, take a database backup. The
migration preserves old vectors in a backup table, changes the vector columns
without truncating or padding, and rebuilds the HNSW index. Run
`scripts/reembed_bge.py` immediately afterward to regenerate vectors from the
stored memory/version text. The script updates only embedding columns and
`embedding_model`; memories, IDs, versions, provenance, graph edges, and
ingestion events are preserved.

Runtime creation prefers the local BGE model. If the optional
`sentence-transformers` dependency or the cached BGE model is unavailable,
`PostgresMemoryRuntime.create()` automatically falls back to the deterministic
384-dimensional `HashEmbedder` and logs a warning. The hash fallback is
appropriate for development and availability, but it does not provide the
same semantic quality as BGE. An explicitly supplied embedder is always used
unchanged.

```python
from ctxflow.memory import PostgresMemoryRuntime

async with await PostgresMemoryRuntime.create() as runtime:
    result = await runtime.ingestor.ingest(event)
```
