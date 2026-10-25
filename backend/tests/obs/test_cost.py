from decimal import Decimal
from uuid import uuid4

from dbseed import seed_source

from driftline.llm.types import CompletionResult, Usage
from driftline.obs.cost import CostLedger, ModelPrice, call_cost, job_cost


def result(provider="anthropic", model="claude-sonnet-5-5", inp=1000, out=500, degraded=False):
    return CompletionResult(
        text="x",
        model=model,
        provider=provider,
        usage=Usage(input_tokens=inp, output_tokens=out),
        latency_ms=120.0,
        degraded=degraded,
    )


def test_call_cost_uses_the_price_table():
    # Sonnet 5.5: $2 / $10 per MTok.
    assert call_cost("anthropic", "claude-sonnet-5-5", 1000, 500) == Decimal("0.007000")
    # Haiku 5.5: $0.10 / $0.50 per MTok, and $0.50 / $2.50 above 100K input tokens.
    assert call_cost("anthropic", "claude-haiku-5-5", 100_000, 0) == Decimal("0.010000")
    assert call_cost("anthropic", "claude-haiku-5-5", 200_000, 1000) == Decimal("0.102500")
    assert call_cost("tei", "BAAI/bge-base-en-v1.5", 10_000, 0) == Decimal(0)
    assert call_cost("deterministic", "anything", 10, 10) == Decimal(0)
    assert call_cost("gemini", "gemini-3.8-flash", 10, 10) is None


def test_a_zero_long_context_rate_is_honoured_not_replaced_by_the_base_rate():
    prices = {"m": ModelPrice(Decimal(1), Decimal(1), 10, Decimal(0), Decimal(0))}
    assert call_cost("anthropic", "m", 5, 5, prices) == Decimal("0.000010")
    assert call_cost("anthropic", "m", 1_000_000, 1_000_000, prices) == Decimal(0)


async def test_ledger_persists_calls_and_sums_per_job(fresh_pool):
    async with fresh_pool.acquire() as conn:
        tenant, _ = await seed_source(conn)
        job = await conn.fetchval(
            "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ask') RETURNING id", tenant
        )
        other = await conn.fetchval(
            "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ask') RETURNING id", tenant
        )
    ledger = CostLedger(fresh_pool)
    await ledger.record(result(), node="draft", tier="answer", job_id=job, tenant_id=tenant)
    await ledger.record(
        result(model="claude-haiku-5-5", inp=400, out=100, degraded=True),
        node="plan",
        tier="extract",
        job_id=job,
        tenant_id=tenant,
    )
    await ledger.record(result(), node="draft", tier="answer", job_id=other, tenant_id=tenant)
    cost = await ledger.record(
        result(provider="gemini", model="gemini-3.8-flash"),
        node="judge",
        tier="judge",
        job_id=job,
        tenant_id=tenant,
    )
    assert cost == Decimal(0) and ledger.unpriced == {"gemini-3.8-flash"}
    async with fresh_pool.acquire() as conn:
        total = await job_cost(conn, job, tenant_id=tenant)
        nodes = await conn.fetch(
            "SELECT node, degraded FROM llm_calls WHERE job_id = $1 ORDER BY id", job
        )
    assert total.calls == 3
    assert (total.input_tokens, total.output_tokens) == (2400, 1100)
    assert total.cost_usd == Decimal("0.007090")  # 0.007 + 0.00009
    assert [(r["node"], r["degraded"]) for r in nodes] == [
        ("draft", False),
        ("plan", True),
        ("judge", False),
    ]


async def test_job_without_calls_costs_nothing(fresh_conn):
    assert (await job_cost(fresh_conn, uuid4(), tenant_id=uuid4())).cost_usd == Decimal(0)


async def test_job_cost_counts_only_the_given_tenants_calls(fresh_pool):
    async with fresh_pool.acquire() as conn:
        tenant, _ = await seed_source(conn)
        intruder, _ = await seed_source(conn)
        job = await conn.fetchval(
            "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ask') RETURNING id", tenant
        )
    ledger = CostLedger(fresh_pool)
    await ledger.record(result(), node="draft", tier="answer", job_id=job, tenant_id=tenant)
    await ledger.record(result(), node="draft", tier="answer", job_id=job, tenant_id=intruder)
    async with fresh_pool.acquire() as conn:
        mine = await job_cost(conn, job, tenant_id=tenant)
        theirs = await job_cost(conn, job, tenant_id=intruder)
        nobody = await job_cost(conn, job, tenant_id=uuid4())
    assert (mine.calls, theirs.calls, nobody.calls) == (1, 1, 0)
    assert mine.cost_usd == call_cost("anthropic", "claude-sonnet-5-5", 1000, 500)
