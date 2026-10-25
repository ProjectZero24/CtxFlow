"""Opt-in fallback pipeline integration test for the PostgreSQL memory path.

Run with:
    CTXFLOW_RUN_POSTGRES_TESTS=1 python -m pytest tests/integration/test_memory_pipeline_fallback.py -q -s
"""

import asyncio
import hashlib
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from ctxflow.memory import (
    Event,
    EventIngestor,
    HashEmbedder,
    PostgresMemoryRuntime,
    Relation,
    load_database_config,
)
from tests.integration._pipeline_helpers import (
    cleanup_memory_run,
    stage_header,
    vector_to_float_list,
    write_db_only_env,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def test_memory_pipeline_fallback_integration(tmp_path):
    """Exercise the PostgreSQL memory pipeline with an explicit test embedder.

    The explicit HashEmbedder keeps this integration test independent of model
    weights while production runtime creation always uses local BGE.
    """
    if os.getenv("CTXFLOW_RUN_POSTGRES_TESTS") != "1":
        pytest.skip("Set CTXFLOW_RUN_POSTGRES_TESTS=1 to run the real PostgreSQL fallback pipeline test")

    async def run():
        env_path = write_db_only_env(tmp_path, ".env")
        config = load_database_config(env_path)
        run_id = uuid4().hex[:8]
        session_id = f"ctxflow-fallback-{run_id}"
        stage_header("Fallback pipeline configuration")
        print(
            f"database={config.database} host={config.host} port={config.port} "
            f"user={config.user} api_key_configured=False embedder=hash-v1"
        )

        runtime = await PostgresMemoryRuntime.create(
            dotenv_path=env_path,
            embedder=HashEmbedder(dimension=384),
            min_size=1,
            max_size=4,
        )
        memory_ids: list[str] = []
        event_hashes: list[str] = []
        try:
            assert isinstance(runtime.ingestor.embedder, HashEmbedder)
            assert runtime.ingestor.extractor is None
            assert runtime.store.embedding_dimension == 384
            print("explicit test embedder verified: runtime is using HashEmbedder")

            stage_header("Fallback pipeline input")
            events = [
                Event(
                    event_id=f"fallback-{run_id}-primary",
                    session_id=session_id,
                    ts=datetime.now(timezone.utc),
                    role="user",
                    content="The project uses PostgreSQL 18 with pgvector for storing memory embeddings.",
                ),
                Event(
                    event_id=f"fallback-{run_id}-primary-repeat",
                    session_id=session_id,
                    ts=datetime.now(timezone.utc),
                    role="user",
                    content="The project uses PostgreSQL 18 with pgvector for storing memory embeddings.",
                ),
                Event(
                    event_id=f"fallback-{run_id}-related",
                    session_id=session_id,
                    ts=datetime.now(timezone.utc),
                    role="user",
                    content="The project uses PostgreSQL 18 with pgvector to store vectors for memory.",
                ),
                Event(
                    event_id=f"fallback-{run_id}-redis",
                    session_id=session_id,
                    ts=datetime.now(timezone.utc),
                    role="user",
                    content="Redis caches API responses for fast access.",
                ),
                Event(
                    event_id=f"fallback-{run_id}-tool",
                    session_id=session_id,
                    ts=datetime.now(timezone.utc),
                    role="tool",
                    content="The database migration completed successfully and created the memories table.",
                    tool_name="migration_tool",
                ),
            ]
            for event in events:
                print(
                    f"event_id={event.event_id} role={event.role} tool={event.tool_name} "
                    f"session={event.session_id} content={event.content}"
                )
                result = await runtime.ingestor.ingest(event)
                event_hashes.append(hashlib.sha256(event.event_id.encode("utf-8")).hexdigest())
                print(f"ingest result: {result}")
                if result.memory_ids:
                    memory_ids.extend(result.memory_ids)
                if event.event_id.endswith("-primary"):
                    first_primary = result

            stage_header("Fallback extraction and classification")
            print("fallback extractor path: extractor is None, so EventIngestor used the raw-message fallback")
            print("raw message fallback is intentional and preserves original content when no LLM is available")

            stage_header("Fallback embeddings and deduplication")
            async with runtime.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT id, text, memory_type, embedding_model, embedding FROM memories WHERE session_id = $1 ORDER BY created_at",
                    session_id,
                )
            assert rows, "fallback pipeline should persist at least one memory"
            for row in rows:
                values = vector_to_float_list(row["embedding"])
                assert len(values) == 384
                assert all(math.isfinite(float(value)) for value in values)
                print(f"memory_id={row['id']} type={row['memory_type']} model={row['embedding_model']} preview={values[:8]}")

            async with runtime.pool.acquire() as conn:
                edges = await conn.fetch(
                    "SELECT src, dst, relation, confidence, created_by FROM graph_edges WHERE src = ANY($1::text[]) OR dst = ANY($1::text[])",
                    list(dict.fromkeys(memory_ids)),
                )
            print("graph_edges", [(row["src"], row["dst"], row["relation"], row["confidence"]) for row in edges])
            assert any(row["relation"] == Relation.FOLLOWS.value for row in edges), "expected session ordering edges"
            assert any(row["relation"] == Relation.DUPLICATE_OF.value for row in edges), "expected duplicate detection edge"

            stage_header("Fallback final state")
            async with runtime.pool.acquire() as conn:
                provenance = await conn.fetch(
                    "SELECT memory_id, source_type, tool FROM provenance WHERE memory_id = ANY($1::text[])",
                    list(dict.fromkeys(memory_ids)),
                )
                counts = await conn.fetchval(
                    "SELECT COUNT(*) FROM memories WHERE session_id = $1",
                    session_id,
                )
            print(f"persisted_memory_rows={counts} provenance_records={len(provenance)}")
            print(f"memory_ids={list(dict.fromkeys(memory_ids))}")
        finally:
            await cleanup_memory_run(runtime.pool, memory_ids=dict.fromkeys(memory_ids), event_hashes=dict.fromkeys(event_hashes))
            await runtime.close()

    asyncio.run(run())
