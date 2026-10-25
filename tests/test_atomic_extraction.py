import asyncio
from datetime import datetime, timezone

from ctxflow import InMemoryExtractionCache
from ctxflow.llm_extractor import LLMExtractor
from ctxflow.memory import Event, EventIngestor, HashEmbedder, InMemoryMemoryStore


def test_atomic_extraction_validates_retries_and_caches_by_event_hash():
    calls = []

    def llm(_prompt, system=""):
        calls.append(system)
        if len(calls) == 1:
            return "not json"
        return (
            '[{"text":"Uses Postgres","type":"fact","entities":["Postgres"],'
            '"claims":["storage is Postgres"],"refs":["design-1"]}]'
        )

    extractor = LLMExtractor(llm, cache=InMemoryExtractionCache(), extraction_retries=1)
    first = extractor.extract_atomic_memories("We use Postgres.", event_hash="event-1")
    second = extractor.extract_atomic_memories("We use Postgres.", event_hash="event-1")

    assert first == second
    assert len(calls) == 2
    assert first[0].text == "Uses Postgres"
    assert first[0].refs == ["design-1"]


def test_atomic_extraction_falls_back_to_raw_message_after_retries():
    calls = 0

    def llm(_prompt, system=""):
        nonlocal calls
        calls += 1
        return "{}"

    extractor = LLMExtractor(llm, extraction_retries=2)
    result = extractor.extract_atomic_memories("Keep this message.")

    assert calls == 3
    assert [(item.text, item.type) for item in result] == [
        ("Keep this message.", "conversation")
    ]


def test_atomic_cache_version_change_causes_a_miss():
    calls = 0

    def llm(_prompt, system=""):
        nonlocal calls
        calls += 1
        return '[{"text":"Versioned","type":"fact"}]'

    cache = InMemoryExtractionCache()
    first = LLMExtractor(llm, cache=cache, model_version="model-1")
    second = LLMExtractor(llm, cache=cache, model_version="model-2")
    third = LLMExtractor(llm, cache=cache, prompt_version="v2")

    first.extract_atomic_memories("same", event_hash="event-1")
    first.extract_atomic_memories("same", event_hash="event-1")
    second.extract_atomic_memories("same", event_hash="event-1")
    third.extract_atomic_memories("same", event_hash="event-1")

    assert calls == 3


def test_atomic_extraction_falls_back_after_network_failure():
    calls = 0

    def llm(_prompt, system=""):
        nonlocal calls
        calls += 1
        raise OSError("network unavailable")

    extractor = LLMExtractor(llm, extraction_retries=1)
    result = extractor.extract_atomic_memories("Keep this message.")

    assert calls == 2
    assert [(item.text, item.type) for item in result] == [
        ("Keep this message.", "conversation")
    ]


def test_atomic_extraction_falls_back_after_empty_response():
    extractor = LLMExtractor(lambda _prompt, system="": "")

    result = extractor.extract_atomic_memories("Keep this message.")

    assert [(item.text, item.type) for item in result] == [
        ("Keep this message.", "conversation")
    ]


def test_ingestion_persists_multiple_atomic_memories():
    def llm(_prompt, system=""):
        return (
            '[{"text":"Uses Postgres","type":"fact","entities":["Postgres"],'
            '"claims":[],"refs":[]},'
            '{"text":"Prefers async","type":"user_preference",'
            '"entities":[],"claims":[],"refs":[]}]'
        )

    async def run():
        store = InMemoryMemoryStore()
        extractor = LLMExtractor(llm)
        ingestor = EventIngestor(store, HashEmbedder(dimension=16), extractor)
        result = await ingestor.ingest(Event(
            "event-1",
            "session-1",
            datetime.now(timezone.utc),
            "user",
            "We use Postgres and prefer async.",
        ))
        assert len(result.memory_ids) == 2
        assert [store.memories[item].text for item in result.memory_ids] == [
            "Uses Postgres",
            "Prefers async",
        ]

    asyncio.run(run())
