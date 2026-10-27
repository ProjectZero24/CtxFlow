"""Opt-in full Groq + local BGE PostgreSQL pipeline diagnostic.

Run with:
    CTXFLOW_RUN_GROQ_TESTS=1 python -m pytest tests/integration/test_memory_pipeline_groq.py -q -s

The conversation is synthetic. The test writes only its own records and removes
them in the final cleanup block.
"""

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import dotenv_values

from ctxflow.llm_extractor import LLMExtractor
from ctxflow.memory import (
    Event,
    LLMEdgeProposer,
    LocalBGEEmbedder,
    PostgresMemoryRuntime,
    embed_query,
    load_database_config,
)
from ctxflow.memory.deduplication import find_duplicates
from ctxflow.providers.groq import GroqLLM
from tests.integration._pipeline_helpers import cleanup_memory_run, stage_header, vector_to_float_list

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@dataclass
class LoggedCall:
    number: int
    purpose: str
    model: str
    elapsed: float
    success: bool
    prompt_preview: str
    response_preview: str


class LoggingGroqLLM:
    """Test-only wrapper that records bounded, purpose-inferred LLM telemetry."""

    def __init__(self, inner: GroqLLM) -> None:
        self.inner = inner
        self.calls: list[LoggedCall] = []

    def __call__(self, prompt: str, system: str = "") -> str:
        purpose = "extraction" if "memory extraction assistant" in system else "edge proposal"
        number = len(self.calls) + 1
        started = time.perf_counter()
        try:
            raw = self.inner(prompt, system=system)
        except Exception:
            elapsed = time.perf_counter() - started
            self.calls.append(
                LoggedCall(number, purpose, getattr(self.inner, "model", "unknown"),
                           elapsed, False, prompt[:240], "<request failed>"))
            raise
        self.calls.append(
            LoggedCall(number, purpose, getattr(self.inner, "model", "unknown"),
                       time.perf_counter() - started, True, prompt[:240], raw[:500]))
        return raw


def _print_call(call: LoggedCall) -> None:
    print(
        f"[PIPELINE][LLM] call={call.number} purpose={call.purpose} model={call.model!r} "
        f"elapsed={call.elapsed:.3f}s success={call.success}\n"
        f"  prompt_preview={call.prompt_preview!r}\n"
        f"  response_preview={call.response_preview!r}"
    )


def _event_content() -> list[tuple[str, str]]:
    return [
        ("fact", "Fact: The Atlas project stores long-term memory in PostgreSQL with pgvector."),
        ("preference", "Remember that I prefer Python async APIs and small, focused modules."),
        ("follow-up", "The memory service should keep PostgreSQL as the source of truth."),
        ("new-fact", "Fact: Redis is used only for short-lived API response caching."),
        ("tool", "The migration tool created the memories, memory_versions, and graph_edges tables successfully."),
        ("temporary", "I am considering a blue dashboard theme for a future demo, but this is not a committed project decision."),
        ("paraphrase", "Fact: Atlas persists its durable context in Postgres using the pgvector extension."),
        ("correction", "Correction: Redis is not the durable memory store; PostgreSQL remains authoritative."),
        ("technical", "We will use bounded graph expansion so retrieval cannot traverse unlimited neighbors."),
        ("tool-query", "The benchmark tool measured a successful cosine search over the Atlas memory index."),
        ("multi-fact", "Fact: The service uses Groq for structured extraction and BGE Small locally for embeddings."),
        ("follow-up", "Fact: BGE Small embeddings run locally without a remote embedding API."),
    ]


async def _count_rows(pool: object, session_id: str) -> dict[str, int]:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """SELECT
                (SELECT COUNT(*) FROM memories WHERE session_id=$1) AS memories,
                (SELECT COUNT(*) FROM memory_versions WHERE memory_id IN
                    (SELECT id FROM memories WHERE session_id=$1)) AS versions,
                (SELECT COUNT(*) FROM provenance WHERE memory_id IN
                    (SELECT id FROM memories WHERE session_id=$1)) AS provenance,
                (SELECT COUNT(*) FROM graph_edges WHERE src IN
                    (SELECT id FROM memories WHERE session_id=$1)
                    OR dst IN (SELECT id FROM memories WHERE session_id=$1)) AS edges,
                (SELECT COUNT(*) FROM ingestion_events WHERE event_id LIKE $2) AS events""",
            session_id,
            f"groq-{session_id}-%",
        )
    return {key: int(row[key]) for key in row.keys()}


def test_memory_pipeline_groq_integration() -> None:
    """Run a traceable multi-event conversation through the complete pipeline."""

    if os.getenv("CTXFLOW_RUN_GROQ_TESTS") != "1":
        pytest.skip("Set CTXFLOW_RUN_GROQ_TESTS=1 to run the live pipeline diagnostic")
    values = dotenv_values(Path(".env"))
    groq_key = os.getenv("GROQ_API_KEY") or values.get("GROQ_API_KEY")
    if not groq_key:
        pytest.skip("GROQ_API_KEY is not configured; skipping the live pipeline diagnostic")

    async def run() -> None:
        run_id = uuid4().hex[:8]
        session_id = f"ctxflow-groq-{run_id}"
        started = time.perf_counter()
        cfg = load_database_config(Path(".env"))
        stage_header("[PIPELINE][STAGE 0: CONFIGURATION]")
        print(
            f"database={cfg.database} host={cfg.host} port={cfg.port} "
            "groq_model=openai/gpt-oss-20b "
            "embedding_model=BAAI/bge-small-en-v1.5 embedding_dimension=384"
        )
        try:
            embedder = LocalBGEEmbedder(local_files_only=True)
        except RuntimeError as error:
            pytest.skip(f"Local BGE model is unavailable: {type(error).__name__}: {error}")

        logging_llm = LoggingGroqLLM(GroqLLM(api_key=groq_key))
        runtime = await PostgresMemoryRuntime.create(
            dotenv_path=Path(".env"),
            embedder=embedder,
            extractor=LLMExtractor(logging_llm),
            edge_proposer=LLMEdgeProposer(logging_llm),
            min_size=1,
            max_size=4,
        )
        memory_ids: list[str] = []
        event_hashes: list[str] = []
        processed = 0
        try:
            assert runtime.store.embedding_dimension == 384
            assert runtime.ingestor.embedder is embedder
            events = _event_content()
            stage_header("[PIPELINE][STAGE 1-8: EVENT INGESTION]")
            for index, (label, content) in enumerate(events, 1):
                event_id = f"groq-{session_id}-{index}"
                event = Event(
                    event_id=event_id,
                    session_id=session_id,
                    ts=datetime.now(timezone.utc),
                    role="tool" if label.startswith("tool") else "user",
                    content=content,
                    tool_name="atlas_diagnostic_tool" if label.startswith("tool") else None,
                )
                before_calls = len(logging_llm.calls)
                before = await _count_rows(runtime.pool, session_id)
                print(
                    f"[PIPELINE][INPUT] event={index} id={event_id} label={label} "
                    f"role={event.role} tool={event.tool_name!r} ts={event.ts.isoformat()}\n"
                    f"  content={content!r}"
                )
                try:
                    result = await runtime.ingestor.ingest(event)
                except Exception as error:
                    stage_header("[PIPELINE][FAILURE DIAGNOSTICS]")
                    print(
                        f"failed_event={index} processed_events={processed} "
                        f"exception={type(error).__name__}: {error} "
                        f"rows={await _count_rows(runtime.pool, session_id)}"
                    )
                    for call in logging_llm.calls:
                        _print_call(call)
                    raise
                processed += 1
                event_hashes.append(hashlib.sha256(event_id.encode()).hexdigest())
                memory_ids.extend(result.memory_ids)
                after = await _count_rows(runtime.pool, session_id)
                print(
                    f"[PIPELINE][IDEMPOTENCY] duplicate={result.duplicate} "
                    f"llm_calls_delta={len(logging_llm.calls) - before_calls} "
                    f"rows_before={before} rows_after={after}"
                )
                print(f"[PIPELINE][PERSISTENCE] result={result}")
                assert not result.duplicate
                assert result.memory_ids
                assert after["memories"] >= before["memories"]

            stage_header("[PIPELINE][STAGE 3: LLM CALL TRACE]")
            for call in logging_llm.calls:
                _print_call(call)
            assert any(call.purpose == "extraction" for call in logging_llm.calls)
            assert any(call.purpose == "edge proposal" for call in logging_llm.calls)

            stage_header("[PIPELINE][STAGE 4-7: DATABASE AND MEMORY TRACE]")
            async with runtime.pool.acquire() as connection:
                rows = await connection.fetch(
                    """SELECT id, text, memory_type, importance, embedding_model, embedding
                    FROM memories WHERE session_id=$1 ORDER BY created_at, id""",
                    session_id,
                )
                edge_rows = await connection.fetch(
                    """SELECT src, dst, relation, confidence, created_by
                    FROM graph_edges WHERE src=ANY($1::text[]) OR dst=ANY($1::text[])""",
                    list(dict.fromkeys(memory_ids)),
                )
                provenance = await connection.fetch(
                    "SELECT memory_id, source_type, tool FROM provenance WHERE memory_id=ANY($1::text[])",
                    list(dict.fromkeys(memory_ids)),
                )
            assert rows
            assert len(provenance) == len(rows)
            assert all(row["embedding_model"] == "BAAI/bge-small-en-v1.5" for row in rows)
            for row in rows:
                vector = vector_to_float_list(row["embedding"])
                print(
                    f"[PIPELINE][MEMORY] id={row['id']} type={row['memory_type']} "
                    f"importance={row['importance']:.3f} model={row['embedding_model']} "
                    f"dimension={len(vector)} preview={vector[:4]}"
                )
                assert len(vector) == 384
            print(f"[PIPELINE][GRAPH] edges={len(edge_rows)} provenance={len(provenance)}")
            for edge in edge_rows:
                print(
                    f"  {edge['src']} -> {edge['dst']} relation={edge['relation']} "
                    f"confidence={edge['confidence']} origin={edge['created_by']}"
                )

            stage_header("[PIPELINE][STAGE 6: DEDUPLICATION OBSERVATION]")
            known = list(runtime.ingestor._known_memories.values())
            assert known
            duplicate_candidates = find_duplicates(known[-1], known[:-1], threshold=0.9)
            print(
                f"[PIPELINE][DEDUP] candidate={known[-1].id} threshold=0.9 "
                f"matches={[(item.memory_id, round(item.similarity, 4)) for item in duplicate_candidates]}"
            )

            stage_header("[PIPELINE][STAGE 9: RETRIEVAL]")
            queries = [
                ("project database", {"PostgreSQL", "pgvector", "Postgres"}),
                ("technical memory retrieval preference", {"async", "graph"}),
                ("authoritative durable memory store", {"PostgreSQL", "Redis"}),
            ]
            for query, expected_terms in queries:
                query_started = time.perf_counter()
                query_vector = await embed_query(embedder, query)
                results = await runtime.store.search(query_vector, query, 3)
                elapsed = time.perf_counter() - query_started
                print(
                    f"[PIPELINE][RETRIEVAL] query={query!r} elapsed={elapsed:.3f}s "
                    f"dimension={len(query_vector)} top_k={len(results)} results={results}"
                )
                result_text = " ".join(item.text for item in known if item.id in {r.memory_id for r in results})
                print(f"  expected_terms={sorted(expected_terms)} observed_text={result_text!r}")
                assert len(query_vector) == 384
                assert results

            stage_header("[PIPELINE][STAGE 10: DUPLICATE EVENT]")
            calls_before = len(logging_llm.calls)
            rows_before = await _count_rows(runtime.pool, session_id)
            duplicate_result = await runtime.ingestor.ingest(
                Event(
                    event_id=f"groq-{session_id}-1",
                    session_id=session_id,
                    ts=datetime.now(timezone.utc),
                    role="user",
                    content=events[0][1],
                )
            )
            rows_after = await _count_rows(runtime.pool, session_id)
            print(
                f"[PIPELINE][IDEMPOTENCY] duplicate_result={duplicate_result} "
                f"llm_calls_delta={len(logging_llm.calls) - calls_before} "
                f"rows_before={rows_before} rows_after={rows_after}"
            )
            assert duplicate_result.duplicate
            assert len(logging_llm.calls) == calls_before
            assert rows_after == rows_before

            stage_header("[PIPELINE][SUMMARY]")
            print(
                f"events_processed={processed} extraction_calls="
                f"{sum(call.purpose == 'extraction' for call in logging_llm.calls)} "
                f"edge_proposal_calls={sum(call.purpose == 'edge proposal' for call in logging_llm.calls)} "
                f"memories_persisted={len(rows)} edges_persisted={len(edge_rows)} "
                f"embedding_batches={processed} elapsed={time.perf_counter() - started:.3f}s"
            )
        finally:
            await cleanup_memory_run(
                runtime.pool,
                memory_ids=dict.fromkeys(memory_ids),
                event_hashes=dict.fromkeys(event_hashes),
            )
            remaining = await _count_rows(runtime.pool, session_id)
            print(f"[PIPELINE][CLEANUP] remaining_run_rows={remaining}")
            assert remaining == {"memories": 0, "versions": 0, "provenance": 0, "edges": 0, "events": 0}
            await runtime.close()

    asyncio.run(run())
