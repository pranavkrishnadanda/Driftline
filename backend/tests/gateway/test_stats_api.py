"""GET /v1/stats (P5b T4): real aggregates over seeded Postgres rows and the Redis cache
counters, scoped to the caller's tenant."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from dbseed import VersionSeed, seed_history, seed_source
from test_ask_api import asgi_client, settings_for

from driftline.cache.semantic import SemanticCache
from driftline.clock import ManualClock
from driftline.gateway.stats import collect_stats
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.router import LLMRouter, Route

NOW = datetime(2026, 10, 25, 15, 30, tzinfo=UTC)
TODAY = NOW.date()


def at(days_ago: int, hour: int = 12) -> datetime:
    """Noon UTC `days_ago` days before NOW's day."""
    day = TODAY - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


async def seed_corpus(conn, name: str):
    """Two sources (upload, openfda): one document with two versions (3 chunks) and one
    with a single version (1 chunk). Returns (tenant_id, version_ids)."""
    tenant, upload = await seed_source(conn, tenant=name, api_key=f"key-{name}")
    openfda = await conn.fetchval(
        "INSERT INTO sources (tenant_id, kind) VALUES ($1, 'openfda') RETURNING id", tenant
    )
    _, versions, _ = await seed_history(
        conn,
        upload,
        external_id=f"{name}-guide",
        title="Guide",
        versions=[
            VersionSeed(datetime(2024, 1, 1, tzinfo=UTC), [("A", "one"), ("B", "two")]),
            VersionSeed(datetime(2025, 1, 1, tzinfo=UTC), [("A", "one, revised")]),
        ],
    )
    _, [label], _ = await seed_history(
        conn,
        openfda,
        external_id=f"{name}-label",
        title="Label",
        versions=[VersionSeed(datetime(2024, 1, 1, tzinfo=UTC), [("Liver", "Check ALT.")])],
    )
    return tenant, [*versions, label]


async def seed_answer(conn, tenant, *, cost: float, created_at: datetime):
    return await conn.fetchval(
        "INSERT INTO answers (tenant_id, question, as_of, body, cost_usd, created_at) "
        "VALUES ($1, 'q', $2, '{}', $3, $2) RETURNING id",
        tenant,
        created_at,
        cost,
    )


async def seed_drift(conn, tenant, answer, versions, verdict: str, claim: int, created_at):
    await conn.execute(
        "INSERT INTO drift_events (answer_id, tenant_id, old_version_id, new_version_id, "
        "verdict, claim_idx, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        answer,
        tenant,
        versions[0],
        versions[1],
        verdict,
        claim,
        created_at,
    )


async def seed_job(conn, tenant, *, created_at, ms: float | None, status="succeeded", kind="ask"):
    finished = created_at + timedelta(milliseconds=ms) if ms is not None else None
    return await conn.fetchval(
        "INSERT INTO jobs (tenant_id, kind, status, created_at, finished_at) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING id",
        tenant,
        kind,
        status,
        created_at,
        finished,
    )


async def seed_llm_call(conn, tenant, job, cost: float, created_at):
    await conn.execute(
        "INSERT INTO llm_calls (job_id, tenant_id, node, tier, provider, model, input_tokens, "
        "output_tokens, cost_usd, latency_ms, created_at) "
        "VALUES ($1, $2, 'draft', 'answer', 'det', 'det', 10, 5, $3, 12, $4)",
        job,
        tenant,
        cost,
        created_at,
    )


async def seed_review(conn, tenant, kind: str, status: str = "open"):
    await conn.execute(
        "INSERT INTO review_items (kind, ref_id, tenant_id, status) "
        "VALUES ($1, gen_random_uuid(), $2, $3)",
        kind,
        tenant,
        status,
    )


async def seed_everything(conn, name: str):
    """A full tenant. Everything outside the 30-day window must not be counted."""
    tenant, versions = await seed_corpus(conn, name)
    # Answers: two today (0.02 + 0.04), one 3 days ago (0.03), one 40 days ago (ignored).
    a1 = await seed_answer(conn, tenant, cost=0.02, created_at=at(0, 9))
    await seed_answer(conn, tenant, cost=0.04, created_at=at(0, 10))
    await seed_answer(conn, tenant, cost=0.03, created_at=at(3))
    await seed_answer(conn, tenant, cost=9.0, created_at=at(40))
    # Drift: today 2 changed + 1 broken; 2 days ago 1 still_valid; 31 days ago (ignored).
    await seed_drift(conn, tenant, a1, versions, "changed", 0, at(0))
    await seed_drift(conn, tenant, a1, versions, "changed", 1, at(0))
    await seed_drift(conn, tenant, a1, versions, "broken", 2, at(0))
    await seed_drift(conn, tenant, a1, versions, "still_valid", 3, at(2))
    await seed_drift(conn, tenant, a1, versions, "broken", 4, at(31))
    # Ask jobs: today 100/200/300/400 ms; yesterday 1000 ms. A failed ask, a running ask,
    # an old ask and a non-ask job are all left out.
    jobs = []
    for ms in (100, 200, 300, 400):
        jobs.append(await seed_job(conn, tenant, created_at=at(0, 8), ms=ms))
    await seed_job(conn, tenant, created_at=at(1, 8), ms=1000)
    await seed_job(conn, tenant, created_at=at(0, 8), ms=50_000, status="failed")
    await seed_job(conn, tenant, created_at=at(0, 8), ms=None, status="running")
    await seed_job(conn, tenant, created_at=at(45), ms=99_000)
    await seed_job(conn, tenant, created_at=at(0, 8), ms=77_000, kind="ingest")
    # LLM spend: 0.05 + 0.01 in the window, 5.0 outside it.
    await seed_llm_call(conn, tenant, jobs[0], 0.05, at(0))
    await seed_llm_call(conn, tenant, jobs[1], 0.01, at(4))
    await seed_llm_call(conn, tenant, jobs[2], 5.0, at(60))
    # Review backlog: 2 open relations, 1 open broken answer, 1 resolved (ignored).
    await seed_review(conn, tenant, "relation")
    await seed_review(conn, tenant, "relation")
    await seed_review(conn, tenant, "broken_answer")
    await seed_review(conn, tenant, "low_confidence_answer", status="resolved")
    return tenant


def det_cache(redis) -> SemanticCache:
    router = LLMRouter(
        providers={"det": DeterministicAdapter("det")},
        chains={"embed": [Route("det", "hash")]},
        clock=ManualClock(),
    )
    return SemanticCache(redis, router)


async def test_collect_stats_aggregates_only_this_tenants_rows_in_the_window(
    fresh_conn, fresh_pool, redis_client
):
    tenant = await seed_everything(fresh_conn, "pharma")
    other = await seed_everything(fresh_conn, "infra")
    await seed_corpus(fresh_conn, "spare")  # a third tenant's corpus never leaks either
    # Cache: one hit and three misses for this tenant, one miss for the other.
    cache = det_cache(redis_client)
    as_of = datetime(2025, 6, 1, tzinfo=UTC)
    await cache.store(tenant_id=tenant, question="q", as_of=as_of, answer={}, version_ids=[])
    assert await cache.lookup(fresh_conn, tenant_id=tenant, question="q", as_of=as_of)
    for question in ("x", "y", "z"):
        assert not await cache.lookup(fresh_conn, tenant_id=tenant, question=question, as_of=as_of)
    assert not await cache.lookup(fresh_conn, tenant_id=other, question="q", as_of=as_of)
    await fresh_conn.execute(
        "INSERT INTO eval_runs (git_sha, corpus, metrics, created_at) VALUES "
        "('aaaaaaa', 'pharma', $1::jsonb, $2), ('bbbbbbb', 'pharma', $3::jsonb, $4)",
        json.dumps({"faithfulness": 0.5}),
        at(5),
        json.dumps({"faithfulness": 0.91, "citation_precision": 0.88, "note": "text"}),
        at(1),
    )

    stats = await collect_stats(fresh_pool, redis_client, tenant, now=NOW)

    assert stats.window_days == 30
    assert stats.corpus.model_dump() == {
        "documents": 2,
        "versions": 3,
        "chunks": 4,
        "sources": [
            {"kind": "openfda", "count": 1},
            {"kind": "git_docs", "count": 0},
            {"kind": "upload", "count": 1},
        ],
    }

    days = stats.drift.per_day
    assert len(days) == 30 and days[0].day == TODAY - timedelta(days=29) and days[-1].day == TODAY
    assert days[-1].model_dump() == {
        "day": TODAY,
        "still_valid": 0,
        "changed": 2,
        "broken": 1,
        "total": 3,
    }
    assert days[-3].still_valid == 1 and days[-3].total == 1
    assert sum(d.total for d in days) == 4 == stats.drift.total

    asks = stats.asks
    assert asks.latency.samples == 5
    # percentile_cont over [100, 200, 300, 400, 1000]
    assert asks.latency.p50_ms == pytest.approx(300)
    assert asks.latency.p95_ms == pytest.approx(880)
    assert len(asks.per_day) == 30
    today, yesterday = asks.per_day[-1], asks.per_day[-2]
    assert today.asks == 4 and today.p50_ms == pytest.approx(250)
    assert today.p95_ms == pytest.approx(385)
    assert yesterday.asks == 1 and yesterday.p50_ms == pytest.approx(1000)
    assert asks.per_day[0].asks == 0 and asks.per_day[0].p50_ms is None

    cost = stats.cost
    assert cost.answers == 3
    assert cost.answers_cost_usd == pytest.approx(0.09)
    assert cost.per_answer_usd == pytest.approx(0.03)
    assert cost.llm_calls == 2 and cost.llm_cost_usd == pytest.approx(0.06)
    assert cost.per_day[-1].answers == 2
    assert cost.per_day[-1].per_answer_usd == pytest.approx(0.03)
    assert cost.per_day[-4].per_answer_usd == pytest.approx(0.03)
    assert cost.per_day[-2].answers == 0 and cost.per_day[-2].per_answer_usd is None

    assert stats.cache.model_dump() == {
        "hits": 1,
        "misses": 3,
        "hit_rate": 0.25,
        "reason": None,
    }

    assert [b.model_dump() for b in stats.review_backlog] == [
        {"kind": "relation", "open": 2},
        {"kind": "broken_answer", "open": 1},
        {"kind": "low_confidence_answer", "open": 0},
        {"kind": "answer", "open": 0},
    ]

    assert stats.latest_eval is not None
    assert stats.latest_eval.git_sha == "bbbbbbb" and stats.latest_eval.corpus == "pharma"
    assert stats.latest_eval.metrics == {"citation_precision": 0.88, "faithfulness": 0.91}


async def test_an_empty_tenant_gets_zeros_and_nulls_never_made_up_numbers(
    fresh_conn, fresh_pool, redis_client
):
    tenant, _ = await seed_source(fresh_conn, tenant="empty", api_key="key-empty")
    stats = await collect_stats(fresh_pool, redis_client, tenant, now=NOW)
    assert stats.corpus.documents == stats.corpus.versions == stats.corpus.chunks == 0
    assert stats.drift.total == 0 and all(d.total == 0 for d in stats.drift.per_day)
    assert stats.asks.latency.model_dump() == {"p50_ms": None, "p95_ms": None, "samples": 0}
    assert stats.cost.per_answer_usd is None and stats.cost.answers == 0
    assert stats.cache.hit_rate is None and stats.cache.reason == "no_lookups"
    assert all(b.open == 0 for b in stats.review_backlog)
    assert stats.latest_eval is None


async def test_stats_route_is_tenant_scoped(fresh_dsn, redis_url, fresh_conn):
    tenant = await seed_everything(fresh_conn, "pharma")
    await seed_everything(fresh_conn, "infra")
    # Rows relative to the real clock, so the route's own `now` sees them today.
    real_now = datetime.now(UTC)
    await seed_answer(fresh_conn, tenant, cost=0.5, created_at=real_now)
    await seed_job(fresh_conn, tenant, created_at=real_now - timedelta(seconds=2), ms=1500)
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.get("/v1/stats", params={"tenant": "pharma"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tenant"] == "pharma"
        assert body["corpus"]["documents"] == 2
        assert date.fromisoformat(body["drift"]["per_day"][-1]["day"]) == real_now.date()
        assert body["asks"]["per_day"][-1]["asks"] >= 1
        assert body["cost"]["answers"] >= 1
        assert body["cache"] == {"hits": 0, "misses": 0, "hit_rate": None, "reason": "no_lookups"}
        assert body["latest_eval"] is None

        with_key = await client.get("/v1/stats", headers={"Authorization": "Bearer key-infra"})
        assert with_key.status_code == 200 and with_key.json()["tenant"] == "infra"

        assert (await client.get("/v1/stats")).status_code == 401
        assert (await client.get("/v1/stats", params={"tenant": "nobody"})).status_code == 404
        mismatch = await client.get(
            "/v1/stats", params={"tenant": "pharma"}, headers={"Authorization": "Bearer key-infra"}
        )
        assert mismatch.status_code == 403
