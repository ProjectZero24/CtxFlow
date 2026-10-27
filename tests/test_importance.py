from ctxflow.memory.importance import score_importance
from ctxflow.memory.store import Memory, MemoryType


def test_dependent_count_normalization_uses_explicit_maximum():
    memory = Memory("fact", memory_type=MemoryType.FACT)

    score = score_importance(
        memory,
        dependent_count=5,
        max_dependent_count=10,
    )

    assert score == 0.075


def test_ingestion_importance_uses_event_context():
    import asyncio
    from datetime import datetime, timezone

    from ctxflow.memory import Event, EventIngestor, HashEmbedder, InMemoryMemoryStore

    async def run():
        store = InMemoryMemoryStore()
        result = await EventIngestor(
            store, HashEmbedder(dimension=16)
        ).ingest(Event(
            "importance-1", "session", datetime.now(timezone.utc),
            "user", "A durable fact",
        ))
        assert store.memories[result.memory_ids[0]].importance > 0

    asyncio.run(run())
