-- Migrate both embedding columns to local BGE Small (384 dimensions).
--
-- This migration never truncates or pads an old vector. Existing vectors are
-- copied to a recoverable backup table before the typed columns are cleared.
-- Run scripts/reembed_bge.py after this migration to regenerate vectors from
-- the stored memory/version text.
BEGIN;

CREATE TABLE IF NOT EXISTS ctxflow_embedding_migration_backup (
    source_table TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    old_embedding VECTOR NOT NULL,
    old_embedding_model TEXT NOT NULL,
    backed_up_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_table, memory_id, version)
);

INSERT INTO ctxflow_embedding_migration_backup
    (source_table, memory_id, version, old_embedding, old_embedding_model)
SELECT 'memories', id, 0, embedding, embedding_model
FROM memories
WHERE embedding IS NOT NULL
ON CONFLICT (source_table, memory_id, version) DO NOTHING;

INSERT INTO ctxflow_embedding_migration_backup
    (source_table, memory_id, version, old_embedding, old_embedding_model)
SELECT 'memory_versions', memory_id, version, embedding, 'historical'
FROM memory_versions
WHERE embedding IS NOT NULL
ON CONFLICT (source_table, memory_id, version) DO NOTHING;

DROP INDEX IF EXISTS memories_embedding_hnsw_idx;

DO $$
DECLARE
    memory_type TEXT;
    version_type TEXT;
BEGIN
    SELECT format_type(a.atttypid, a.atttypmod)
    INTO memory_type
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relname = 'memories' AND a.attname = 'embedding'
      AND NOT a.attisdropped;

    SELECT format_type(a.atttypid, a.atttypmod)
    INTO version_type
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relname = 'memory_versions' AND a.attname = 'embedding'
      AND NOT a.attisdropped;

    IF memory_type <> 'vector(384)' THEN
        ALTER TABLE memories
            ALTER COLUMN embedding TYPE VECTOR(384)
            USING NULL::VECTOR(384);
    END IF;
    IF version_type <> 'vector(384)' THEN
        ALTER TABLE memory_versions
            ALTER COLUMN embedding TYPE VECTOR(384)
            USING NULL::VECTOR(384);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS memories_embedding_hnsw_idx ON memories
    USING hnsw (embedding vector_cosine_ops);

COMMIT;
