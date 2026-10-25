import json

import asyncpg
import pytest
from dbseed import seed_source, seed_version, seed_watched_answer

from driftline.db.migrate import downgrade_migrations, run_migrations

NEW_COLUMNS = {
    ("drift_events", "claim_idx"),
    ("drift_events", "tenant_id"),
    ("answers", "watched_at"),
    ("review_items", "tenant_id"),
    ("review_items", "resolution"),
    ("review_items", "resolved_at"),
    ("review_items", "resolved_by"),
}
NEW_INDEXES = {
    "drift_events_answer_version_claim",
    "review_items_open_kind_ref",
    "answer_citations_chunk",
}


async def _columns(conn: asyncpg.Connection) -> set[tuple[str, str]]:
    rows = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public'"
    )
    return {(r["table_name"], r["column_name"]) for r in rows}


async def _indexes(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    return {r["indexname"] for r in rows}


async def test_seed_watched_answer_writes_answer_and_citations(fresh_conn):
    tenant_id, source_id = await seed_source(fresh_conn)
    _, version_id = await seed_version(fresh_conn, source_id, texts=[("A", "x"), ("B", "y")])
    chunk_ids = [
        r["id"]
        for r in await fresh_conn.fetch(
            "SELECT id FROM chunks WHERE version_id = $1 ORDER BY ord", version_id
        )
    ]
    answer_id = await seed_watched_answer(
        fresh_conn, tenant_id, version_id, chunk_ids, [("claim x", "x"), ("claim y", "y")]
    )
    row = await fresh_conn.fetchrow(
        "SELECT tenant_id, watched, watched_at, body FROM answers WHERE id = $1", answer_id
    )
    assert row["tenant_id"] == tenant_id and row["watched"] and row["watched_at"] is not None
    claims = json.loads(row["body"])["claims"]
    assert [(c["idx"], c["text"], c["citations"][0]["quote"]) for c in claims] == [
        (0, "claim x", "x"),
        (1, "claim y", "y"),
    ]
    assert claims[1]["citations"][0]["version_id"] == str(version_id)
    cites = await fresh_conn.fetch(
        "SELECT claim_idx, chunk_id FROM answer_citations WHERE answer_id = $1 ORDER BY claim_idx",
        answer_id,
    )
    assert [(c["claim_idx"], c["chunk_id"]) for c in cites] == list(enumerate(chunk_ids))


async def test_drift_events_one_row_per_answer_version_claim(fresh_conn):
    tenant_id, source_id = await seed_source(fresh_conn)
    _, version_id = await seed_version(fresh_conn, source_id)
    chunk_id = await fresh_conn.fetchval("SELECT id FROM chunks WHERE version_id = $1", version_id)
    answer_id = await seed_watched_answer(
        fresh_conn, tenant_id, version_id, [chunk_id], [("c", "alpha")]
    )
    insert = (
        "INSERT INTO drift_events (tenant_id, answer_id, old_version_id, new_version_id, "
        "claim_idx, verdict) VALUES ($1, $2, $3, $3, $4, 'still_valid')"
    )
    await fresh_conn.execute(insert, tenant_id, answer_id, version_id, 0)
    await fresh_conn.execute(insert, tenant_id, answer_id, version_id, 1)
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await fresh_conn.execute(insert, tenant_id, answer_id, version_id, 0)


async def test_one_open_review_item_per_kind_and_ref(fresh_conn):
    tenant_id, _ = await seed_source(fresh_conn)
    ref = await fresh_conn.fetchval("SELECT gen_random_uuid()")
    insert = (
        "INSERT INTO review_items (tenant_id, kind, ref_id, status) "
        "VALUES ($1, 'answer', $2, $3) RETURNING id"
    )
    first = await fresh_conn.fetchval(insert, tenant_id, ref, "open")
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await fresh_conn.fetchval(insert, tenant_id, ref, "open")
    await fresh_conn.execute(
        "UPDATE review_items SET status = 'resolved', resolution = '{\"action\": \"approve\"}', "
        "resolved_at = now(), resolved_by = 'alice' WHERE id = $1",
        first,
    )
    await fresh_conn.fetchval(insert, tenant_id, ref, "open")  # a new open item is fine now
    case_id = await fresh_conn.fetchval(
        "INSERT INTO eval_cases (tenant_id, source_review_id, question, as_of, expected) "
        "VALUES ($1, $2, 'q', now(), '{}') RETURNING id",
        tenant_id,
        first,
    )
    assert await fresh_conn.fetchval("SELECT created_at FROM eval_cases WHERE id = $1", case_id)


async def test_migration_0004_backfills_tenant_on_existing_rows(fresh_dsn):
    downgrade_migrations(fresh_dsn, "0003")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        tenant_id, source_id = await seed_source(conn)
        _, version_id = await seed_version(conn, source_id)
        answer_id = await conn.fetchval(
            "INSERT INTO answers (tenant_id, question, as_of, body) "
            "VALUES ($1, 'q', now(), '{}') RETURNING id",
            tenant_id,
        )
        await conn.execute(
            "INSERT INTO drift_events (answer_id, new_version_id, verdict) "
            "VALUES ($1, $2, 'changed')",
            answer_id,
            version_id,
        )
        await conn.execute(
            "INSERT INTO review_items (kind, ref_id) VALUES ('answer', $1), ('relation', $2)",
            answer_id,
            version_id,  # record_malformed queues the version id as the ref
        )
    finally:
        await conn.close()
    run_migrations(fresh_dsn, "head")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT tenant_id FROM drift_events") == tenant_id
        assert await conn.fetchval("SELECT claim_idx FROM drift_events") == 0
        tenants = await conn.fetch("SELECT tenant_id FROM review_items")
        assert [r["tenant_id"] for r in tenants] == [tenant_id, tenant_id]
    finally:
        await conn.close()


async def test_migration_0004_upgrade_downgrade_roundtrip(fresh_dsn):
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0005"
        assert NEW_COLUMNS <= await _columns(conn)
        assert NEW_INDEXES <= await _indexes(conn)
        assert await conn.fetchval("SELECT to_regclass('eval_cases')") == "eval_cases"
        assert {
            "id",
            "tenant_id",
            "source_review_id",
            "question",
            "as_of",
            "expected",
            "created_at",
        } <= {c for t, c in await _columns(conn) if t == "eval_cases"}
    finally:
        await conn.close()

    downgrade_migrations(fresh_dsn, "0003")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0003"
        assert not NEW_COLUMNS & await _columns(conn)
        assert not NEW_INDEXES & await _indexes(conn)
        assert await conn.fetchval("SELECT to_regclass('eval_cases')") is None
    finally:
        await conn.close()

    run_migrations(fresh_dsn, "head")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0005"
    finally:
        await conn.close()
