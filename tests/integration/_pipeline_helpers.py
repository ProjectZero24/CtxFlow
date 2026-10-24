from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Iterable

from dotenv import dotenv_values


def load_runtime_env(dotenv_path: str | Path = ".env") -> dict[str, str]:
    values = dotenv_values(dotenv_path)
    return {key: str(value) for key, value in values.items() if key and value is not None}


def write_db_only_env(tmp_path: Path, dotenv_path: str | Path = ".env") -> Path:
    values = load_runtime_env(dotenv_path)
    lines = [
        f"{key}={values[key]}"
        for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
        if key in values and values[key]
    ]
    env_path = tmp_path / ".env"
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


async def cleanup_memory_run(pool: object, *, memory_ids: Iterable[str], event_hashes: Iterable[str]) -> None:
    memory_ids = tuple(dict.fromkeys(memory_ids))
    event_hashes = tuple(dict.fromkeys(event_hashes))
    if not memory_ids and not event_hashes:
        return
    async with pool.acquire() as connection:
        async with connection.transaction():
            if memory_ids:
                await connection.execute(
                    "DELETE FROM graph_edges WHERE src = ANY($1::text[]) OR dst = ANY($1::text[])",
                    list(memory_ids),
                )
                await connection.execute(
                    "DELETE FROM provenance WHERE memory_id = ANY($1::text[])",
                    list(memory_ids),
                )
                await connection.execute(
                    "DELETE FROM memory_versions WHERE memory_id = ANY($1::text[])",
                    list(memory_ids),
                )
                await connection.execute(
                    "DELETE FROM memories WHERE id = ANY($1::text[])",
                    list(memory_ids),
                )
            if event_hashes:
                await connection.execute(
                    "DELETE FROM ingestion_events WHERE event_hash = ANY($1::text[])",
                    list(event_hashes),
                )


def stage_header(label: str) -> None:
    print(f"\n=== {label} ===")


def preview_vector(values: Iterable[float], *, limit: int = 8) -> list[float]:
    preview = list(values)
    return preview[:limit]


def vector_to_float_list(value: object) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            parsed = ast.literal_eval(stripped)
            return [float(item) for item in parsed]
        return [float(stripped)]
    return [float(value)]
