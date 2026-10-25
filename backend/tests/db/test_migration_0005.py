from datetime import UTC, datetime

import asyncpg
import pytest
from dbseed import seed_source

from driftline.db.migrate import downgrade_migrations, run_migrations

INSERT_VERSION = (
    "INSERT INTO doc_versions (document_id, version_no, content_hash, valid_from, valid_to) "
    "VALUES ($1, $2, $3, $4, $5)"
)
HASH_KEY = "doc_versions_document_id_content_hash_key"


def ts(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


async def _seed_document(conn: asyncpg.Connection):
    _, source = await seed_source(conn)
    return await conn.fetchval(
        "INSERT INTO documents (source_id, external_id) VALUES ($1, 'doc') RETURNING id", source
    )


async def _constraints(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'doc_versions'::regclass"
    )
    return {r["conname"] for r in rows}


async def test_migration_0005_allows_reverted_content_hash(fresh_conn):
    assert await fresh_conn.fetchval("SELECT version_num FROM alembic_version") == "0006"
    assert HASH_KEY not in await _constraints(fresh_conn)
    doc = await _seed_document(fresh_conn)
    await fresh_conn.execute(INSERT_VERSION, doc, 1, "A", ts(2020), ts(2021))
    await fresh_conn.execute(INSERT_VERSION, doc, 2, "B", ts(2021), ts(2022))
    await fresh_conn.execute(INSERT_VERSION, doc, 3, "A", ts(2022), None)
    assert await fresh_conn.fetchval("SELECT count(*) FROM doc_versions") == 3


async def test_migration_0005_keeps_window_no_overlap_constraint(fresh_conn):
    doc = await _seed_document(fresh_conn)
    await fresh_conn.execute(INSERT_VERSION, doc, 1, "A", ts(2020), None)
    with pytest.raises(asyncpg.exceptions.ExclusionViolationError):
        await fresh_conn.execute(INSERT_VERSION, doc, 2, "A", ts(2021), None)


async def test_migration_0005_upgrade_downgrade_roundtrip(fresh_dsn):
    downgrade_migrations(fresh_dsn, "0004")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0004"
        assert HASH_KEY in await _constraints(conn)
        assert await conn.fetchval("SELECT to_regclass('doc_versions_doc_hash')") is None
    finally:
        await conn.close()
    run_migrations(fresh_dsn, "head")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0006"
        assert HASH_KEY not in await _constraints(conn)
        assert await conn.fetchval("SELECT to_regclass('doc_versions_doc_hash')") is not None
    finally:
        await conn.close()
