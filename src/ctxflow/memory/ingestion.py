"""Rule-based, idempotent asynchronous memory ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ctxflow.memory.embeddings import Embedder, embed_text
from ctxflow.memory.store import (
    Edge,
    Memory,
    MemoryStore,
    MemoryType,
    MemoryTier,
    Provenance,
    Relation,
    SourceType,
)


@dataclass(frozen=True)
class Event:
    event_id: str
    session_id: str
    ts: datetime
    role: str
    content: str
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    event_hash: str
    memory_ids: list[str]
    duplicate: bool = False


class EventIngestor:
    """MVP ingestion pipeline: classify, embed, persist, and link memories."""

    def __init__(self, store: MemoryStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder
        self._seen: dict[str, list[str]] = {}
        self._last_by_session: dict[str, str] = {}
        self._events: dict[str, Event] = {}

    async def ingest(self, event: Event) -> IngestResult:
        event_hash = hashlib.sha256(event.event_id.encode("utf-8")).hexdigest()
        if event_hash in self._seen:
            return IngestResult(event_hash, list(self._seen[event_hash]), duplicate=True)

        memory_id = hashlib.sha256(
            f"{event_hash}:{event.role}:{event.content}".encode("utf-8")
        ).hexdigest()[:16]
        memory = Memory(
            id=memory_id,
            text=event.content,
            memory_type=self._classify(event),
            tier=MemoryTier.EPISODIC,
            created_at=event.ts,
            session_id=event.session_id,
            source=event.tool_name or event.role,
            embedding_model=self.embedder.model,
            embedding=await embed_text(self.embedder, event.content),
            entities=list(event.metadata.get("entities", [])),
        )
        parent = self._last_by_session.get(event.session_id)
        edge = Edge(memory.id, parent, Relation.FOLLOWS) if parent else None
        provenance = Provenance(
            memory_id=memory.id,
            source_type=SourceType.TOOL_OUTPUT if event.tool_name else SourceType.USER_MESSAGE,
            source_id=event.event_id,
            tool=event.tool_name,
        )
        persist_ingestion = getattr(self.store, "persist_ingestion", None)
        if persist_ingestion is not None:
            persisted = await persist_ingestion(
                event_hash, event.event_id, memory, edge, provenance
            )
            if not persisted:
                return IngestResult(event_hash, [memory_id], duplicate=True)
        else:
            claim_event = getattr(self.store, "claim_event", None)
            if claim_event is not None and not await claim_event(event_hash, event.event_id):
                return IngestResult(event_hash, [memory_id], duplicate=True)
            await self.store.add(memory)
            if parent:
                await self._add_edge(edge)
            await self._add_provenance(provenance)
        self._seen[event_hash] = [memory.id]
        self._events[event_hash] = event
        self._last_by_session[event.session_id] = memory.id
        return IngestResult(event_hash, [memory.id])

    async def _add_edge(self, edge: Edge) -> None:
        add_edge = getattr(self.store, "add_edge", None)
        if add_edge is not None:
            await add_edge(edge)

    async def _add_provenance(self, provenance: Provenance) -> None:
        add_provenance = getattr(self.store, "add_provenance", None)
        if add_provenance is not None:
            await add_provenance(provenance)

    @staticmethod
    def _classify(event: Event) -> MemoryType:
        if event.tool_name:
            return MemoryType.TOOL_RESULT
        text = event.content.lower()
        if "remember that" in text or "i prefer" in text:
            return MemoryType.USER_PREFERENCE
        if text.startswith(("decided", "decision:", "we will")):
            return MemoryType.DECISION
        return MemoryType.CONVERSATION


def utc_now() -> datetime:
    """Return an aware UTC timestamp for callers creating events."""

    return datetime.now(timezone.utc)
