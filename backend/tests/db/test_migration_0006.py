import json

import asyncpg
import pytest
from dbseed import seed_source, seed_version

from driftline.db.migrate import downgrade_migrations, run_migrations


async def _nullable(conn, table: str, column: str) -> bool:
    return (
        await conn.fetchval(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = $1 AND column_name = $2",
            table,
            column,
        )
        == "YES"
    )


async def test_migration_0006_requires_tenant_and_allows_the_new_kinds(fresh_conn):
    assert await fresh_conn.fetchval("SELECT version_num FROM alembic_version") == "0006"
    assert not await _nullable(fresh_conn, "review_items", "tenant_id")
    tenant_id, _ = await seed_source(fresh_conn)
    for kind in ("answer", "relation", "broken_answer", "low_confidence_answer"):
        await fresh_conn.execute(
            "INSERT INTO review_items (kind, ref_id, tenant_id) VALUES ($1, gen_random_uuid(), $2)",
            kind,
            tenant_id,
        )
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await fresh_conn.execute(
            "INSERT INTO review_items (kind, ref_id, tenant_id) "
            "VALUES ('other', gen_random_uuid(), $1)",
            tenant_id,
        )
    with pytest.raises(asyncpg.exceptions.NotNullViolationError):
        await fresh_conn.execute(
            "INSERT INTO review_items (kind, ref_id) VALUES ('relation', gen_random_uuid())"
        )
    await fresh_conn.execute(
        "INSERT INTO jobs (tenant_id, kind, status) VALUES ($1, 'ask', 'needs_review')", tenant_id
    )


async def test_migration_0006_upgrade_downgrade_roundtrip(fresh_dsn):
    downgrade_migrations(fresh_dsn, "0005")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await _nullable(conn, "review_items", "tenant_id")
        tenant_id, source_id = await seed_source(conn)
        _, version_id = await seed_version(conn, source_id)
        answer_id = await conn.fetchval(
            "INSERT INTO answers (tenant_id, question, as_of, body) "
            "VALUES ($1, 'q', now(), '{}') RETURNING id",
            tenant_id,
        )
        # Rows written before 0006: the drift hook's 'answer' + reason broken, and a
        # supersession item without a tenant.
        await conn.execute(
            "INSERT INTO review_items (kind, ref_id, tenant_id, payload) "
            "VALUES ('answer', $1, $2, $3::jsonb)",
            answer_id,
            tenant_id,
            json.dumps({"reason": "broken"}),
        )
        await conn.execute(
            "INSERT INTO review_items (kind, ref_id, payload) VALUES ('relation', $1, $2::jsonb)",
            version_id,
            json.dumps({"error": "malformed_extraction"}),
        )
    finally:
        await conn.close()

    run_migrations(fresh_dsn, "head")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0006"
        rows = await conn.fetch("SELECT kind, tenant_id FROM review_items ORDER BY kind")
        assert [(r["kind"], r["tenant_id"]) for r in rows] == [
            ("broken_answer", tenant_id),
            ("relation", tenant_id),
        ]
        await conn.execute(
            "INSERT INTO review_items (kind, ref_id, tenant_id) "
            "VALUES ('low_confidence_answer', gen_random_uuid(), $1)",
            tenant_id,
        )
        await conn.execute(
            "INSERT INTO jobs (tenant_id, kind, status) VALUES ($1, 'ask', 'needs_review')",
            tenant_id,
        )
    finally:
        await conn.close()

    downgrade_migrations(fresh_dsn, "0005")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await _nullable(conn, "review_items", "tenant_id")
        kinds = await conn.fetch("SELECT kind FROM review_items ORDER BY kind")
        assert [r["kind"] for r in kinds] == ["answer", "relation"]
        assert await conn.fetchval("SELECT count(*) FROM jobs WHERE status = 'needs_review'") == 0
    finally:
        await conn.close()
    run_migrations(fresh_dsn, "head")
