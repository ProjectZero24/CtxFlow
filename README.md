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

---

## ResearchOS — multi-agent research workspace

`src/researchos/` is the application layer from the FYP proposal: four
agents (Retriever → Reader → Synthesizer → Critic), four schema-registered
skills, a FastAPI backend, a bundled Research Trace UI, and an evaluation
harness with two flat-RAG baselines.

### Run the workspace from a fresh checkout

```bash
python -m venv .venv
```

Install the ResearchOS and test dependencies, then start the API. On Windows
PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[researchos,dev]"
.\.venv\Scripts\python.exe -m researchos.api.main
```

On macOS/Linux:

```bash
.venv/bin/python -m pip install -e ".[researchos,dev]"
.venv/bin/python -m researchos.api.main
```

Alternatively, after installation, run `researchos-api`. Open
<http://127.0.0.1:8000>; `/health` should return an `ok` status. The
`researchos` extra includes the optional PDF parser (`pymupdf`); the metadata
and abstract workflow does not require a PDF upload.

### Workspace demo

1. Open the workspace and check that the API status is online.
2. Add a paper using its title and abstract (or upload a PDF).
3. Ask a question about ingested evidence; the workspace reports stream steps
   and distinguishes answers, empty results, and failures.
4. Open an answer citation or graph node to inspect its Research Trace.
5. Export a Markdown report from an answer when available.

The workspace is dependency-free (vanilla JS/SVG) and ships inside the wheel;
it needs no npm build. Clicking a citation or graph node opens the Research
Trace panel: provenance chain, superseded claims, contradictions, and source
papers. API errors and unavailable/empty states are presented explicitly.

The API contract can be inspected at <http://127.0.0.1:8000/docs>. Main UI
endpoints:

| Area | Endpoint |
|---|---|
| Workspace UI / Research Trace | `GET /` |
| Health & graph stats | `GET /health` |
| Agent chat (SSE also at `/api/stream`) | `POST /api/chat` |
| Paper ingestion (metadata + abstract) | `POST /api/papers/ingest` |
| PDF ingestion (Paper Reader skill) | `POST /api/papers/upload` |
| Researcher notes | `POST/GET /api/notes` |
| Graph data / stats | `GET /api/graph/data`, `GET /api/graph/stats` |
| Research Trace | `POST /api/trace` |
| Model token/latency usage | `GET /api/model/usage` |
| Skill discovery | `GET /api/skills` |
| OpenAPI docs | `GET /docs` |

### Current limitations

Project labels are not isolated projects: they scope the displayed paper list
and notes only. Graph and chat data are shared in memory and disappear when the
server restarts. Questions run immediately; plan review/confirmation,
cancellation, resume, and durable run history are not implemented. The stream
reports agent completion events but has no run ID or formal partial-result
contract; disconnecting does not guarantee that server work stops. Request
`session_id` and `token_budget` fields do not currently provide session
isolation or control the runtime token budget. The workspace displays available
source metadata, but a missing access/page/section field means that full-text
access or location is unverified.

### Model consumption

Model calls are **off by default**. Without `RESEARCHOS_MODEL_ENABLED=1`,
`create_app()` builds no model client and agents keep their deterministic
paths, so tests and the offline demo do not make network calls.

Enable the gateway and pick a provider (install the model extra first:
`pip install -e ".[researchos,llm]"`):

```bash
export RESEARCHOS_MODEL_ENABLED=1
export RESEARCHOS_MODEL_PROVIDER=groq       # groq | ollama | nvidia | openrouter | hf
export RESEARCHOS_MODEL_ID=openai/gpt-oss-20b
export RESEARCHOS_MODEL_TIMEOUT_S=20
export RESEARCHOS_MAX_RETRIES=2
export GROQ_API_KEY=...
researchos-api
```

`RESEARCHOS_MODEL_ID` defaults to the provider preset (`qwen3:8b` for Ollama,
`meta/llama-3.3-70b-instruct` for NVIDIA, and so on). `RESEARCHOS_MODEL_BASE_URL`
and `RESEARCHOS_MODEL_API_KEY` are optional escape hatches for self-hosted or
proxied OpenAI-compatible endpoints. Only `src/researchos/gateway/model.py`
imports a provider SDK; agents and skills receive a plain
`(prompt, system="") -> str` callable.

```python
from researchos.gateway import create_model_gateway

gateway = create_model_gateway()          # None when disabled
if gateway is not None:
    text = gateway.complete("Summarize this abstract...", system="Be terse.")
    data = gateway.complete_json("Return {\"claims\": [...]}")
```

Every call records prompt/completion/total tokens and latency (estimating at
4 characters per token when a provider omits usage). Inspect the running
process totals at `GET /api/model/usage`; `gateway.usage()` and
`gateway.usage_by_model()` expose the same counters in-process.

Failures are not hidden: the gateway raises `ModelCallError` after its bounded
retries, and the synthesizer reports `success=false` with an `llm_failure`
alert instead of returning a 200 that looks successful. `RESEARCHOS_MAX_RETRIES`
is capped at 10, and `temperature` overrides are validated against `0..2`.
The test suite clears model variables and ignores the project `.env`, so local
provider settings never leak into it.

### Evaluation

```bash
researchos-eval
# reproducible JSON report:
python -m researchos.eval --json --out docs/eval/2026-10-26-s5.json
```

The committed [S5 report](docs/eval/2026-10-26-s5.json) records all three
systems on a deterministic synthetic suite of 5 papers and 10 questions
(`k=5`): direct CtxFlow graph queries, single-agent-shaped flat retrieval, and
a four-stage-pipeline-shaped flat baseline. The graph evaluator does **not**
run the ResearchOS agents. At the recorded run, answer accuracy was 0.80 for
the graph and 0.50 for each flat baseline; provenance accuracy was 0.80 and
0.00 respectively. These small-suite results are descriptive, not
statistically significant.

Important limitations: answer/provenance scoring uses normalized substring
matching; flat retrieval uses a deterministic hashed lexical embedder, not
semantic embeddings; supersession links are injected from dataset annotations;
and the benchmark does not test automatic contradiction detection. Context
token counts use deterministic `SimpleTokenizer` (`simple-v1`), not provider
tokenization or billed usage. The production synthesis-prompt hash in the
report is reference metadata only (`used_by_benchmark: false`); the benchmark
does not call a provider or use that prompt. The multi-agent-shaped baseline
over-fetches `2k` candidates and keeps at most `k` context items.

### ResearchOS tests

```bash
pytest tests/test_agents.py tests/test_skills.py tests/test_api.py \
       tests/test_workspace_api.py tests/test_eval_harness.py \
       tests/test_model_gateway.py
```

For the full suite, run `python -m pytest -q`.

For a focused workspace/API run, use
`python -m pytest -q tests/test_workspace_api.py tests/test_api.py`.
