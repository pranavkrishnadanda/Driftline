import asyncpg
import pytest
from dbseed import seed_source, seed_version


async def _columns(conn, table: str) -> dict[str, str]:
    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = $1",
        table,
    )
    return {r["column_name"]: r["data_type"] for r in rows}


async def test_doc_versions_has_version_key_section_hashes_and_source_meta(conn):
    cols = await _columns(conn, "doc_versions")
    assert cols["version_key"] == "text"
    assert cols["section_hashes"] == "jsonb"
    assert cols["source_meta"] == "jsonb"


async def test_chunks_have_tags_defaulting_empty(conn):
    _, source = await seed_source(conn)
    _, version = await seed_version(conn, source, texts=[])
    await conn.execute("INSERT INTO chunks (version_id, ord, text) VALUES ($1, 0, 'x')", version)
    assert await conn.fetchval("SELECT tags FROM chunks WHERE version_id = $1", version) == []
    assert (await _columns(conn, "chunks"))["tags"] == "ARRAY"


async def test_source_cursors_primary_key(conn):
    _, source = await seed_source(conn)
    insert = "INSERT INTO source_cursors (source_id, external_id, cursor) VALUES ($1, 'x', $2)"
    await conn.execute(insert, source, "1")
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await conn.execute(insert, source, "2")


async def test_fresh_dsn_is_isolated_and_migrated(fresh_dsn, migrated_dsn):
    assert fresh_dsn != migrated_dsn
    fresh = await asyncpg.connect(fresh_dsn)
    try:
        assert await fresh.fetchval("SELECT version_num FROM alembic_version") == "0005"
        assert await fresh.fetchval("SELECT count(*) FROM documents") == 0
    finally:
        await fresh.close()
