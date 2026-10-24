"""ResearchOS — Multi-agent autonomous scientific research platform.

Built on top of CtxFlow's graph-native context memory engine, ResearchOS
provides:

- **Skills**: Typed, schema-validated tool abstractions (literature search,
  paper reading, graph query, review writing).
- **Agents**: Deterministic multi-agent pipeline (Router → Retriever →
  Reader → Synthesizer → Critic).
- **API**: FastAPI async backend with SSE streaming.
- **Eval**: Benchmark harness comparing graph-based truth maintenance
  against flat vector RAG baselines.
"""

__version__ = "0.1.0"
