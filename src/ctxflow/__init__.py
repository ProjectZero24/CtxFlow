"""CtxFlow — Schema-agnostic graph-based context management for LLM agents.

Public API surface:

- :class:`CtxFlow` — the primary facade (``ingest``, ``query``, ``prune``,
  ``export``, ``import_``).
- :class:`CtxFlowConfig` — typed configuration with sensible defaults.
- :class:`Node`, :class:`Edge`, :class:`QueryResult` — core data models.
- :class:`Extractor`, :class:`DefaultExtractor` — pluggable extraction.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ctxflow.extractors import DefaultExtractor, Extractor
from ctxflow.governance import GovernanceEngine
from ctxflow.graph import ContextGraph
from ctxflow.models import CtxFlowConfig, Edge, Node, QueryResult
from ctxflow.pruning import Pruner
from ctxflow.query import QueryEngine
from ctxflow.serialization import (
    export_binary,
    export_json,
    import_binary,
    import_json,
)

__all__ = [
    "CtxFlow",
    "CtxFlowConfig",
    "Node",
    "Edge",
    "QueryResult",
    "Extractor",
    "DefaultExtractor",
]


class CtxFlow:
    """High-level facade for the CtxFlow context graph.

    Composes the graph, extractor, governance engine, query engine, and
    pruner behind a clean four-method API::

        ctx = CtxFlow()
        node_id = ctx.ingest("The agent observed a wall ahead.")
        results = ctx.query("What obstacles are nearby?", k=3)
        removed = ctx.prune(threshold=0.7, strategy="drop")
        ctx.export("memory.json")

    Parameters
    ----------
    config : CtxFlowConfig | None
        Framework configuration. Defaults are used if omitted.
    extractor : Extractor | None
        Pluggable text extractor. Falls back to :class:`DefaultExtractor`.
    """

    def __init__(
        self,
        config: CtxFlowConfig | None = None,
        extractor: Extractor | None = None,
    ) -> None:
        self._config = config or CtxFlowConfig()
        self._config.validate()

        self._extractor = extractor or DefaultExtractor()
        self._graph = ContextGraph()
        self._governance = GovernanceEngine(self._config)
        self._query_engine = QueryEngine(self._config, self._extractor, self._governance)
        self._pruner = Pruner(self._config, self._extractor)

    # -- Properties (power-user access) -------------------------------------

    @property
    def config(self) -> CtxFlowConfig:
        """Current framework configuration."""
        return self._config

    @property
    def graph(self) -> ContextGraph:
        """Direct access to the underlying ContextGraph."""
        return self._graph

    @property
    def extractor(self) -> Extractor:
        """The active Extractor instance."""
        return self._extractor

    # -- Ingestion ----------------------------------------------------------

    def ingest(
        self,
        content: str,
        node_type: str | None = None,
        source_id: str | None = None,
        tags: Set[str] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        """Ingest a context unit into the graph.

        Parameters
        ----------
        content : str
            Raw text content of the context unit.
        node_type : str | None
            Free-form type label (e.g. ``"observation"``, ``"decision"``).
        source_id : str | None
            If provided, creates an explicit edge from *source_id* to the
            new node with relation ``"follows"``.
        tags : set[str] | None
            Caller-supplied tags. If ``None``, tags are auto-extracted
            via the configured Extractor.
        metadata : dict | None
            Arbitrary key-value pairs attached to the node.

        Returns
        -------
        str
            The ID of the newly created node.
        """
        # 1. Extract tags and summary.
        extracted_tags = self._extractor.extract_tags(content)
        if tags:
            extracted_tags = extracted_tags | tags
        summary = self._extractor.summarize(content)

        # 2. Create and insert the node.
        node = Node(
            content=content,
            summary=summary,
            tags=extracted_tags,
            node_type=node_type or "generic",
            metadata=metadata or {},
        )
        self._graph.add_node(node)

        # 3. Explicit link (if source_id provided).
        if source_id and self._graph.has_node(source_id):
            if self._governance.can_add_edge(self._graph, source_id):
                edge = Edge(
                    source_id=source_id,
                    target_id=node.id,
                    relation_type="follows",
                    weight=1.0,
                )
                self._graph.add_edge(edge)

        # 4. Implicit links (top-k tag-similar nodes).
        if self._config.max_link_k > 0:
            similar = self._graph.find_similar_by_tags(
                tags=node.tags,
                k=self._config.max_link_k,
                min_similarity=self._config.min_link_similarity,
                exclude={node.id},
            )
            for similar_node, sim_score in similar:
                # Check degree cap before linking.
                if self._governance.can_add_edge(self._graph, node.id):
                    edge = Edge(
                        source_id=node.id,
                        target_id=similar_node.id,
                        relation_type="related_to",
                        weight=sim_score,
                    )
                    self._graph.add_edge(edge)

        return node.id

    # -- Query --------------------------------------------------------------

    def query(
        self,
        context: str,
        k: int = 5,
        weights: Tuple[float, float, float] | None = None,
        anchor: str | None = None,
    ) -> List[QueryResult]:
        """Retrieve the top-*k* most relevant nodes for *context*.

        Parameters
        ----------
        context : str
            Natural-language query (tags auto-extracted via Extractor).
        k : int
            Number of results.
        weights : tuple[float, float, float] | None
            Override ``(alpha, beta, gamma)`` for this query.
        anchor : str | None
            Node ID for proximity scoring (BFS anchor).

        Returns
        -------
        list[QueryResult]
            Ranked results with score breakdowns.
        """
        return self._query_engine.query(
            graph=self._graph,
            context=context,
            k=k,
            weights=weights,
            anchor=anchor,
        )

    # -- Pruning ------------------------------------------------------------

    def prune(
        self,
        threshold: float = 0.5,
        strategy: str = "drop",
    ) -> List[str]:
        """Prune stale nodes from the graph.

        Parameters
        ----------
        threshold : float
            Staleness threshold (0–1). Nodes above this are pruned.
        strategy : str
            ``"drop"`` to delete, ``"summarize"`` to collapse clusters.

        Returns
        -------
        list[str]
            IDs of removed/replaced nodes.
        """
        return self._pruner.prune(
            graph=self._graph,
            threshold=threshold,
            strategy=strategy,
        )

    # -- Persistence --------------------------------------------------------

    def export(self, path: str, format: str = "json") -> None:
        """Serialize the graph to disk.

        Parameters
        ----------
        path : str
            File path to write to.
        format : str
            ``"json"`` (default) or ``"binary"`` (MessagePack).
        """
        if format == "json":
            export_json(self._graph, path)
        elif format == "binary":
            export_binary(self._graph, path)
        else:
            raise ValueError(f"Unknown format: {format!r}. Use 'json' or 'binary'.")

    def import_(self, path: str, format: str = "json") -> None:
        """Load a graph from disk, replacing the current graph.

        Parameters
        ----------
        path : str
            File path to read from.
        format : str
            ``"json"`` (default) or ``"binary"`` (MessagePack).
        """
        if format == "json":
            self._graph = import_json(path)
        elif format == "binary":
            self._graph = import_binary(path)
        else:
            raise ValueError(f"Unknown format: {format!r}. Use 'json' or 'binary'.")
        # Rebuild internal references.
        self._query_engine = QueryEngine(
            self._config, self._extractor, self._governance
        )
        self._pruner = Pruner(self._config, self._extractor)

    # -- Convenience --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CtxFlow(nodes={self._graph.node_count}, "
            f"edges={self._graph.edge_count})"
        )

    def __len__(self) -> int:
        return self._graph.node_count
