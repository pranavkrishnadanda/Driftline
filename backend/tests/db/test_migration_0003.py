import asyncpg
import pytest
from dbseed import seed_source

from driftline.db.migrate import downgrade_migrations, run_migrations


async def test_llm_calls_table_rejects_negative_tokens(fresh_conn):
    tenant_id, _ = await seed_source(fresh_conn)
    job_id = await fresh_conn.fetchval(
        "INSERT INTO jobs (tenant_id, kind, payload) VALUES ($1, 'ask', '{\"q\": 1}') RETURNING id",
        tenant_id,
    )
    insert = (
        "INSERT INTO llm_calls (job_id, tenant_id, node, tier, provider, model, input_tokens, "
        "output_tokens, cost_usd, latency_ms) VALUES ($1, $2, 'draft', 'answer', 'anthropic', "
        "'claude-sonnet-5-5', $3, 5, 0.001, 12.5)"
    )
    await fresh_conn.execute(insert, job_id, tenant_id, 10)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await fresh_conn.execute(insert, job_id, tenant_id, -1)
    assert await fresh_conn.fetchval("SELECT payload->>'q' FROM jobs WHERE id = $1", job_id) == "1"


async def test_one_answer_per_job_and_status_check(fresh_conn):
    tenant_id, _ = await seed_source(fresh_conn)
    job_id = await fresh_conn.fetchval(
        "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ask') RETURNING id", tenant_id
    )
    insert = (
        "INSERT INTO answers (tenant_id, question, as_of, body, job_id, status) "
        "VALUES ($1, 'q', now(), '{}', $2, $3)"
    )
    await fresh_conn.execute(insert, tenant_id, job_id, "answered")
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await fresh_conn.execute(insert, tenant_id, job_id, "answered")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await fresh_conn.execute(insert, tenant_id, None, "maybe")


async def test_migration_0003_downgrades_and_upgrades_cleanly(fresh_dsn):
    downgrade_migrations(fresh_dsn, "0002")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT to_regclass('llm_calls')") is None
    finally:
        await conn.close()
    run_migrations(fresh_dsn, "head")
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0006"
        assert await conn.fetchval("SELECT to_regclass('llm_calls')") == "llm_calls"
    finally:
        await conn.close()
