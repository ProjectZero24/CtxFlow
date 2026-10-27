"""Regenerate all PostgreSQL embeddings using local BGE Small.

Run only after migrations/004_bge_small_384_dimension.sql:

    python scripts/reembed_bge.py

The model is loaded before any database update. All updates occur in one
transaction and source text, IDs, versions, and non-embedding metadata are
left unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import asyncpg
from dotenv import dotenv_values

from ctxflow.memory.embeddings import BGE_MODEL_NAME, LocalBGEEmbedder


def _database_values(path: Path) -> dict[str, str]:
    values = dotenv_values(path)
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise ValueError("Missing database configuration: " + ", ".join(missing))
    return {name: str(values[name]) for name in required}


async def _run(dotenv_path: Path, batch_size: int) -> None:
    embedder = LocalBGEEmbedder(local_files_only=True)
    if embedder.model != BGE_MODEL_NAME or embedder.dimension != 384:
        raise RuntimeError("Local embedding model cache is not the expected BGE Small 384 model")
    config = _database_values(dotenv_path)
    connection = await asyncpg.connect(
        host=config["DB_HOST"],
        port=int(config["DB_PORT"]),
        database=config["DB_NAME"],
        user=config["DB_USER"],
        password=config["DB_PASSWORD"],
    )
    try:
        dimensions = await connection.fetch(
            """SELECT table_name, format_type(a.atttypid, a.atttypmod) AS type
            FROM information_schema.columns ic
            JOIN pg_attribute a ON a.attname = ic.column_name
            JOIN pg_class c ON c.oid = a.attrelid AND c.relname = ic.table_name
            WHERE ic.table_schema='public'
              AND ic.column_name='embedding'
              AND ic.table_name = ANY($1::text[])
              AND NOT a.attisdropped""",
            ["memories", "memory_versions"],
        )
        if {row["type"] for row in dimensions} != {"vector(384)"}:
            raise RuntimeError("Database embedding columns must be vector(384) before re-embedding")
        memories = await connection.fetch("SELECT id, text FROM memories ORDER BY id")
        versions = await connection.fetch(
            "SELECT memory_id, version, text FROM memory_versions ORDER BY memory_id, version"
        )
        memory_vectors = await _encode_rows(embedder, memories, batch_size)
        version_vectors = await _encode_rows(embedder, versions, batch_size)
        if len(memory_vectors) != len(memories) or len(version_vectors) != len(versions):
            raise RuntimeError("Embedding model returned an incomplete result")
        async with connection.transaction():
            for row, vector in zip(memories, memory_vectors):
                status = await connection.execute(
                    "UPDATE memories SET embedding=$2::vector, embedding_model=$3 WHERE id=$1",
                    row["id"], _vector(vector), BGE_MODEL_NAME,
                )
                if status != "UPDATE 1":
                    raise RuntimeError(f"Failed to update embedding for memory {row['id']}")
            for row, vector in zip(versions, version_vectors):
                status = await connection.execute(
                    """UPDATE memory_versions SET embedding=$3::vector
                    WHERE memory_id=$1 AND version=$2""",
                    row["memory_id"], row["version"], _vector(vector),
                )
                if status != "UPDATE 1":
                    raise RuntimeError(
                        f"Failed to update embedding for {row['memory_id']} version {row['version']}"
                    )
            remaining = await connection.fetchval(
                "SELECT COUNT(*) FROM memories WHERE embedding IS NULL"
            )
            remaining_versions = await connection.fetchval(
                "SELECT COUNT(*) FROM memory_versions WHERE embedding IS NULL"
            )
            if remaining or remaining_versions:
                raise RuntimeError(
                    "Re-embedding left NULL vectors; transaction rolled back "
                    f"(memories={remaining}, versions={remaining_versions})"
                )
        print(
            f"reembedded_memories={len(memories)} "
            f"reembedded_versions={len(versions)} model={BGE_MODEL_NAME} dimension=384"
        )
    finally:
        await connection.close()


async def _encode_rows(embedder: LocalBGEEmbedder, rows: list[asyncpg.Record], batch_size: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(rows), batch_size):
        vectors.extend(await embedder.embed_many([row["text"] for row in rows[start:start + batch_size]]))
    return vectors


def _vector(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dotenv", type=Path, default=Path(".env"))
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    asyncio.run(_run(args.dotenv, args.batch_size))


if __name__ == "__main__":
    main()
