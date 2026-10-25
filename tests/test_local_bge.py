import asyncio

import pytest

from ctxflow.memory.embeddings import (
    BGE_EMBEDDING_DIMENSION,
    BGE_MODEL_NAME,
    LocalBGEEmbedder,
)


@pytest.fixture(scope="module")
def embedder():
    try:
        return LocalBGEEmbedder(local_files_only=True)
    except RuntimeError as error:
        pytest.skip(str(error))


def test_local_bge_loads_once_and_returns_normalized_passage_and_query(embedder):
    assert embedder.model == BGE_MODEL_NAME
    assert embedder.dimension == BGE_EMBEDDING_DIMENSION

    async def run():
        passage = await embedder.embed("A local memory about PostgreSQL.")
        query = await embedder.embed_query("What is the memory about?")
        return passage, query

    passage, query = asyncio.run(run())
    assert len(passage) == len(query) == BGE_EMBEDDING_DIMENSION
    assert all(value == pytest.approx(value) for value in passage)
    assert sum(value * value for value in passage) == pytest.approx(1.0, abs=1e-5)
    assert sum(value * value for value in query) == pytest.approx(1.0, abs=1e-5)


def test_local_bge_batch_and_concurrent_calls(embedder):
    async def run():
        batch = await embedder.embed_many(["first memory", "second memory"])
        concurrent = await asyncio.gather(
            embedder.embed("first memory"),
            embedder.embed("second memory"),
        )
        return batch, concurrent

    batch, concurrent = asyncio.run(run())
    assert len(batch) == 2
    assert batch[0] == pytest.approx(concurrent[0], abs=1e-5)
    assert batch[1] == pytest.approx(concurrent[1], abs=1e-5)
