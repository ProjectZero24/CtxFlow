"""Baseline memories for the ResearchOS evaluation harness.

Two baselines are provided, matching Section 5.2 of the proposal:

- **Baseline A** — flat vector retrieval with a single agent.
- **Baseline B** — the same flat vector retrieval, with deterministic stages
  shaped like Retriever → Reader → Synthesizer → Critic.

Neither baseline has access to graph structure, supersession edges, or
provenance chains, which is exactly the contrast the evaluation is
designed to measure.

The embedder is a deterministic hashed bag-of-words vectorizer rather
than ChromaDB/OpenAI embeddings. This keeps the benchmark hermetic and
runnable offline; swap in a real embedder via ``embedder=`` when one is
available.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from researchos.eval.dataset import BenchmarkPaper, BenchmarkQuestion, BenchmarkSuite

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


# ---------------------------------------------------------------------------
# Deterministic embedding
# ---------------------------------------------------------------------------

class HashingEmbedder:
    """Deterministic hashed bag-of-words embedder.

    Each token is hashed into a fixed-width vector with a signed
    contribution (the "hashing trick"), then L2-normalized. Semantically
    weak, but reproducible and dependency-free — sufficient for a
    retrieval baseline that must never be confused with the graph's
    semantic layer.
    """

    def __init__(self, dimensions: int = 256) -> None:
        if dimensions < 8:
            raise ValueError("dimensions must be >= 8")
        self.dimensions = dimensions

    def embed(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    @staticmethod
    def cosine(a: Sequence[float], b: Sequence[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# Flat vector store
# ---------------------------------------------------------------------------

@dataclass
class FlatDocument:
    """A document stored in the flat baseline memory."""

    id: str
    text: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: List[float] = field(default_factory=list)


@dataclass
class FlatHit:
    """A search hit from :class:`FlatVectorStore`."""

    document: FlatDocument
    score: float = 0.0

    @property
    def text(self) -> str:
        return self.document.text

    @property
    def metadata(self) -> Dict[str, Any]:
        return self.document.metadata


class FlatVectorStore:
    """Top-k cosine-similarity store with no relational structure."""

    def __init__(
        self,
        embedder: Optional[HashingEmbedder] = None,
        k: int = 5,
    ) -> None:
        self.embedder = embedder or HashingEmbedder()
        self.k = k
        self.documents: List[FlatDocument] = []
        self._by_id: Dict[str, FlatDocument] = {}

    # -- Ingestion ----------------------------------------------------------

    def ingest(
        self,
        doc_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FlatDocument:
        """Add or replace a document in the store."""
        document = FlatDocument(
            id=doc_id,
            text=text,
            metadata=metadata or {},
            embedding=self.embedder.embed(text),
        )
        self.documents = [d for d in self.documents if d.id != doc_id]
        self.documents.append(document)
        self._by_id[doc_id] = document
        return document

    def ingest_paper(self, paper: "BenchmarkPaper") -> None:
        """Index a benchmark paper and each of its claims as flat chunks."""
        self.ingest(
            paper.id,
            f"Paper: {paper.title}\n{paper.abstract}",
            metadata={"paper_id": paper.id, "title": paper.title},
        )
        for index, claim in enumerate(paper.claims):
            self.ingest(
                f"{paper.id}-claim-{index}",
                claim["text"],
                metadata={
                    "paper_id": paper.id,
                    "claim_text": claim["text"],
                    "tags": list(claim.get("tags", [])),
                },
            )

    def index_suite(self, suite: "BenchmarkSuite") -> None:
        """Index every paper in a benchmark suite."""
        for paper in suite.papers:
            self.ingest_paper(paper)

    # -- Retrieval ----------------------------------------------------------

    def search(self, query: str, k: Optional[int] = None) -> List[FlatHit]:
        """Return the top-*k* documents by cosine similarity."""
        query_embedding = self.embedder.embed(query)
        scored: List[FlatHit] = []
        for document in self.documents:
            score = self.embedder.cosine(query_embedding, document.embedding)
            scored.append(FlatHit(document=document, score=score))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[: (k or self.k)]


# Backwards-compatible alias for the original inline baseline.
FlatRAGBaseline = FlatVectorStore


# ---------------------------------------------------------------------------
# Baseline systems
# ---------------------------------------------------------------------------

@dataclass
class BaselineAnswer:
    """A baseline's answer to one benchmark question."""

    system_name: str
    text: str
    retrieved_texts: List[str] = field(default_factory=list)
    cited_sources: List[str] = field(default_factory=list)
    pipeline: List[str] = field(default_factory=list)
    traceable: bool = False


def _unique(values: Sequence[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


class SingleAgentFlatRAG:
    """Baseline A: one agent, flat top-k vector retrieval."""

    system_name = "Flat vector RAG (single agent)"

    def __init__(
        self,
        k: int = 5,
        embedder: Optional[HashingEmbedder] = None,
    ) -> None:
        self.k = k
        self.store = FlatVectorStore(embedder=embedder, k=k)

    def index_suite(self, suite: "BenchmarkSuite") -> None:
        self.store.index_suite(suite)

    def answer(self, question: "BenchmarkQuestion") -> BaselineAnswer:
        hits = self.store.search(question.question, k=self.k)
        texts = [hit.text for hit in hits]
        sources = _unique(
            [str(hit.metadata.get("paper_id", "")) for hit in hits]
        )
        return BaselineAnswer(
            system_name=self.system_name,
            text=texts[0] if texts else "",
            retrieved_texts=texts,
            cited_sources=sources,
            pipeline=["single_agent"],
            # Flat retrieval stores paper metadata but no provenance chain.
            traceable=False,
        )


class MultiAgentFlatRAG(SingleAgentFlatRAG):
    """Baseline B: four pipeline-shaped stages over the same flat memory.

    The pipeline is intentionally honest about its limits: the Critic
    has no supersession edges or provenance graph to consult, so it can
    only report that no structural verification was possible.
    """

    system_name = "Flat vector RAG (4-stage pipeline-shaped baseline)"

    def answer(self, question: "BenchmarkQuestion") -> BaselineAnswer:
        # Retriever: over-fetch candidates from flat memory.
        hits = self.store.search(question.question, k=self.k * 2)

        # Reader: normalize the retrieved chunks into "claims".
        claims = [hit.text for hit in hits if hit.text.strip()]

        # Synthesizer: compose an answer from the best-matching claim.
        draft = claims[0] if claims else ""

        # Critic: flat memory exposes no lineage, so nothing can be verified.
        logger.debug(
            "Flat-RAG critic: no provenance graph available for %r",
            question.id,
        )

        texts = claims[: self.k]
        sources = _unique(
            [str(hit.metadata.get("paper_id", "")) for hit in hits[: self.k]]
        )
        return BaselineAnswer(
            system_name=self.system_name,
            text=draft,
            retrieved_texts=texts,
            cited_sources=sources,
            pipeline=["retriever", "reader", "synthesizer", "critic"],
            traceable=False,
        )
