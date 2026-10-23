-- Week 1-2 memory contract.
-- Current memory rows are denormalized for reads; versions remain append-only.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    tier TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    session_id TEXT,
    source TEXT NOT NULL DEFAULT '',
    importance DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (importance BETWEEN 0 AND 1),
    access_count INTEGER NOT NULL DEFAULT 0 CHECK (access_count >= 0),
    current_version INTEGER NOT NULL DEFAULT 1 CHECK (current_version >= 1),
    validity TEXT NOT NULL DEFAULT 'valid',
    archived BOOLEAN NOT NULL DEFAULT FALSE,
    entities TEXT[] NOT NULL DEFAULT '{}',
    embedding VECTOR,
    embedding_model TEXT NOT NULL DEFAULT '',
    token_counts JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE memory_versions (
    memory_id TEXT NOT NULL REFERENCES memories(id),
    version INTEGER NOT NULL CHECK (version >= 1),
    text TEXT NOT NULL,
    embedding VECTOR,
    created_at TIMESTAMPTZ NOT NULL,
    reason TEXT NOT NULL,
    supersedes_version INTEGER,
    actor TEXT NOT NULL,
    PRIMARY KEY (memory_id, version)
);

CREATE TABLE graph_edges (
    src TEXT NOT NULL REFERENCES memories(id),
    dst TEXT NOT NULL REFERENCES memories(id),
    relation TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (src, dst, relation)
);

CREATE TABLE provenance (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id),
    source_type TEXT NOT NULL,
    source_id TEXT,
    author TEXT,
    tool TEXT,
    extraction_confidence DOUBLE PRECISION NOT NULL CHECK (extraction_confidence BETWEEN 0 AND 1),
    parent_memories TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL
);
