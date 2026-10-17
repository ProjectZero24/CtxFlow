"""Week 3-6 memory vertical-slice tests."""

import asyncio
from datetime import datetime, timezone

import pytest

from ctxflow.memory import (
    Edge,
    Event,
    EventIngestor,
    HashEmbedder,
    InMemoryMemoryStore,
    Relation,
    SimpleTokenizer,
    count_tokens,
)


def test_ingestion_is_idempotent_and_creates_session_edge():
    async def run():
        store = InMemoryMemoryStore()
        ingestor = EventIngestor(store, HashEmbedder(dimension=16))
        event = Event("e1", "s1", datetime.now(timezone.utc), "user", "remember that blue is preferred")

        first = await ingestor.ingest(event)
        second = await ingestor.ingest(event)

        assert second.duplicate is True
        assert second.memory_ids == first.memory_ids
        assert len(store.memories) == 1
        next_result = await ingestor.ingest(
            Event("e2", "s1", datetime.now(timezone.utc), "assistant", "The preference was applied")
        )
        assert (next_result.memory_ids[0], first.memory_ids[0], Relation.FOLLOWS) in store.edges

    asyncio.run(run())


def test_neighbors_respect_node_cap_and_embedding_is_deterministic():
    async def run():
        store = InMemoryMemoryStore()
        embedder = HashEmbedder(dimension=16)
        ingestor = EventIngestor(store, embedder)
        ids = []
        for index in range(5):
            result = await ingestor.ingest(
                Event(str(index), "s", datetime.now(timezone.utc), "user", f"memory {index}")
            )
            ids.append(result.memory_ids[0])
        for node_id in ids[1:]:
            await store.add_edge(Edge(ids[0], node_id, Relation.RELATED_TO))

        graph = await store.neighbors(ids[0], depth=1, max_nodes=3, fanout_cap=20)
        assert len(graph.nodes) <= 3
        assert await embedder.embed("same") == await embedder.embed("same")

    asyncio.run(run())


def test_token_counts_are_lazy_and_cached():
    memory = type("MemoryLike", (), {"text": "hello, world", "token_counts": {}})()
    tokenizer = SimpleTokenizer()
    assert count_tokens(memory, tokenizer) == 3
    assert memory.token_counts == {"simple-v1": 3}
