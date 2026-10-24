import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from ctxflow.memory import (
    Edge,
    Event,
    EventIngestor,
    HashEmbedder,
    Memory,
    MemoryTier,
    MemoryType,
    PostgresMemoryRuntime,
    PostgresMemoryStore,
    Provenance,
    Relation,
    SourceType,
    load_database_config,
)


pytestmark = pytest.mark.postgres


def _database_config():
    if os.getenv("CTXFLOW_RUN_POSTGRES_TESTS") != "1":
        pytest.skip(
            "Set CTXFLOW_RUN_POSTGRES_TESTS=1 to run against the project .env database"
        )
    return load_database_config(Path(".env"))


def test_real_postgres_memory_and_ingestion_path():
    config = _database_config()
    prefix = "ctxflow-it-" + uuid4().hex
    memory_id = prefix + "-memory"
    neighbor_id = prefix + "-neighbor"
    null_embedding_id = prefix + "-null"
    event_id = prefix + "-event"
    event_hash = __import__("hashlib").sha256(event_id.encode()).hexdigest()
    created_memory_ids = {memory_id, neighbor_id, null_embedding_id}

    async def run():
        runtime = await PostgresMemoryRuntime.create(
            dotenv_path=Path(".env"),
            min_size=1,
            max_size=2,
        )
        pool = runtime.pool
        try:
            async with pool.acquire() as connection:
                assert await connection.fetchval(
                    "SELECT current_database()"
                ) == config.database
                table_names = await connection.fetch(
                    """SELECT table_name FROM information_schema.tables
                    WHERE table_schema='public' AND table_name = ANY($1::text[])""",
                    ["memories", "memory_versions", "graph_edges",
                     "provenance", "ingestion_events"],
                )
                assert {row["table_name"] for row in table_names} == {
                    "memories", "memory_versions", "graph_edges",
                    "provenance", "ingestion_events",
                }
                assert await connection.fetchval(
                    "SELECT extversion FROM pg_extension WHERE extname='vector'"
                )
                vector_types = await connection.fetch(
                    """SELECT c.relname AS table_name,
                    format_type(a.atttypid, a.atttypmod) AS type
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid=a.attrelid
                    JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public'
                      AND c.relname = ANY($1::text[])
                      AND a.attname='embedding' AND NOT a.attisdropped""",
                    ["memories", "memory_versions"],
                )
                assert {row["type"] for row in vector_types} == {"vector(384)"}

            store = runtime.store
            vector = [0.0] * 383 + [1.0]
            memory = Memory(
                id=memory_id,
                text="real PostgreSQL memory",
                memory_type=MemoryType.FACT,
                tier=MemoryTier.SEMANTIC,
                session_id=prefix,
                embedding=vector,
            )
            assert await store.add(memory) == memory_id
            saved = await store.get(memory_id)
            assert saved is not None
            assert saved.text == memory.text
            assert saved.memory_type is MemoryType.FACT
            assert saved.tier is MemoryTier.SEMANTIC
            assert saved.embedding == vector

            history = await store.get_version_history(memory_id)
            assert len(history) == 1
            assert history[0].version == 1

            new_vector = [1.0] + [0.0] * 383
            assert await store.create_version(
                memory_id,
                "updated PostgreSQL memory",
                "integration test",
                1,
                "integration-test",
                embedding=new_vector,
            ) == 2
            assert (await store.get(memory_id, version=1)).text == memory.text
            updated = await store.get(memory_id)
            assert updated is not None
            assert updated.text == "updated PostgreSQL memory"
            assert updated.embedding == new_vector
            assert len(await store.get_version_history(memory_id)) == 2
            version_one_as_of = memory.created_at + timedelta(microseconds=1)
            historical = await store.get(memory_id, as_of=version_one_as_of)
            assert historical is not None
            assert historical.text == memory.text

            neighbor = Memory(
                id=neighbor_id,
                text="neighbor memory",
                session_id=prefix,
                embedding=[0.0] * 384,
            )
            null_memory = Memory(
                id=null_embedding_id,
                text="memory without an embedding",
                session_id=prefix,
                embedding=None,  # type: ignore[arg-type]
            )
            await store.add(neighbor)
            await store.add(null_memory)
            await store.add_edge(Edge(memory_id, neighbor_id, Relation.RELATED_TO))
            await store.add_provenance(
                Provenance(
                    memory_id=memory_id,
                    source_type=SourceType.DOCUMENT,
                    source_id=prefix,
                )
            )
            assert any(
                item.memory_id == memory_id
                for item in await store.search(vector, "real", 10)
            )
            assert any(
                item.memory_id == memory_id
                for item in await store.search(
                    vector, "real PostgreSQL memory", 10, as_of=version_one_as_of
                )
            )
            assert await store.search(None, "without an embedding", 10)
            graph = await store.neighbors(
                memory_id,
                depth=1,
                relations=[Relation.RELATED_TO],
                direction="out",
                max_nodes=2,
                fanout_cap=1,
            )
            assert {item.id for item in graph.nodes} == {memory_id, neighbor_id}
            assert len(graph.edges) == 1
            assert graph.edges[0].relation is Relation.RELATED_TO

            ingestor = runtime.ingestor
            event = Event(
                event_id=event_id,
                session_id=prefix,
                ts=datetime.now(timezone.utc),
                role="user",
                content="an event persisted in the real database",
            )
            first = await ingestor.ingest(event)
            second = await ingestor.ingest(event)
            assert not first.duplicate
            assert second.duplicate
            created_memory_ids.add(first.memory_ids[0])
            assert await store.get(first.memory_ids[0]) is not None
            async with pool.acquire() as connection:
                assert await connection.fetchval(
                    "SELECT COUNT(*) FROM ingestion_events WHERE event_hash=$1",
                    event_hash,
                ) == 1
                assert await connection.fetchval(
                    "SELECT COUNT(*) FROM provenance WHERE memory_id=$1",
                    first.memory_ids[0],
                ) == 1

            failed_event = Event(
                event_id=prefix + "-retry-event",
                session_id=prefix,
                ts=datetime.now(timezone.utc),
                role="user",
                content="this event must be retryable",
            )
            with pytest.raises(ValueError, match="embedding dimensions"):
                await EventIngestor(store, HashEmbedder(127)).ingest(failed_event)
            retry = await ingestor.ingest(failed_event)
            assert not retry.duplicate
            created_memory_ids.add(retry.memory_ids[0])
        finally:
            async with pool.acquire() as connection:
                await connection.execute(
                    "DELETE FROM provenance WHERE memory_id = ANY($1::text[])",
                    list(created_memory_ids),
                )
                await connection.execute(
                    "DELETE FROM graph_edges WHERE src = ANY($1::text[]) "
                    "OR dst = ANY($1::text[])",
                    list(created_memory_ids),
                )
                await connection.execute(
                    "DELETE FROM memory_versions WHERE memory_id = ANY($1::text[])",
                    list(created_memory_ids),
                )
                await connection.execute(
                    "DELETE FROM memories WHERE id = ANY($1::text[])",
                    list(created_memory_ids),
                )
                await connection.execute(
                    "DELETE FROM ingestion_events WHERE event_hash = ANY($1::text[])",
                    [
                        __import__("hashlib").sha256(item.encode()).hexdigest()
                        for item in (event_id, prefix + "-retry-event")
                    ],
                )
            await runtime.close()
            assert pool.is_closing()

    asyncio.run(run())
