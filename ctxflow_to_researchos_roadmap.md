# CtxFlow → ResearchOS: Development Roadmap

## Current State vs. Required State

### What exists today (CtxFlow v0.1)

| Module | File | Status |
|---|---|---|
| Data models | [`models.py`]| ✅ Node, Edge, Config, QueryResult |
| Graph engine | [`graph.py`] | ✅ NetworkX DiGraph, tag index, BFS, Jaccard |
| Governance | [`governance.py`]| ✅ Degree cap + score normalization |
| Query engine | [`query.py`]| ✅ α·tag + β·recency + γ·proximity scoring |
| Pruning | [`pruning.py`] | ✅ Drop + Summarize (RAPTOR-style compaction) |
| Extractors | [`extractors.py`]| ✅ Abstract interface + rule-based default |
| Serialization | [`serialization.py`] | ✅ JSON + MessagePack |
| Facade | [`__init__.py`] | ✅ `ingest`, `query`, `prune`, `export/import_` |
| Tests | [`tests/`] | ✅ 8 test files covering all modules |

# CtxFlow — Implementation Plan v2 (Revised and Expanded)

**Project:** CtxFlow
**Team:** Christo (Memory) · Abinav (Context) · Harikesh (Trust) · Adhityan (Serving / Optimization)
**One-line description:** A model-agnostic, resource-aware context management layer that selects, organizes, and compiles long-running agent memory into compact LLM context under relevance, graph, provenance, token, redundancy, and serving constraints.

> **How to read this document.** Sections 0–4 are shared by everyone. Section 5 contains one detailed plan per member. Sections 6–10 cover integration, experiments, timeline, risks, and cut lines. Appendices hold formulas, schemas, and checklists.
> **Timeline assumption:** 24 weeks. If your calendar is shorter or longer, scale the week numbers proportionally. The *order* and the *must-have-by-60%-of-the-calendar* rule matter more than the exact weeks.

---

## 0. What Changed From v1

| # | Issue in v1 | Fix in v2 | Where |
|---|-------------|-----------|-------|
| 1 | Cache-aware selection conflicted with relevance/causal ordering (ordering reshuffles the prefix per query) and the selector ran before the compiler, so it could not know the final order | **Tiered, prefix-stable context layout.** Positional/ordering experiments happen inside the query-specific tier only. Cache cost is a **plan-level** quantity (tokens past the first divergence), not an additive per-memory cost | §2.3, §5.4 |
| 2 | "Estimate cache-hit probability" was vague; hosted APIs hide cache state | Self-hosted engine (vLLM) plus a **shadow prefix tracker** that computes the expected cached prefix directly and is validated against engine-reported numbers. A simulated adapter is provided for development without a GPU | §5.4 |
| 3 | Benchmark was owned by "All" and started late | One named owner, starts in week 1, ships a **gold graph, gold provenance, and gold stale-set** with every scenario, runs in *oracle-graph* and *extracted-graph* modes, plus adapters for external benchmarks | §4 |
| 4 | Phases were sequential, so the last member waited for the first three | **Contract freeze in weeks 1–2, stubs, and a walking skeleton by week 6.** Everyone builds in parallel | §6 |
| 5 | Duplicated ownership (token budget in two places, versioning/supersession split across two people) | Single owner per concept; explicit boundary table | §3.7 |
| 6 | Greedy selector picked by raw utility and ignored real rendered cost | **Density greedy** on *rendered* token cost, best-singleton fallback, dependency **bundles** (closure) | §5.4 |
| 7 | Token counts were a single precomputed number | Per-tokenizer counts **and** rendered-cost accounting (headers, relation sentences, template overhead) with a hard post-compile check | §5.2 |
| 8 | Trust formula double-counted freshness; validity ignored query intent | Provenance score excludes freshness; validity handling depends on **query intent** (a "why did we change?" query *needs* superseded memories) | §5.3 |
| 9 | Experiment matrix was combinatorial | Fixed default configuration + **one-factor-at-a-time ablations**, budget sweeps, dev/test split, clustered bootstrap CIs | §7 |
| 10 | Formulas were corrupted by a Markdown conversion | All formulas rewritten as plain text in code blocks | Appendix A |
| 11 | Leftover reference ("the current CtxFlow design already supports…") | Baseline scorer is now defined in this document | §5.4 |

---

## 1. Scope, Assumptions, and Success Criteria

### 1.1 Assumptions
- Python 3.11+, FastAPI, PostgreSQL with pgvector, NetworkX/SciPy, pytest.
- A local embedding model (e.g., a small sentence-embedding model) so experiments are reproducible and free of API drift.
- A **self-hosted generator** (a 7–8B-class instruct model served by vLLM) for the serving experiments. If GPU access is not available, see the fallback ladder in §5.4.
- Benchmark scenarios contain hundreds of memories each. A separate synthetic **scale test** (up to ~100k nodes) is used only for latency measurements.

### 1.2 Non-goals
CtxFlow does not train or fine-tune LLMs, does not modify KV tensors, is not a general agent framework, and does not claim to extend the model's native context window.

### 1.3 Success criteria (what the final report must be able to *show*)
Negative or null results are acceptable **if measured honestly**; these are questions the project must answer, not outcomes it must achieve.

| ID | Question the final evaluation must answer |
|----|-------------------------------------------|
| S1 | At **equal token budget**, does CtxFlow selection beat vector top-k on evidence recall and answer accuracy? |
| S2 | How many fewer prompt tokens does CtxFlow need to match full-history (or large-budget) accuracy? |
| S3 | Does provenance + correction propagation reduce stale-information in context and in answers, and at what unnecessary-invalidation cost? |
| S4 | Does the prefix-stable layout raise cached-token fraction and lower TTFT in multi-turn replay, and what does it cost in accuracy? |
| S5 | Does the total CtxFlow overhead (retrieval + graph + selection + compilation) pay for itself in model-side work? |
| S6 | How much of the result depends on graph quality (oracle graph vs extracted graph)? |

---

## 2. Architecture

### 2.1 End-to-end pipeline

```text
User query
   │
   ▼
QueryAnalyzer ───────────────► intent: fact_lookup | current_state | history_why |
   │                                   multi_hop | preference | procedural | general
   ▼
Retriever (dense + keyword, fused)  ──► seed memories
   │
   ▼
Bounded graph expansion (BFS, depth/fan-out/node caps)  ──► candidate subgraph
   │
   ▼
Scorer  (semantic, graph/PPR, entity/tag, temporal(intent), importance, trust(intent))
   │
   ▼
Layout-aware Selector ◄──── BudgetPlanner (token budget)
   │        ▲
   │        └──── CacheAdapter / PrefixTracker (cache state)
   ▼
Materializer (IDs → content, current versions, validity annotations)
   │
   ▼
ContextCompiler (dedupe → group → order → render → trim → hard budget check)
   │
   ▼
LLMAdapter ──► response ──► AuditLog
```

### 2.2 Responsibility boundaries (unchanged in spirit from v1)

| Component | Question it answers |
|-----------|--------------------|
| Retriever | Where might useful information exist? (candidate generation) |
| Scorer | How useful is each candidate for *this* query and intent? |
| Selector | Which candidates are worth spending the context budget on? (optimization) |
| Materializer | What is the actual content of the selected memories (current versions, validity labels)? |
| Compiler | How should the selected memories be arranged and rendered for the LLM? |
| LLM | What should the agent say or do given this context? |

### 2.3 Tiered, prefix-stable context layout (the key v2 design change)

Prefix caching in engines such as vLLM reuses KV state only for the **longest common prefix** of two prompts. Anything that changes early in the prompt invalidates everything after it. So the prompt is split into tiers ordered from most stable to least stable:

```text
┌─────────────────────────────────────────────────────────────┐
│ Tier 0  System prompt + tool definitions        static       │  ← cached across all requests
├─────────────────────────────────────────────────────────────┤
│ Tier 1  Pinned project context                  changes rarely│  ← canonical order, hysteresis
│         (stable semantic memories, key decisions)            │
├─────────────────────────────────────────────────────────────┤
│ Tier 2  Session context                         changes slowly│  ← per session, append-mostly
│         (current task, plan, recent decisions)               │
├─────────────────────────────────────────────────────────────┤
│ Tier 3  Query-specific memories                 per request   │  ← ordered by Abinav's strategies
├─────────────────────────────────────────────────────────────┤
│ Tier 4  User query + dynamic fields             per request   │  ← always last
│         (timestamps, request IDs, etc.)                      │
└─────────────────────────────────────────────────────────────┘
```

**The prefix contract** (agreed by Abinav and Adhityan, enforced by tests):

1. Tiers 0–2 are rendered **deterministically**: canonical memory order (by memory ID or creation time, never by per-query score), fixed template, identical bytes for identical inputs.
2. **No dynamic strings** (timestamps, request IDs, random IDs, "current date") appear before Tier 4.
3. Tier 1 changes only through the **StableBlockManager** (hysteresis rule in §5.4), *except* that correctness overrides caching: if a memory in Tier 1/2 becomes STALE/SUPERSEDED/CONTRADICTED, the tier is refreshed immediately.
4. Positional-bias and ordering experiments (Abinav) operate on Tier 3 only, *and* separately on a flat no-tier layout so the positional-bias finding is a statement about the LLM rather than about caching.
5. The joint study "ordering gain vs prefix loss" (Abinav × Adhityan) reports both effects in one table.

---

## 3. Shared Infrastructure and Contracts (Weeks 1–2, frozen by end of week 2)

### 3.1 Core data models (Pydantic)

```python
class MemoryNode:
    id: str                       # stable, e.g. "m_000123"
    text: str                     # current version's text (denormalized for speed)
    embedding_model: str          # id of model that produced `embedding`
    embedding: list[float]
    memory_type: MemoryType       # conversation|fact|decision|observation|tool_result|
                                  # document|task|correction|summary|user_preference
    tier: MemoryTier              # working | episodic | semantic
    created_at: datetime
    session_id: str | None
    source: str
    importance: float             # [0,1]
    access_count: int
    token_counts: dict[str, int]  # tokenizer_id -> raw token count of `text`
    current_version: int
    validity: ValidityState       # VALID|STALE|CONTRADICTED|REQUIRES_REVIEW|SUPERSEDED
    archived: bool
    entities: list[str]

class MemoryVersion:
    memory_id: str
    version: int
    text: str
    embedding: list[float]
    created_at: datetime
    reason: str                   # why this version exists
    supersedes_version: int | None
    actor: str                    # user | agent | system | propagation

class Edge:
    src: str
    dst: str
    relation: Relation            # see 3.2
    weight: float                 # tunable heuristic, NOT a universal truth
    confidence: float             # [0,1]; 1.0 for gold/explicit
    created_by: str               # rule | llm | gold | user
    created_at: datetime

class Provenance:
    memory_id: str
    source_type: SourceType       # user_message|assistant_message|tool_output|document|derived|external
    source_id: str | None
    author: str | None
    tool: str | None
    extraction_confidence: float  # [0,1]
    parent_memories: list[str]
    created_at: datetime

class QueryIntent(Enum):
    FACT_LOOKUP; CURRENT_STATE; HISTORY_WHY; MULTI_HOP; PREFERENCE; PROCEDURAL; GENERAL

class Candidate:
    memory_id: str
    scores: dict[str, float]      # named, normalized signals
    rendered_tokens: int          # cost as it will actually appear in the prompt
    required_parents: list[str]   # hard dependencies for bundle selection

class LayoutPlan:
    tier1_ids: list[str]; tier2_ids: list[str]; tier3_ids: list[str]
    token_estimate: int; layout_hash: str

class CompiledContext:
    blocks: list[Block]           # Block(tier, text, memory_ids, token_count)
    total_tokens: int
    layout_hash: str
```

### 3.2 Relation vocabulary and **direction convention**

An edge `(src, dst, relation)` is read as **"src `<relation>` dst"**.

| Relation | Reading | In dependency set (`DEP_TYPES`)? |
|----------|---------|----------------------------------|
| `derived_from` | src was derived from dst | yes |
| `depends_on` | src depends on dst | yes |
| `based_on` | src is based on dst | yes |
| `summary_of` | src summarizes dst | yes |
| `caused_by` | src was caused by dst | yes (weaker) |
| `supersedes` | src replaces dst | no (handled by versioning/validity) |
| `contradicts` | src conflicts with dst (symmetric) | no (handled by contradiction logic) |
| `duplicate_of` | src is a near-duplicate of dst | no |
| `follows` | src comes after dst in the same thread | no |
| `related_to` | weak association | no |

**Dependents of X** = nodes `n` with an edge `(n → X)` whose relation is in `DEP_TYPES`. Correction propagation walks **dependents** (reverse direction). This convention is the most likely source of integration bugs, so it is covered by a dedicated unit-test fixture (Appendix C).

### 3.3 Storage (PostgreSQL + pgvector; NetworkX as an in-memory graph view)

```sql
memories(id PK, text, memory_type, tier, created_at, session_id, source, importance,
         access_count, current_version, validity, archived, entities TEXT[],
         embedding VECTOR(d), embedding_model, token_counts JSONB)
memory_versions(memory_id, version, text, embedding VECTOR(d), created_at, reason,
                supersedes_version, actor, PRIMARY KEY (memory_id, version))
graph_edges(src, dst, relation, weight, confidence, created_by, created_at,
            PRIMARY KEY (src, dst, relation))
provenance(memory_id PK, source_type, source_id, author, tool,
           extraction_confidence, parent_memories TEXT[], created_at)
validity_log(id PK, memory_id, old_state, new_state, reason, caused_by_memory,
             propagation_run_id, created_at)
audit_records(request_id PK, ts, session_id, query, intent, config_hash, candidates JSONB,
              selected JSONB, compiled_context_hash, compiled_context TEXT,
              model, response TEXT, timings JSONB)
experiment_runs(run_id PK, config_hash, git_sha, seed, started_at, results JSONB)
```

- The in-memory NetworkX `MultiDiGraph` is **rebuilt from `graph_edges` at startup** and updated incrementally. The database is the source of truth.
- Use one vector index (pgvector HNSW) over **current-version** embeddings only; old-version embeddings are retained but excluded unless `include_history=True`.
- Use Postgres full-text search for the keyword half of hybrid retrieval.

### 3.4 Interfaces (Python `Protocol`s; semver; changes via PR with two approvals)

```python
class MemoryStore:
    async def add(self, memory) -> str
    async def get(self, memory_id, version=None, as_of=None)
    async def create_version(self, memory_id, new_text, reason, supersedes_version, actor) -> int
    async def search(self, query_emb, query_text, k, *, types=None, include_archived=False,
                     include_history=False, as_of=None) -> list[ScoredId]
    async def neighbors(self, memory_id, *, depth, relations=None, direction="both",
                        max_nodes=200, fanout_cap=20) -> Subgraph
    async def get_version_history(self, memory_id) -> list[MemoryVersion]

class ProvenanceStore:
    async def record(self, provenance)
    async def lineage(self, memory_id, direction="up"|"down", depth=None) -> Subgraph
    async def apply_correction(self, memory_id, new_text, reason) -> PropagationReport
    async def set_validity(self, memory_id, state, reason, caused_by=None)
    def trust(self, memory_id, intent) -> TrustScore       # provenance_score x validity gate
    async def explain(self, request_id) -> AuditExplanation

class QueryAnalyzer:
    def analyze(self, query, session_ctx=None) -> QueryAnalysis   # intent, entities, confidence

class Retriever:
    async def candidates(self, analysis, session_ctx) -> CandidateSet  # seeds + expanded subgraph

class Scorer:
    def score(self, candidate_set, analysis) -> list[Candidate]

class Selector:
    def select(self, candidates, budget, layout_policy, cache_state, analysis) -> SelectionResult

class BudgetPlanner:
    def plan(self, model_profile, system_tokens, tool_tokens, query_tokens, output_reserve) -> int

class TokenizerAdapter:
    def count(self, text: str) -> int
    def count_prompt(self, rendered_prompt: str) -> int   # includes chat-template overhead

class ContextCompiler:
    def compile(self, selection, analysis, budget, layout_plan) -> CompiledContext

class CacheAdapter:
    def expected_cached_tokens(self, prompt_tokens: list[int]) -> int
    def last_request_cached_tokens(self) -> int | None
    def complete(self, prompt: str, **params) -> LLMResult      # includes TTFT, timings
    def metrics(self) -> dict

class LLMAdapter:
    def complete(self, prompt, **params) -> LLMResult
```

### 3.5 Repository layout and engineering rules

```text
ctxflow/
  core/            models.py, config.py, timing.py, interfaces.py
  memory/          store.py, ingest.py, extraction.py, graph.py, consolidation.py, retention.py   (Christo)
  context/         budget.py, tokenizers.py, intent.py, compiler.py, render.py, ordering.py,
                   compression.py                                                                   (Abinav)
  trust/           provenance.py, lineage.py, validity.py, propagation.py, contradiction.py,
                   audit.py, trust_scoring.py                                                       (Harikesh)
  selection/       retriever.py, expansion.py, scoring.py, ppr.py, mmr.py, selectors.py,
                   pcst.py, stable_block.py                                                         (Adhityan)
  serving/         vllm_adapter.py, sim_adapter.py, prefix_tracker.py                              (Adhityan)
  eval/            scenarios/, harness.py, metrics.py, judge.py, report.py                         (Abinav)
  testing/         mocks.py, fixtures/                                                              (all)
  api/             main.py (FastAPI)
configs/           default.yaml, ablations/*.yaml, models/*.yaml
experiments/       one folder per experiment: config + results + notebook
tests/
```

Rules:
- **Every run is reproducible:** a run record stores config hash, git SHA, seeds, model IDs, and per-stage timings.
- **Per-stage timing** via a shared `timed("stage")` context manager; nothing ships without it.
- **LLM response cache** keyed by `(model, prompt hash, params)` so reruns and CI are free and deterministic.
- **LLM extraction cache** keyed by event hash so ingestion experiments do not re-pay LLM costs.
- CI runs unit tests plus a 5-scenario smoke benchmark using mocked/cached LLM responses.
- `main` is always runnable. Feature branches, PR review by at least one *other* member.

### 3.6 FastAPI surface (minimal)

```text
POST /events                  ingest an interaction event          (Christo)
GET  /memories/{id}           memory + versions + provenance       (Christo/Harikesh)
POST /query                   full pipeline: query → context → LLM (all)
POST /corrections             apply a correction + propagate       (Harikesh)
GET  /audit/{request_id}      explain a past request               (Harikesh)
GET  /debug/context/{req_id}  compiled context + tier layout       (Abinav)
```

### 3.7 Ownership boundaries (one owner per concept)

| Concept | Owner | Consumers | Boundary rule |
|---------|-------|-----------|---------------|
| MemoryNode storage, versions table, `create_version`, `get_as_of` | Christo | all | Versioning is the **storage mechanism**: append-only, never overwrite |
| Decision *that* something is superseded / stale / contradicted; validity states; lineage edges' semantics | Harikesh | Christo, Adhityan, Abinav | Harikesh decides; Christo's `create_version` executes. `apply_correction` calls `create_version` |
| Graph construction (edge extraction, `follows`, `duplicate_of`, `related_to`) | Christo | Adhityan | Lineage edges (`DEP_TYPES`) are *proposed* by Christo's extractor, *validated and consumed* by Harikesh |
| Query intent classification | Abinav | Adhityan, Harikesh, Abinav's compiler | Single classifier; others import it |
| Tokenizers, `BudgetPlanner`, rendered-token accounting, hard budget check | Abinav | Adhityan | Adhityan never computes budgets; he receives `B_memory` |
| Scoring, MMR, PPR, selectors, PCST, stable-block manager | Adhityan | — | Selectors consume `trust()` and `importance`; they do not compute them |
| Compiler, renderers, ordering, compression | Abinav | Adhityan | Tier 0–2 rendering must obey the prefix contract (§2.3) |
| Cache adapter, prefix tracker, serving metrics | Adhityan | Abinav | — |
| Evaluation harness, metric code, benchmark schema | Abinav | all | Scenario *families* are authored by whoever needs them (§4.2) |
| Audit log schema | Harikesh | all | Everyone writes via `AuditLog.record(...)` |

---

## 4. Benchmark and Evaluation Infrastructure

**Owner (suggested): Abinav.** Rationale: his positional experiments need the harness first, and his research scope is the lightest, so this balances load. Swap owners if the team prefers, but there must be exactly one named owner. Starts week 1.

### 4.1 Scenario format
Each scenario is a JSON document containing everything needed to run the pipeline *and* score it (full example in Appendix B):

```text
events[]                 time-ordered interaction events (messages, tool calls, corrections)
queries[]                1–5 queries, each with intent label, gold answer keys, gold evidence IDs
gold_graph               ground-truth edges between memories (typed)
gold_provenance          ground-truth source/parent information
gold_stale_sets          for each correction: which memories SHOULD become stale/superseded
distractors              near-duplicates and off-topic memories deliberately included
metadata                 family, difficulty, length, seed
```

### 4.2 Scenario families (≈ 15 scenarios each → ≈ 120 total at v2)

| Family | Tests | Primary author |
|--------|-------|----------------|
| F1 Fact update chain | Current-state vs history ("what do we use now / why did it change?") | Christo |
| F2 Multi-hop dependency | decision → experiment → dataset; evidence not similar to the query | Adhityan |
| F3 Correction propagation | A corrected → B, C derived from A become stale (1–4 hops) | Harikesh |
| F4 Silent contradiction | Conflict without explicit correction language | Harikesh |
| F5 Redundancy-heavy | Many near-duplicate memories; tight budget | Adhityan |
| F6 Long-horizon history | Evidence scattered across 100+ events | Abinav |
| F7 Preference stability | Stable preferences + occasional overrides | Christo |
| F8 Tool-result provenance | Results from tools of varying reliability | Harikesh |

Generation procedure: hand-write the scenario *skeleton* (facts, decisions, corrections, gold graph) → expand with templates → LLM-paraphrase surface text for realism → **human-verify a ≥ 20 % sample** → freeze. Every scenario has a seed. Document the generator so the dataset is reproducible.

### 4.3 Splits and rules
- **Dev** (30 %): for tuning weights, thresholds, prompts. **Test** (70 %): locked at **week 14**; touched only for final experiments.
- Report **oracle-graph mode** (gold edges/provenance) and **extracted-graph mode** (pipeline-built). The gap measures how much results depend on extraction quality (answers S6).
- Include **external benchmarks** as adapters (check current versions and licenses; LoCoMo and LongMemEval are good starting points) for at least a sanity-level comparison, and compare against **at least one existing memory system** (e.g., Mem0 or Letta) if setup effort is reasonable. Treat these as "nice for credibility", not blocking.

### 4.4 Scoring
- **Answer accuracy:** programmatic **key-fact match** (normalized string/regex over gold answer keys) as the primary metric — cheap, deterministic.
- **LLM judge:** only on a subset or for open-ended answers; fixed rubric, temperature 0, **manual audit of ≥ 10 %** of judgments to estimate judge error.
- **Stale-answer detection:** answer asserts a value listed in the scenario's `stale_strings`.
- **Faithfulness:** compiled context labels memories `[m12]`; answers should cite IDs; check cited IDs ⊂ context and that cited memory supports the claim (judge on subset).

### 4.5 Metric definitions

```text
Evidence Recall@B     = |selected ∩ gold_evidence| / |gold_evidence|        (at token budget B)
Evidence Precision@B  = |selected ∩ gold_evidence| / |selected|
Stale-in-context rate = |selected ∩ gold_stale| / |selected|
Redundancy ratio      = fraction of selected pairs with cosine > 0.9   (or mean max-pairwise cosine)
Compression ratio     = tokens(raw selected) / tokens(compiled)
Propagation precision = |predicted_stale ∩ gold_stale| / |predicted_stale|
Propagation recall    = |predicted_stale ∩ gold_stale| / |gold_stale|
Unnecessary invalidation = |predicted_stale \ gold_stale| / |valid memories|
Cached-token fraction = cached_prompt_tokens / total_prompt_tokens
TTFT, total latency   = measured with streaming; medians + p95 over repeated runs
Overhead              = Σ(retrieve, expand, score, select, compile) stage times
```

---

## 5. Member Plans

---

### 5.1 Christo — Memory Architecture for LLM Agents

**Research question:** How should long-term agent memory be represented, consolidated, versioned, and retrieved?
**Core contribution:** Structured hybrid memory + memory graph + append-only versioning + consolidation.
**You provide to others:** the `MemoryStore` and graph. Without it, nothing downstream has data to optimize, so your **week-6 vertical slice is the project's critical path**.

#### 5.1.1 Memory model and layers
Implement the three layers as *views over one table* (field `tier`), not three databases:

| Layer | What it is | How it is produced |
|-------|------------|--------------------|
| Working | Recent items for the current task (current request, plan, latest tool results) | Query-time window per session (not a separate store) |
| Episodic | Specific past events (a debugging session, a decision, a failed approach) | Direct output of ingestion |
| Semantic | Generalized facts distilled from repeated or related episodes | **Consolidation job** (5.1.5) |

#### 5.1.2 Ingestion pipeline (async, idempotent)

```text
Event {event_id, session_id, ts, role, content, tool_name?, metadata}
  → idempotency check (hash of event_id)
  → extraction (atomic memories)
  → classification (memory_type)
  → importance estimation
  → embedding
  → dedup check
  → persist (memory + version 1 + provenance record)
  → edge proposal (rule-based now, LLM-based async)
```

- **Extraction.** Stage 1 (MVP): one memory per message, one per tool result (with a truncation policy and a pointer to the full output). Stage 2: an LLM extractor emits JSON `[{text, type, entities, claims, refs}]`, validated with Pydantic, retried on failure, **falling back to the raw message** if validation fails. Cache every extraction by event hash.
- **Classification.** Rules first (tool output → `tool_result`, "remember that…" → `user_preference`/`fact`), small LLM prompt second. Hand-label ~200 memories to measure accuracy and keep that label set in the benchmark.
- **Dedup.** Before insert, look up the top-5 ANN neighbors. If cosine > `τ_dup` (start 0.95, tune on dev) and same type, **do not delete anything**: add a `duplicate_of` edge and bump access/importance counters on the canonical memory.
- **Embedding.** Store `embedding_model` and dimension with every vector so re-embedding is possible.
- **Token counts.** Computed lazily per registered tokenizer ID and cached in `token_counts`.

#### 5.1.3 Importance scoring

```text
importance = w_task·task_relevance + w_freq·norm(access_count) + w_user·user_explicitness
           + w_dep·norm(dependent_count) + w_novelty·novelty
```
- Each term normalized to [0,1]; weights in config.
- **Known risk:** `access_count` creates a rich-get-richer loop (selected → accessed → more important → selected). Mitigations: count access only for memories *selected*, apply a per-window cap, and ablate the term.
- `dependent_count` is supplied by Harikesh's lineage graph (cheap in-degree over `DEP_TYPES`).

#### 5.1.4 Graph construction (typed, with confidence)
- **Stage 1 (deterministic, week 3–6):** `follows` (same-thread order), `derived_from` for tool results → the call that produced them, explicit references ("because of experiment 3"), shared-entity `related_to` when cosine > τ_rel.
- **Stage 2 (async LLM proposer, week 7–10):** for each new memory, take the top-k neighbors, ask for `{relation, confidence}` from the vocabulary in §3.2; store with `created_by="llm"`; keep only edges above `τ_edge`.
- **Quality measurement (mandatory):** edge precision/recall against the benchmark's **gold graph**, per relation type. This also produces the *extracted-graph mode* numbers for §4.3.
- **Hub control:** `neighbors()` enforces `fanout_cap` and `max_nodes`, keeping the highest-weight edges, so a single hub memory cannot explode the candidate set.

#### 5.1.5 Consolidation (episodic → semantic)
- **Trigger:** every N new memories sharing an entity cluster, or a periodic background job.
- **Method:** cluster by entity + embedding; an LLM writes one semantic memory per cluster; store `summary_of` edges to every source (this gives Harikesh real lineage to propagate through).
- **Rule:** a semantic memory is **never** the only copy of its sources, and when any source becomes STALE/SUPERSEDED the summary is flagged for regeneration (coordinate with Harikesh).

#### 5.1.6 Versioning
- Append-only `memory_versions`; `memories.current_version` points to the live one.
- `create_version(memory_id, new_text, reason, supersedes_version, actor)` re-embeds, stores the new vector, and marks old-version vectors as non-current for indexing.
- `get(memory_id, as_of=ts)` answers *"what did we believe at time T?"*; `get_version_history` answers *"why did the belief change?"*.
- Harikesh decides **when** a correction applies; you provide the mechanism.

#### 5.1.7 Retention / forgetting
```text
retention(v) = importance + access + dependency_score + correction_value − age_decay
```
Actions in order of severity: **deprioritize → compress (replace with summary, keep link) → archive (exclude from default retrieval)**. Never hard-delete. **Invariants:** never archive a memory that has active dependents or whose validity is CONTRADICTED/REQUIRES_REVIEW; log every action. Evaluate with a forgetting simulation: memory size vs accuracy as retention aggressiveness grows.

#### 5.1.8 Retrieval API
- `search(...)` is **hybrid**: dense vector search + Postgres full-text, fused with reciprocal-rank fusion. Keyword matching rescues exact names/IDs that embeddings blur. Ablate dense-only vs hybrid.
- Filters: types, validity, `as_of`, `include_archived`, `include_history`.
- `neighbors(...)`: bounded BFS with relation filter, direction, depth (default ≤ 2), `max_nodes` (default 200), `fanout_cap` (default 20).

#### 5.1.9 Experiments (retrieval-only metrics need no LLM; end-to-end metrics use the shared harness)

| Arm | Description |
|-----|-------------|
| M0 | Flat full history (upper bound on recall, worst on tokens) |
| M1 | Sliding window |
| M2 | Dense vector memory |
| M3 | Hybrid dense + keyword |
| M4 | Vector + graph expansion (extracted graph) |
| M5 | M4 + versioning/validity handling (with Harikesh) |
| M4-oracle | M4 with gold graph (measures extraction loss) |

Metrics: Evidence Recall@B, precision, accuracy, memory size, retrieval latency, irrelevant-memory count, contradiction rate, tokens; plus **ingestion quality** (classification accuracy, edge P/R, dedup precision) and ingestion throughput.

#### 5.1.10 Weekly plan

| Weeks | Deliverable |
|-------|-------------|
| 1–2 | Contract freeze (with team); schema + migrations; `MemoryStore` interface + in-memory mock; 3 hand-made fixtures |
| 3–6 | **Vertical slice:** Postgres/pgvector store, rule-based ingestion, embeddings, dense search, graph load + bounded BFS, token counts. Demo: ingest scenario → search → neighbors |
| 7–10 | LLM extractor (cached), classifier eval, dedup, importance v1, LLM edge proposer, edge P/R report |
| 11–13 | Versioning API + `as_of`; consolidation job with `summary_of` lineage; hybrid retrieval |
| 14–18 | Retention/forgetting + simulation; M0–M5 experiments on dev; tuning of `τ` thresholds on dev only |
| 19–22 | Final test-split runs, oracle vs extracted comparison, scale test (latency vs memory count) |
| 23–24 | Chapter/seminar writing, demo support |

#### 5.1.11 Acceptance criteria
- Ingest 10k synthetic events without errors; re-ingesting the same events creates no duplicates.
- `neighbors()` never exceeds `max_nodes` regardless of graph shape (property test).
- Version history is complete and `as_of` returns the correct text for every correction in the fixtures.
- Edge extractor reports per-relation precision/recall on dev.

#### 5.1.12 Risks and fallbacks
| Risk | Fallback |
|------|----------|
| LLM extraction is slow/expensive | Cache by event hash; run benchmark ingestion once, reuse |
| LLM edge quality is poor | Keep rule-based edges + gold-graph mode; report extraction loss as a finding |
| Consolidation creates hallucinated facts | Keep `summary_of` links, annotate summaries as `derived`, lower their reliability prior (Harikesh) |

---

### 5.2 Abinav — Context Window Utilization, Positional Bias, and Context Compilation

**Research question:** How does context length and positional arrangement affect the usefulness of retrieved agent memory, and how should structured memory be rendered for an LLM?
**Core contribution:** Budget-aware, tier-aware context compilation; graph-to-text rendering; positional-bias-aware ordering; plus ownership of the evaluation harness.
**Why the harness is yours:** your positional experiments are the first consumers of it, and everyone else's results depend on it. Treat it as a first-class deliverable.

#### 5.2.1 TokenizerAdapter and BudgetPlanner (single owner of all budget logic)

```text
B_memory = B_context_limit − B_system − B_tools − B_query − B_output_reserve − B_safety
```
- `B_safety` (2–5 %) absorbs tokenizer drift and chat-template overhead.
- **Model profiles** in YAML: context limit, tokenizer ID, output reserve default, template overhead.
- **Per-tokenizer counts**: never trust a count produced with another model's tokenizer.
- **Rendered-cost accounting:** a memory's cost in the prompt is `tokens(render(memory))`, which includes its ID tag, metadata line, and relation sentences. Provide `rendered_token_cost(memory, render_style)` to Adhityan's selector.
- **Hard check after compilation** with the real tokenizer on the fully templated prompt. If over budget: trim the lowest-utility item and re-render until it fits. The budget must **never** be exceeded in any test.

#### 5.2.2 QueryAnalyzer (intent)
Classes: `fact_lookup`, `current_state`, `history_why`, `multi_hop`, `preference`, `procedural`, `general`.
- Start with rules + keyword cues ("why", "originally", "now", "currently", "how did we get") and a zero-shot LLM fallback; hand-label ~150 queries for evaluation and report accuracy/confusion matrix.
- Low-confidence → `general` (neutral behavior). Everyone consumes this one classifier; it controls ordering (you), validity handling (Harikesh), and temporal weighting (Adhityan).

#### 5.2.3 ContextCompiler stages

```text
SelectionResult → dedupe → group → order → render → trim → hard budget check → CompiledContext
```
1. **Dedupe:** exact + near-duplicate safeguard (the selector already removes redundancy; this is a safety net).
2. **Group:** by connected components of the *selected* subgraph, then by session/thread, so related memories sit together.
3. **Order:** strategy per tier (5.2.4).
4. **Render:** one of the styles below.
5. **Trim / check:** enforce budget exactly (5.2.1).

**Render styles** (an experimental factor):

| Style | Description |
|-------|-------------|
| R0 | Raw concatenation with memory IDs |
| R1 | Flat list with metadata (time, source, validity) |
| R2 | **Grouped narrative:** graph relations converted to sentences ("Decision [m12] was derived from Experiment [m7] and depends on Requirement [m3]") |
| R3 | R2 + explicit status annotation ("[m4] — superseded on 2026-03-02 by [m12]") |

Relation → sentence templates are small, deterministic, and unit-tested. **Never dump raw graph structure into the prompt.** Always cite memories as `[mID]` so answers can reference them (enables faithfulness checks and Harikesh's audit trail).

#### 5.2.4 Layout and ordering (follows the prefix contract in §2.3)

| Tier | Ordering rule |
|------|---------------|
| 0–2 | Canonical and deterministic (by ID or creation time). **Not experimental** |
| 3 | Experimental: O1 chronological · O2 relevance-descending · O3 strongest-first · O4 strongest-last · O5 importance sandwich · O6 causal · O7 adaptive (intent-driven) |
| 4 | Query last |

**O6 (causal) algorithm:** topological sort over `derived_from/depends_on/caused_by` among selected memories (dependencies first), chronological tie-break; contract strongly-connected components so cycles do not break the sort.
**O7 (adaptive):** `history_why → O1 or O6`, `multi_hop → O6`, `fact_lookup/current_state → O3`, `general → O2`. Tune on dev.

#### 5.2.5 Positional-bias study (generic, cache-independent)
Controlled design:
- Fixed memory *set* (gold evidence + distractors), fixed total tokens, only **position of evidence** varies: start / 25 % / 50 % / 75 % / end.
- Context lengths: 1k, 2k, 4k, 8k tokens. Evidence count: 1 and 3 (multi-evidence).
- ≥ 50 queries per cell. **Same LLM, temperature 0.** At least **two models** (the local serving model plus one more) since the effect is model-specific.
- Statistics: paired comparisons across positions (McNemar for binary accuracy), bootstrap CIs.
- Deliverable: accuracy-by-position curves per model and length. Then repeat with real selected memories and the O1–O7 strategies.

Be honest in the write-up: positional bias is well documented already; your original contribution is the **interaction** with graph-structured, tiered, cache-aware context and with render style.

#### 5.2.6 Compression
- **MVP: extractive.** Score sentences within each memory by query similarity; keep top sentences up to a per-memory cap; always keep at least one sentence; never drop sentences containing dates, numbers, or negations without an ablation showing it is safe.
- **Optional abstractive:** an LLM summary of a *group* with source IDs, cached by group hash; ablate for accuracy and faithfulness.
- Hierarchical compression is a research extension (§10).
- Metrics: compression ratio, accuracy delta, faithfulness delta.

#### 5.2.7 Evaluation harness (deliverable with milestones)

| Component | Description |
|-----------|-------------|
| Scenario loader + validator | Enforces the schema in Appendix B; rejects malformed scenarios |
| Runner | Ingest → pipeline(config) → LLM → score; supports oracle/extracted-graph modes and budget sweeps |
| Config grid | YAML configs; one-factor-at-a-time ablation generator |
| Response cache | Keyed by (model, prompt hash, params) |
| Metric library | §4.5, unit-tested on hand-computed examples |
| Judge | Key-fact match + optional LLM judge with manual-audit sampling |
| Reporter | Tables/plots (accuracy vs budget, ablation tables, latency breakdown) with clustered bootstrap CIs |

#### 5.2.8 Experiments
- **E-A1** Positional bias (5.2.5).
- **E-A2** Ordering strategies O1–O7 × budget × render style, on Tier 3 and on flat layout.
- **E-A3** Render styles R0–R3 (does graph-to-text help multi-hop and history queries?).
- **E-A4** Compression on/off × budget.
- **E-A5** *(joint with Adhityan)* ordering gain vs prefix-cache loss (one table: accuracy, cached-token fraction, TTFT).

#### 5.2.9 Weekly plan

| Weeks | Deliverable |
|-------|-------------|
| 1–2 | Scenario schema; 3 hand-made fixtures; harness skeleton; model profiles; token-count tests |
| 3–6 | `TokenizerAdapter`, `BudgetPlanner`, simple compiler (R1 + relevance order), harness v0 running **top-k baseline end-to-end**; 20 scenarios |
| 7–10 | Rule-based intent classifier + eval; R2/R3 renderers; positional-bias study (E-A1); benchmark v1 (60 scenarios) |
| 11–14 | O1–O7; extractive compression; external-benchmark adapter; **benchmark v2 final (120 scenarios), test split locked at W14** |
| 15–18 | E-A2/E-A3/E-A4 on dev; joint E-A5 setup with Adhityan; judge audit |
| 19–22 | Final test runs; all report generation |
| 23–24 | Chapter/seminar writing, demo support |

#### 5.2.10 Acceptance criteria
- Budget is **never** exceeded across a randomized test of ≥ 1,000 compilations (property test), including worst-case long memories.
- Compiling the same input twice yields byte-identical Tier 0–2 text (determinism test).
- Intent classifier reports accuracy on the hand-labeled set.
- Harness reproduces an identical result from a cached run (same config hash ⇒ same numbers).

#### 5.2.11 Risks and fallbacks
| Risk | Fallback |
|------|----------|
| Positional effects are weak/absent for the chosen model | Report as a legitimate finding; test a second model and longer contexts; emphasize render-style results |
| Harness slips and blocks everyone | Week-6 harness v0 is a hard milestone; others can run with a minimal script until then |
| Judge unreliable | Rely on key-fact match; restrict LLM judge to audited subset |

---

### 5.3 Harikesh — Data Lineage, Correction Propagation, and Trust

**Research question:** How can lineage and corrections prevent stale or unsupported information from propagating through long-running agent memory?
**Core contribution:** Provenance capture + lineage graph + validity state machine + correction propagation + contradiction handling + trust-aware scoring + audit trail.

#### 5.3.1 Provenance capture
- Hook into Christo's ingestion: every new memory gets a `Provenance` record (`source_type`, `source_id`, `author`, `tool`, `extraction_confidence`, `parent_memories`).
- **`source_reliability` priors** per `source_type` live in config (e.g., explicit user statement > tool output > LLM-derived summary > unverified external). These are **tunable heuristics**, not facts; ablate them.
- **`extraction_confidence`:** LLM self-reported confidence is poorly calibrated. Prefer proxies: rule-extraction = 1.0, LLM extraction agreeing across two runs = high, disagreement = low. Check calibration on dev (reliability diagram) and report it.

#### 5.3.2 Lineage graph
- The lineage graph is the subgraph of typed edges in `DEP_TYPES` (§3.2).
- **Cycle handling:** detect cycles at insertion; contract strongly-connected components for propagation (treat the SCC as one unit) and log a warning.
- API: `lineage(id, direction="up"|"down", depth)`; `dependent_count(id)` is exported for Christo's importance score.

#### 5.3.3 Validity state machine

| From → To | Trigger | Reversible? |
|-----------|---------|-------------|
| VALID → SUPERSEDED | Explicit `supersedes` edge / new version created for the same claim | No (history preserved, status final) |
| VALID → STALE | An upstream source in its lineage changed, impact ≥ θ_high | Yes |
| VALID → REQUIRES_REVIEW | Upstream changed, θ_low ≤ impact < θ_high; or low-confidence contradiction | Yes |
| VALID → CONTRADICTED | High-confidence contradiction with a more trusted/newer memory | Yes |
| STALE/REQUIRES_REVIEW → VALID | Re-validation confirms the memory still holds (re-check or user confirmation) | — |
| STALE/REQUIRES_REVIEW → CONTRADICTED | Re-validation finds a conflict | Yes |

Every transition writes a row to `validity_log` with `reason`, `caused_by_memory`, and `propagation_run_id`. **Nothing is ever auto-deleted or auto-rewritten.**

#### 5.3.4 Correction propagation (detailed algorithm)

```text
Input: correction event (memory X gets a new version, or a `supersedes` edge is added)

1. Execute: call MemoryStore.create_version(X, ...)             # Christo's mechanism
2. Compute impact over DEPENDENTS of X (reverse DEP_TYPES edges):
     impact(X) = 1.0
     impact(child) = max over paths of  Π( edge.confidence × relation_strength[edge.relation] )
   - Breadth-first, depth limit D (default 3)
   - Diamonds: keep the max impact over all paths
   - Cycles: use SCC contraction; visited set prevents loops
   - Stop expanding a branch when impact < θ_low
3. Mark:  impact ≥ θ_high → STALE ;   θ_low ≤ impact < θ_high → REQUIRES_REVIEW
4. Optional re-evaluation (bounded, async, batched):
     for each marked memory m (highest impact first, budget = N calls):
         verdict = NLI/LLM check: "does m still hold given new X?"
         → VALID / STALE / CONTRADICTED, plus a one-line explanation
5. Summaries: any `summary_of` parent marked STALE → flag the summary for regeneration (Christo)
6. Return PropagationReport {corrected_id, affected:[{id, state, impact, path}], cost}
```

Implementation notes:
- Wrap steps 1–3 in **one DB transaction**; make the operation **idempotent** (re-applying the same correction produces no further changes).
- `relation_strength` (e.g., `derived_from` 1.0, `depends_on` 0.9, `based_on` 0.8, `caused_by` 0.6) and `θ_high/θ_low/D` are **config parameters tuned on dev**, not constants of nature.
- Conservative by default: *mark*, do not rewrite.

#### 5.3.5 Contradiction detection (cheap-first pipeline)

```text
new memory
  → candidate generation: ANN top-k (k≈10) restricted to same-entity / same-topic memories
  → filter: cosine > τ_c
  → stage 1: small NLI cross-encoder (entailment / neutral / contradiction)
  → stage 2: LLM judge only for the ambiguous band
  → output: `contradicts` edge with confidence
  → resolution policy (below)
```
**Resolution policy** — three different situations must not be conflated:

| Situation | Signal | Action |
|-----------|--------|--------|
| **Supersession** (time-ordered update) | Newer + correction language ("actually", "we switched", "no longer") | `supersedes` edge → old memory SUPERSEDED |
| **Contradiction** (conflicting claims coexist) | High-confidence conflict, no update language | `contradicts` edge; keep both; flag both; the lower-trust one gets `CONTRADICTED` or `REQUIRES_REVIEW` per config |
| **Different scope** (both true in different contexts) | Different entity/project/time scope | No action. This is the main false-positive source, so evaluate it explicitly |

Never run contradiction detection across the whole store; only over new memory × bounded candidates. Measure precision/recall against gold contradiction pairs (family F4).

#### 5.3.6 Trust-aware scoring (fixes the double-counting in v1)

```text
provenance_score(v) = source_reliability(v) × extraction_confidence(v)        # both in [0,1]
trust(v, intent)    = provenance_score(v) × validity_multiplier(state(v), intent)
```
- **Freshness is not in `trust`.** Temporal relevance is a separate scoring signal owned by Adhityan's scorer.
- `validity_multiplier` depends on **query intent** (initial values, tuned on dev):

| Validity state | current_state / fact_lookup | history_why |
|----------------|-----------------------------|-------------|
| VALID | 1.0 | 1.0 |
| REQUIRES_REVIEW | 0.6 | 0.8 |
| STALE | 0.2 | 0.8 |
| CONTRADICTED | 0.3 | 0.9 |
| SUPERSEDED | **0.0 (excluded)** | **1.0 (included and annotated)** |

- Why this matters: the query *"what database did we finally choose and why?"* **needs** the superseded MongoDB decision; the query *"what database do we use?"* must **not** surface it as current.
- Trust enters the selector as **one bounded additive term** with a weight (never a multiplier that can wipe out relevance), except for the explicit exclusion of SUPERSEDED under current-state intents (configurable).
- Compiler (Abinav) renders non-VALID memories with explicit annotations (R3), so the LLM sees *why* something is flagged.

#### 5.3.7 Audit log, explanations, and correction viewer
- `AuditLog.record(...)` stores: query, intent, config hash, candidate IDs + scores, selected IDs **with versions and validity at selection time**, compiled-context hash (and text), model, response, per-stage timings.
- `explain(request_id)` returns for each selected memory its provenance chain, validity history, and any correction that affected it.
- **Correction viewer** (small Streamlit or static HTML page): *original fact → correction → affected memories (with state and impact) → current state*. This is also your strongest demo artifact.

#### 5.3.8 Experiments

| Arm | Description |
|-----|-------------|
| P0 | No provenance, no validity handling |
| P1 | Provenance-aware scoring only |
| P2 | P1 + versioning/supersession |
| P3 | P2 + correction propagation |
| P4 | P3 + contradiction handling |

Inject controlled corrections varying: **propagation depth** (1–4 hops), **fan-out** (1–10 dependents), and **graph noise** (drop or corrupt 10/20/30 % of lineage edges to test robustness).

Metrics: stale-in-context rate, stale-in-answer rate, propagation precision/recall, unnecessary-invalidation rate, answer accuracy, contradiction rate in answers, latency overhead, **sensitivity to θ_high, θ_low, D**. Also report the oracle-lineage vs extracted-lineage gap.

#### 5.3.9 Weekly plan

| Weeks | Deliverable |
|-------|-------------|
| 1–2 | `ProvenanceStore` interface + mock; validity-state enum and transition table; direction-convention test fixture with Christo |
| 3–6 | Provenance capture hook; `validity_log`; explicit-supersession handling (explicit edges only); `trust()` v0 (provenance × validity); stale-flagging working on fixtures |
| 7–10 | Lineage queries; propagation algorithm (steps 1–3) with transactions + idempotency; F3 scenarios authored; propagation P/R on dev |
| 11–14 | NLI-based contradiction pipeline; resolution policy; F4/F8 scenarios; audit log + `explain()`; **your scenarios complete by W12 so benchmark v2 can lock at W14** |
| 15–18 | Optional re-evaluation step (bounded); trust-scoring integration with Adhityan's selector; intent-dependent multipliers tuned on dev; correction viewer |
| 19–22 | P0–P4 experiments on test; noise-robustness and θ-sensitivity sweeps |
| 23–24 | Chapter/seminar writing, demo support |

#### 5.3.10 Acceptance criteria
- On fixtures: every memory downstream of a corrected memory within depth D and impact ≥ θ_low is marked; none outside the lineage cone is marked.
- Propagation is idempotent and transactional (crash-injection test leaves a consistent state).
- SUPERSEDED memories are excluded for current-state queries and included-and-annotated for history queries (end-to-end test).
- `explain(request_id)` reconstructs the full provenance chain for every selected memory.

#### 5.3.11 Risks and fallbacks
| Risk | Fallback |
|------|----------|
| Lineage edges are sparse/noisy → low propagation recall | Report oracle vs extracted lineage; add conservative `related_to`-based REQUIRES_REVIEW as an ablation |
| Over-invalidation hurts accuracy | Tune θ; keep REQUIRES_REVIEW as the default for low impact; report the unnecessary-invalidation trade-off curve |
| NLI model is weak on domain text | Rely on explicit-correction detection + LLM judge on a small band; document precision/recall honestly |

---

### 5.4 Adhityan — Resource-Aware Selection and Cache-Aware Serving

**Research question:** How can context selection jointly optimize relevance, graph structure, redundancy, token budget, cache reuse, and serving latency?
**Core contribution:** Layout-aware, token-budgeted, graph-aware selection + a cache-aware stable-block manager + serving instrumentation, evaluated against vector top-k, MMR, PPR, and PCST baselines.

#### 5.4.1 Retrieval orchestration and bounded expansion
```text
analysis → Retriever (dense + keyword via Christo's search) → seeds (top-m, default 10)
         → BFS expansion: depth ≤ 2, max_nodes 200, fan-out cap 20, relation filter
         → candidate subgraph (nodes, typed weighted edges)
```
Log candidate count per query; measure how often gold evidence is **in the candidate set** (candidate recall), because no selector can recover evidence that retrieval never produced.

#### 5.4.2 Scoring

**Baseline scorer B0** (kept as the reference baseline):
```text
Score0(v,q) = α·S_tag + β·S_recency + γ·S_proximity + δ·S_embedding
```
| Signal | Definition |
|--------|------------|
| `S_tag` | Overlap between query entities/keywords and the memory's entities/tags |
| `S_recency` | Exponential decay, half-life per memory type |
| `S_proximity` | `1 / (1 + graph_distance_to_nearest_seed)` |
| `S_embedding` | Cosine(query, memory) |

**Extended scorer** adds signals; every signal is **min-max normalized within the candidate set**:
```text
P(v,q) = w_sem·S_sem + w_ppr·S_ppr + w_tag·S_tag + w_time·S_time(intent)
       + w_imp·S_imp + w_trust·S_trust
```
Weights live in config, are **tuned on the dev split only** (random search over a coarse grid, fixed budget of trials), and are reported with sensitivity analysis. Use distinct names per module so the same Greek letter never means two things.

#### 5.4.3 Personalized PageRank (PPR)
- Seeds weighted by softmax of similarity over the top-m seeds.
- Graph: the candidate subgraph; typed edge weights from config; treat directed edges as bidirectional with a reverse-weight factor `ρ` (default 0.5).
- Compute with SciPy sparse power iteration: damping 0.85 (restart 0.15), tolerance 1e-6, ≤ 50 iterations; handle dangling nodes.
- Expected benefit: multi-hop evidence that is graph-connected but not similar to the query (family F2). **Hypothesis to test, not assume.**

#### 5.4.4 Redundancy (MMR) — incremental, O(n·k)
```text
R(v | S) = max_{u ∈ S} cos(E_v, E_u)         (0 when S is empty)
```
Maintain `max_sim[v]` for every candidate; when item `u` is added to `S`, update `max_sim[v] = max(max_sim[v], cos(E_v, E_u))`. Never build a full n×n matrix. Optional hard near-duplicate filter (cosine > 0.97). Sweep the redundancy weight.

#### 5.4.5 Selector family (all share one interface; all must respect the budget)

| ID | Selector | Description |
|----|----------|-------------|
| S0 | Vector top-k | Fill the budget by embedding similarity (baseline) |
| S1 | Weighted greedy | Descending `P(v)` until budget is full |
| S2 | **Density greedy** | Pick by `U(v|S) / rendered_tokens(v)^a`, `a ∈ [0.5, 1]` |
| S3 | MMR-greedy | S2 with the redundancy term |
| S4 | PPR + greedy | S3 with `S_ppr` in `P` |
| S5 | **Full utility** | S4 + graph-coherence term + dependency bundles |
| S6 | Layout-aware / cache-aware | S5 + tier manager + plan-level cache cost (5.4.7) |
| S7 | PCST | Experimental comparison (5.4.9) |

**Utility used by S2–S6:**
```text
U(v | S) = P(v) + λ_g·G(v | S) − μ·R(v | S)
G(v | S) = Σ_{u∈S, typed edge(v,u)} w(edge) / Σ_{all candidate edges of v} w(edge)     ∈ [0,1]
```
**Dependency bundles (closure):** if `v` has hard parents `required_parents(v)` (VALID, in `DEP_TYPES`) that are not yet selected, treat `{v} ∪ missing_parents` as one **bundle** with summed cost and summed utility. Depth ≤ 2. This stops the selector from picking a decision while omitting the experiment that justifies it.

**Greedy details:**
- Compute `rendered_tokens` via Abinav's `rendered_token_cost`; never use raw text tokens.
- After the greedy pass, compare against the **best single feasible item** (or bundle) by total utility and keep the better one (classic knapsack-greedy safeguard).
- Complexity is fine for n ≤ ~300 candidates with incremental redundancy; lazy-greedy with a priority queue is an optional optimization.
- **Theory caveat:** approximation guarantees for cost-benefit greedy hold for *monotone submodular* objectives; the subtractive redundancy term does not formally satisfy this. Present the selector as a **heuristic evaluated empirically**, not as a provably optimal method.
- **Pinned items** (e.g., the user's explicit "remember this") are inserted first and reduce the remaining budget.

#### 5.4.6 Serving stack and hardware ladder

| Option | Setup | What you can claim |
|--------|-------|--------------------|
| **A (preferred)** | Institutional/cloud GPU (≈ 16–24 GB) running a 7–8B instruct model under **vLLM with automatic prefix caching** | Real TTFT and cache-hit measurements |
| **B** | Smaller model (1–3B) on a smaller/free-tier GPU | Real but smaller-scale measurements; say so |
| **C (fallback)** | `SimulatedCacheAdapter` = shadow prefix tracker + latency model calibrated from a short real run | **Cache-hit and token savings are real computations; TTFT is modeled.** Label all latency numbers as simulated |

**Decide A/B/C by week 3** and write the decision into the repo. Check the vLLM version's flags and metric names at setup time (prefix-caching options and Prometheus metric names have changed across releases) and record the version in every run record.

`CacheAdapter` implementations:
- `VLLMAdapter`: OpenAI-compatible streaming API (for TTFT), reads engine metrics and the per-request cached-token count if the version exposes it.
- `SimulatedCacheAdapter`: for unit tests, CI, and Option C.

#### 5.4.7 Cache-aware selection — the revised design

**Why per-memory cache cost does not work:** prefix caches reuse only the longest common prefix, so the cost of a prompt depends on *where it first diverges*, not on a per-item sum. v2 therefore models cache cost at the **plan level**:

```text
uncached_tokens(plan) = total_prompt_tokens(plan) − LCP_tokens(plan, cached_prefixes)
J(plan) = Σ_{v ∈ plan} U(v) − λ_c · uncached_tokens(plan) / B_memory       # dimensionless
subject to  Σ rendered_tokens ≤ B_memory
```

**PrefixTracker (shadow cache):**
- Maintains a trie of **block hashes** of recently served prompts (block size = the engine's block size; verify for your version).
- `expected_cached_tokens(prompt_tokens)` returns the longest matching block-aligned prefix.
- LRU capacity approximates the engine's cache capacity (conservative setting).
- **Validate** against the engine's reported cached tokens per request; report mean absolute prediction error. If it is poor, use the engine-reported value from the previous turn as feedback.

**StableBlockManager (Tier 1 with hysteresis):**
```text
Each request:
  proposed_T1  = best Tier-1 set under current signals (stable semantic memories, key decisions)
  gain         = Σ U(proposed_T1) − Σ U(current_T1)
  loss         = cached_tokens_lost_by_changing_T1 / B_memory
  refresh iff  gain > λ_c · loss + κ        # hysteresis margin κ
          OR   any memory in current_T1/T2 is STALE / SUPERSEDED / CONTRADICTED   # correctness overrides cache
```
- Tier 3 is then selected normally (S5) under the remaining budget `B_q = B_memory − tokens(T1) − tokens(T2)`.
- Everything in Tiers 0–2 follows the prefix contract (§2.3): deterministic rendering, no dynamic strings.
- **Multi-session sharing:** sessions on the same project share Tier 0 + Tier 1 verbatim; this is where large cache benefits should appear.

#### 5.4.8 Latency instrumentation and overhead budget
```text
TTFT = T_analyze + T_retrieve + T_expand + T_score + T_select + T_compile + T_queue + T_prefill(uncached) + T_first_token
CtxFlow overhead = T_analyze + T_retrieve + T_expand + T_score + T_select + T_compile
```
- Set an **overhead target** early (for example, selection p95 < 100 ms at n = 300 candidates) and profile against it. The target is a goal to be measured, not an assumption.
- Report the net effect: overhead vs saved model-side work (answers S5).
- Measure on a quiet machine, fixed GPU, **warm-up requests discarded, ≥ 5 repetitions, report medians and p95**.

#### 5.4.9 PCST (experimental comparison only)
- Node prize = `P(v)`; edge cost = `c₀ / weight(edge)`, scaled by a global factor.
- Use an existing solver (e.g., the `pcst_fast` package used in graph-RAG work; verify installation early).
- **Budget handling:** binary-search the global cost scale until the solution's rendered tokens ≤ `B_memory`, then trim by prize density if still over.
- **Limitations to state in the report:** PCST optimizes connected structure rather than a knapsack, does not model redundancy, and cache cost is not an edge cost. Expect it to help on connectivity-dependent queries (F2) and not necessarily elsewhere.

#### 5.4.10 Experiments

| ID | Experiment | Arms |
|----|------------|------|
| E-D1 | Retrieval | Vector only · Vector+BFS · Vector+PPR · Vector+graph-aware scoring |
| E-D2 | Selection (equal budgets) | S0 · S1 · S2 · S3 · S4 · S5 · S7 (S6 handled in E-D3) |
| E-D3 | Serving (multi-turn replay, 20 queries/session) | A0 flat/no-tier · A1 tiered, no cache cost · A2 tiered + hysteresis · A3 tiered + hysteresis + cache-aware refresh; each with prefix caching ON/OFF |
| E-D4 | Multi-session shared prefix | 1, 4, 8 sessions sharing Tier 1 |
| E-D5 | Scorer ablation | Remove one signal at a time (sem, ppr, tag, time, imp, trust) |
| E-D6 | Candidate recall | BFS depth 1/2/3 × fan-out caps |
| E-A5 (joint) | Ordering gain vs prefix loss | O-strategies × tiered/flat × cache ON |

Metrics: accuracy, Evidence Recall@B, tokens, redundancy ratio, selection latency, TTFT (p50/p95), total latency, cached-token fraction, estimated cost/request. **Headline plot:** accuracy vs token budget, all selectors at equal budgets.

#### 5.4.11 Weekly plan

| Weeks | Deliverable |
|-------|-------------|
| 1–2 | `Selector`/`Scorer`/`CacheAdapter` interfaces + mocks; selection works on hand-made fixtures; **GPU option decision started** |
| 3–6 | B0 scorer, S0–S2 (top-k, weighted greedy, density greedy), budget property tests, timing instrumentation, `VLLMAdapter` hello-world (or Option C sim); **GPU decision final at W3** |
| 7–10 | MMR (incremental), PPR, scorer v2 with normalization, dependency bundles, `PrefixTracker` + validation vs engine |
| 11–14 | S5 full utility; dev-split weight tuning; E-D1/E-D2 on dev; candidate-recall analysis |
| 15–18 | `StableBlockManager`, S6, E-D3/E-D4 setup; PCST (S7); joint E-A5 with Abinav; **feature freeze W18** |
| 19–22 | Final test runs; scale/latency test; sensitivity analyses |
| 23–24 | Chapter/seminar writing, demo support |

#### 5.4.12 Acceptance criteria
- Every selector returns a result with `Σ rendered_tokens ≤ B_memory` on ≥ 1,000 randomized inputs (property test); results are deterministic given a seed.
- Incremental redundancy matches a brute-force n×n implementation on small inputs.
- `PrefixTracker` reports the exact LCP on synthetic prompt pairs and its prediction error vs the engine is measured and reported.
- Tier 0–2 text is byte-identical across consecutive requests when `StableBlockManager` holds (test).
- A STALE/SUPERSEDED memory in Tier 1 forces refresh (integration test with Harikesh).

#### 5.4.13 Risks and fallbacks
| Risk | Fallback |
|------|----------|
| No suitable GPU | Option C; claim token and cache-hit savings, label TTFT as simulated |
| Engine cache metrics differ by version | Pin the vLLM version; use the shadow tracker as primary and engine numbers as validation |
| PPR/MMR/cache-aware show no gain | Report as a finding with the sensitivity analysis; the baseline comparison is still a contribution |
| PCST install/time sink | Cap at ~1 week; drop to an extension (§10) |

---

```
CtxFlow/
├── src/
│   ├── ctxflow/                  # Existing (enhanced)
│   │   ├── __init__.py           # Facade: ingest, query, prune, research_trace
│   │   ├── models.py             # + status, superseded_by, Edge.metadata
│   │   ├── graph.py              # + trace_provenance()
│   │   ├── query.py              # + include_superseded filter
│   │   ├── governance.py         # (unchanged)
│   │   ├── pruning.py            # (unchanged)
│   │   ├── extractors.py         # (unchanged)
│   │   ├── serialization.py      # + new fields
│   │   ├── contradiction.py      # NEW: supersession detection
│   │   └── llm_extractor.py      # NEW: LLM-powered Extractor
│   │
│   └── researchos/               # NEW: application layer
│       ├── __init__.py
│       ├── skills/
│       │   ├── registry.py
│       │   ├── literature_search.py
│       │   ├── paper_reader.py
│       │   ├── graph_query.py
│       │   └── review_writer.py
│       ├── agents/
│       │   ├── base.py
│       │   ├── retriever.py
│       │   ├── reader.py
│       │   ├── synthesizer.py
│       │   ├── critic.py
│       │   └── router.py
│       ├── api/                  # FastAPI backend
│       │   ├── main.py
│       │   ├── routes/
│       │   └── schemas.py
│       └── eval/                 # Evaluation harness
│           ├── benchmark.py
│           ├── baselines.py
│           └── metrics.py
│
├── frontend/                     # UI (React/Next.js or HTMX)
│
├── tests/                        # Existing (expanded)
│   ├── test_contradiction.py     # NEW
│   ├── test_llm_extractor.py     # NEW
│   ├── test_skills.py            # NEW
│   ├── test_agents.py            # NEW
│   └── ...existing tests...
│
├── docs/
│   ├── ResearchOS_FYP_Proposal.docx
│   └── ...
│
└── pyproject.toml                # Updated with new deps
```

---

## Dependency Additions

```diff
 # pyproject.toml
 [project]
 dependencies = [
     "networkx>=3.0",
+    "openai>=1.0",          # LLM client (or litellm for multi-provider)
+    "httpx>=0.25",          # Async HTTP for API calls
+    "pymupdf>=1.24",        # PDF parsing
+    "pydantic>=2.0",        # Skill schemas + API models
+    "fastapi>=0.110",       # Backend API
+    "uvicorn>=0.29",        # ASGI server
 ]
+
+[project.optional-dependencies]
+eval = [
+    "chromadb>=0.5",        # Baseline vector store
+    "sentence-transformers>=3.0",  # Embeddings
+]
```

---
