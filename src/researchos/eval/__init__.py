"""ResearchOS Eval — evaluation harness and benchmarks.

Public surface:

- :class:`BenchmarkRunner` — runs the graph system and both flat-RAG
  baselines over a :class:`BenchmarkSuite`.
- :func:`get_default_contradiction_benchmark` — the built-in
  superseded-claim suite.
- :class:`EvaluationMetrics` — answer/provenance/token metrics.
- :class:`FlatVectorStore`,
  :class:`SingleAgentFlatRAG`, :class:`MultiAgentFlatRAG` — baselines.
"""

from researchos.eval.baselines import (
    FlatVectorStore,
    MultiAgentFlatRAG,
    SingleAgentFlatRAG,
)
from researchos.eval.benchmark import BenchmarkRunner
from researchos.eval.dataset import (
    BenchmarkPaper,
    BenchmarkQuestion,
    BenchmarkSuite,
    get_default_contradiction_benchmark,
)
from researchos.eval.metrics import EvaluationMetrics

__all__ = [
    "BenchmarkPaper",
    "BenchmarkQuestion",
    "BenchmarkRunner",
    "BenchmarkSuite",
    "EvaluationMetrics",
    "FlatVectorStore",
    "MultiAgentFlatRAG",
    "SingleAgentFlatRAG",
    "get_default_contradiction_benchmark",
]
