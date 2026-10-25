import uuid
from datetime import UTC, datetime

import asyncpg
import pytest

from driftline.db.migrate import run_migrations

EXPECTED_TABLES = {
    "tenants",
    "sources",
    "documents",
    "doc_versions",
    "chunks",
    "relations",
    "answers",
    "answer_citations",
    "drift_events",
    "review_items",
    "jobs",
    "outbox",
    "eval_runs",
}

INSERT_VERSION = (
    "INSERT INTO doc_versions (document_id, version_no, content_hash, valid_from, valid_to) "
    "VALUES ($1, $2, $3, $4, $5)"
)


def ts(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


async def seed_document(conn) -> uuid.UUID:
    tenant = await conn.fetchval(
        "INSERT INTO tenants (name, api_key_hash) VALUES ($1, 'x') RETURNING id",
        f"t-{uuid.uuid4()}",
    )
    source = await conn.fetchval(
        "INSERT INTO sources (tenant_id, kind) VALUES ($1, 'upload') RETURNING id", tenant
    )
    return await conn.fetchval(
        "INSERT INTO documents (source_id, external_id) VALUES ($1, 'doc-1') RETURNING id", source
    )


async def test_all_spec_tables_exist(conn):
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    assert EXPECTED_TABLES <= {r["table_name"] for r in rows}


async def test_extensions_installed(conn):
    rows = await conn.fetch("SELECT extname FROM pg_extension")
    assert {"vector", "btree_gist"} <= {r["extname"] for r in rows}


def test_migrations_are_idempotent(migrated_dsn):
    run_migrations(migrated_dsn)


async def test_overlapping_versions_are_rejected(conn):
    doc = await seed_document(conn)
    await conn.execute(INSERT_VERSION, doc, 1, "h1", ts(2024), None)
    with pytest.raises(asyncpg.exceptions.ExclusionViolationError):
        await conn.execute(INSERT_VERSION, doc, 2, "h2", ts(2025), None)


async def test_adjacent_versions_are_allowed(conn):
    doc = await seed_document(conn)
    await conn.execute(INSERT_VERSION, doc, 1, "h1", ts(2024), None)
    async with conn.transaction():
        await conn.execute(
            "UPDATE doc_versions SET valid_to = $2 WHERE document_id = $1 AND version_no = 1",
            doc,
            ts(2025),
        )
        await conn.execute(INSERT_VERSION, doc, 2, "h2", ts(2025), None)
    count = await conn.fetchval("SELECT count(*) FROM doc_versions WHERE document_id = $1", doc)
    assert count == 2


async def test_repeated_content_hash_is_allowed_for_a_revert(conn):
    # 0005 dropped UNIQUE (document_id, content_hash): A -> B -> A is three versions.
    # The store, not the schema, makes re-ingesting the current content a no-op.
    doc = await seed_document(conn)
    await conn.execute(INSERT_VERSION, doc, 1, "same", ts(2020), ts(2021))
    await conn.execute(INSERT_VERSION, doc, 2, "other", ts(2021), ts(2022))
    await conn.execute(INSERT_VERSION, doc, 3, "same", ts(2022), None)
    count = await conn.fetchval("SELECT count(*) FROM doc_versions WHERE document_id = $1", doc)
    assert count == 3


async def test_duplicate_version_no_is_rejected(conn):
    doc = await seed_document(conn)
    await conn.execute(INSERT_VERSION, doc, 1, "h1", ts(2020), ts(2021))
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await conn.execute(INSERT_VERSION, doc, 1, "h2", ts(2022), None)


async def test_chunk_tsv_is_generated_and_embedding_is_768(conn):
    doc = await seed_document(conn)
    version = await conn.fetchval(INSERT_VERSION + " RETURNING id", doc, 1, "h", ts(2024), None)
    vec = "[" + ",".join(["0.1"] * 768) + "]"
    await conn.execute(
        "INSERT INTO chunks (version_id, ord, text, embedding, embed_model) "
        "VALUES ($1, 0, 'Boxed warning: hepatotoxicity', $2::vector, 'm')",
        version,
        vec,
    )
    hit = await conn.fetchval(
        "SELECT count(*) FROM chunks WHERE version_id = $1 AND tsv @@ plainto_tsquery('english', 'warning')",
        version,
    )
    assert hit == 1
    with pytest.raises(asyncpg.exceptions.DataError):
        await conn.execute(
            "INSERT INTO chunks (version_id, ord, text, embedding) VALUES ($1, 1, 'x', '[0.1,0.2]'::vector)",
            version,
        )
