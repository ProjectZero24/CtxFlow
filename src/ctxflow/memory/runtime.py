"""Application lifecycle helpers for the PostgreSQL memory path."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg
from dotenv import dotenv_values

from ctxflow.memory.embeddings import Embedder, HashEmbedder
from ctxflow.memory.ingestion import EventIngestor
from ctxflow.memory.postgres_store import PostgresMemoryStore

_REQUIRED_DATABASE_VARIABLES = (
    "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"
)


@dataclass(frozen=True)
class DatabaseConfig:
    """Connection settings loaded independently from environment variables."""

    host: str
    port: int
    database: str
    user: str
    password: str


def load_database_config(dotenv_path: str | Path | None = None) -> DatabaseConfig:
    """Load and validate PostgreSQL settings without constructing a URL."""

    values = dotenv_values(dotenv_path) if dotenv_path is not None else dotenv_values()
    missing = [name for name in _REQUIRED_DATABASE_VARIABLES if not values.get(name)]
    if missing:
        raise ValueError(
            "Missing required database environment variables: " + ", ".join(missing)
        )
    try:
        port = int(str(values["DB_PORT"]))
    except ValueError as error:
        raise ValueError("DB_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("DB_PORT must be between 1 and 65535")
    return DatabaseConfig(
        host=str(values["DB_HOST"]),
        port=port,
        database=str(values["DB_NAME"]),
        user=str(values["DB_USER"]),
        password=str(values["DB_PASSWORD"]),
    )


async def create_pool(
    config: DatabaseConfig | None = None,
    *,
    dotenv_path: str | Path | None = None,
    **pool_options: Any,
) -> Any:
    """Create an asyncpg pool using separate, validated connection fields."""

    settings = config or load_database_config(dotenv_path)
    return await asyncpg.create_pool(
        host=settings.host,
        port=settings.port,
        database=settings.database,
        user=settings.user,
        password=settings.password,
        **pool_options,
    )


@dataclass
class PostgresMemoryRuntime:
    """Owned PostgreSQL resources and the configured event ingestor."""

    pool: Any
    store: PostgresMemoryStore
    ingestor: EventIngestor

    @classmethod
    async def create(
        cls,
        *,
        embedder: Embedder | None = None,
        dotenv_path: str | Path | None = None,
        **pool_options: Any,
    ) -> "PostgresMemoryRuntime":
        pool = await create_pool(dotenv_path=dotenv_path, **pool_options)
        active_embedder = embedder or HashEmbedder(dimension=128)
        store = PostgresMemoryStore(pool, embedding_dimension=128)
        return cls(pool, store, EventIngestor(store, active_embedder))

    async def close(self) -> None:
        await self.pool.close()

    async def __aenter__(self) -> "PostgresMemoryRuntime":
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        await self.close()
