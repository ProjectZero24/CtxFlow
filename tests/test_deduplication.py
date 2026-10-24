import asyncio
from datetime import datetime, timezone

from ctxflow.memory import Event, EventIngestor, HashEmbedder, InMemoryMemoryStore
from ctxflow.memory.deduplication import find_duplicates
from ctxflow.memory.store import Memory, MemoryType


def test_find_duplicates_defaults_to_initial_threshold_and_same_type():
    candidate = Memory("candidate", memory_type=MemoryType.FACT, embedding=[1.0, 0.0])
    near = Memory("near", memory_type=MemoryType.FACT, embedding=[0.96, 0.28])
    other_type = Memory("near", memory_type=MemoryType.DECISION, embedding=[0.96, 0.28])

    assert find_duplicates(candidate, [near])
    assert not find_duplicates(candidate, [other_type])


def test_ingestion_uses_top_five_same_type_ann_candidates():
    async def run():
        class RecordingStore(InMemoryMemoryStore):
            def __init__(self):
                super().__init__()
                self.search_calls = []

            async def search(self, query_emb, query_text, k, **kwargs):
                self.search_calls.append((k, kwargs.get("types")))
                return await super().search(query_emb, query_text, k, **kwargs)

        store = RecordingStore()
        ingestor = EventIngestor(store, HashEmbedder(dimension=16))
        await ingestor.ingest(
            Event("first", "session", datetime.now(timezone.utc), "user", "a durable fact")
        )
        await ingestor.ingest(
            Event("second", "session", datetime.now(timezone.utc), "user", "a different fact")
        )

        assert store.search_calls
        assert all(k == 5 for k, _types in store.search_calls)
        assert all(types for _k, types in store.search_calls)

    asyncio.run(run())
