import asyncio

import pytest

from ctxflow.memory import (
    DatabaseConfig,
    EventIngestor,
    HashEmbedder,
    PostgresMemoryRuntime,
    create_pool,
    load_database_config,
)


def test_database_config_loads_dotenv_values(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DB_HOST=localhost\nDB_PORT=5432\nDB_NAME=ctxflow_test\n"
        "DB_USER=tester\nDB_PASSWORD=p@ss:word\n",
        encoding="utf-8",
    )

    config = load_database_config(env_file)

    assert config == DatabaseConfig(
        host="localhost",
        port=5432,
        database="ctxflow_test",
        user="tester",
        password="p@ss:word",
    )


def test_database_config_reports_missing_variables(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DB_HOST=localhost\n", encoding="utf-8")

    with pytest.raises(ValueError, match="DB_PORT"):
        load_database_config(env_file)


def test_database_config_reports_invalid_port(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DB_HOST=localhost\nDB_PORT=postgres\nDB_NAME=db\n"
        "DB_USER=user\nDB_PASSWORD=secret\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="DB_PORT must be an integer"):
        load_database_config(env_file)


def test_pool_creation_passes_separate_connection_fields(monkeypatch):
    calls = {}

    async def fake_create_pool(**kwargs):
        calls.update(kwargs)
        return "pool"

    monkeypatch.setattr("ctxflow.memory.runtime.asyncpg.create_pool", fake_create_pool)
    config = DatabaseConfig("localhost", 5432, "db", "user", "p@ss:word")

    assert asyncio.run(create_pool(config, min_size=1)) == "pool"
    assert calls == {
        "host": "localhost",
        "port": 5432,
        "database": "db",
        "user": "user",
        "password": "p@ss:word",
        "min_size": 1,
    }


def test_runtime_closes_pool_and_builds_postgres_ingestor(monkeypatch):
    class FakePool:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    pool = FakePool()

    async def fake_create_pool(**_kwargs):
        return pool

    monkeypatch.setattr("ctxflow.memory.runtime.create_pool", fake_create_pool)

    async def run():
        runtime = await PostgresMemoryRuntime.create(
            embedder=HashEmbedder(dimension=128)
        )
        assert isinstance(runtime.ingestor, EventIngestor)
        assert runtime.store.embedding_dimension == 128
        await runtime.close()
        assert pool.closed

    asyncio.run(run())
