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
