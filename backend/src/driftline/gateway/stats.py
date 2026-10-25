"""System stats for the `/stats` view (spec sections 9 and 11): `GET /v1/stats`.

Every number is a real aggregate over the caller's tenant (`require_tenant`), never an
estimate. Time series cover the last `WINDOW_DAYS` UTC days, today included, with one
entry per day (zero or null on days with no rows):

- corpus size: documents, versions, chunks, and sources by kind (all time);
- drift events per day by verdict;
- ask latency p50/p95 (job `finished_at - created_at` of succeeded asks) and asks
  finished per day;
- cost per answer (`answers.cost_usd`) and total LLM spend (`llm_calls.cost_usd`);
- the semantic cache hit rate, from the per-tenant counters `SemanticCache.lookup` keeps
  in Redis (all time; null with a reason when there have been no lookups);
- the open review backlog by kind;
- the latest eval run's numeric metrics. Eval runs are not per tenant (they score the
  system on a golden corpus), so every tenant sees the same latest run.
"""

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, get_args
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

from driftline.agents.events import DriftVerdict
from driftline.agents.schemas import SourceKind
from driftline.auth import TenantRow
from driftline.cache.semantic import lookup_counts
from driftline.gateway.auth import AUTH_RESPONSES, CallerTenant
from driftline.review.queue import ReviewKind

WINDOW_DAYS = 30

CORPUS = """
SELECT
  (SELECT count(*) FROM documents d JOIN sources s ON s.id = d.source_id
    WHERE s.tenant_id = $1) AS documents,
  (SELECT count(*) FROM doc_versions v JOIN documents d ON d.id = v.document_id
    JOIN sources s ON s.id = d.source_id WHERE s.tenant_id = $1) AS versions,
  (SELECT count(*) FROM chunks c JOIN doc_versions v ON v.id = c.version_id
    JOIN documents d ON d.id = v.document_id JOIN sources s ON s.id = d.source_id
    WHERE s.tenant_id = $1) AS chunks
"""
SOURCES = "SELECT kind, count(*) AS n FROM sources WHERE tenant_id = $1 GROUP BY kind"
DRIFT = """
SELECT (created_at AT TIME ZONE 'UTC')::date AS day, verdict, count(*) AS n
FROM drift_events WHERE tenant_id = $1 AND created_at >= $2 AND created_at < $3
GROUP BY 1, 2
"""
# Latency of a finished ask, in ms, bucketed by the day it finished.
_ASKS = """
FROM (
  SELECT (finished_at AT TIME ZONE 'UTC')::date AS day,
         extract(epoch FROM finished_at - created_at) * 1000 AS ms
  FROM jobs
  WHERE tenant_id = $1 AND kind = 'ask' AND status = 'succeeded'
    AND finished_at >= $2 AND finished_at < $3
) asks
"""
_PERCENTILES = (
    "count(*) AS n, "
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS p50, "
    "percentile_cont(0.95) WITHIN GROUP (ORDER BY ms) AS p95 "
)
ASKS_PER_DAY = f"SELECT day, {_PERCENTILES}{_ASKS} GROUP BY day"
ASKS_TOTAL = f"SELECT {_PERCENTILES}{_ASKS}"
ANSWERS_PER_DAY = """
SELECT (created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS n, sum(cost_usd) AS usd
FROM answers WHERE tenant_id = $1 AND created_at >= $2 AND created_at < $3
GROUP BY 1
"""
LLM_SPEND = """
SELECT count(*) AS n, coalesce(sum(cost_usd), 0) AS usd FROM llm_calls
WHERE tenant_id = $1 AND created_at >= $2 AND created_at < $3
"""
BACKLOG = """
SELECT kind, count(*) AS n FROM review_items
WHERE tenant_id = $1 AND status = 'open' GROUP BY kind
"""
LATEST_EVAL = """
SELECT git_sha, corpus, metrics, created_at FROM eval_runs
ORDER BY created_at DESC, id LIMIT 1
"""


class KindCount(BaseModel):
    kind: SourceKind
    count: int


class CorpusStats(BaseModel):
    documents: int
    versions: int
    chunks: int
    sources: list[KindCount] = Field(description="every source kind, zero when absent")


class DriftDay(BaseModel):
    day: date
    still_valid: int
    changed: int
    broken: int
    total: int


class DriftStats(BaseModel):
    total: int
    per_day: list[DriftDay]


class Latency(BaseModel):
    p50_ms: float | None
    p95_ms: float | None
    samples: int = Field(description="succeeded asks the percentiles are over")


class AskDay(BaseModel):
    day: date
    asks: int = Field(description="asks that succeeded this day")
    p50_ms: float | None
    p95_ms: float | None


class AskStats(BaseModel):
    latency: Latency
    per_day: list[AskDay]


class CostDay(BaseModel):
    day: date
    answers: int
    per_answer_usd: float | None


class CostStats(BaseModel):
    answers: int
    answers_cost_usd: float
    per_answer_usd: float | None = Field(description="null when there were no answers")
    llm_calls: int
    llm_cost_usd: float = Field(description="every LLM call, answers and drift checks alike")
    per_day: list[CostDay]


class CacheStats(BaseModel):
    hits: int
    misses: int
    hit_rate: float | None
    reason: str | None = Field(
        description="why hit_rate is null: `no_lookups` or `redis_unavailable`"
    )


class ReviewBacklog(BaseModel):
    kind: ReviewKind
    open: int


class EvalSummary(BaseModel):
    git_sha: str
    corpus: str
    created_at: datetime
    metrics: dict[str, float]


class Stats(BaseModel):
    tenant: str
    generated_at: datetime
    window_days: int
    corpus: CorpusStats
    drift: DriftStats
    asks: AskStats
    cost: CostStats
    cache: CacheStats
    review_backlog: list[ReviewBacklog]
    latest_eval: EvalSummary | None


def _days(today: date) -> list[date]:
    return [today - timedelta(days=n) for n in range(WINDOW_DAYS - 1, -1, -1)]


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _numeric_metrics(raw: Any) -> dict[str, float]:
    metrics = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(metrics, dict):
        return {}
    return {
        str(k): float(v)
        for k, v in sorted(metrics.items())
        if isinstance(v, int | float) and not isinstance(v, bool)
    }


async def _cache_stats(redis: Redis, tenant_id: UUID) -> CacheStats:
    try:
        hits, misses = await lookup_counts(redis, tenant_id)
    except RedisError:
        return CacheStats(hits=0, misses=0, hit_rate=None, reason="redis_unavailable")
    lookups = hits + misses
    if not lookups:
        return CacheStats(hits=0, misses=0, hit_rate=None, reason="no_lookups")
    return CacheStats(hits=hits, misses=misses, hit_rate=hits / lookups, reason=None)


async def collect_stats(
    pool: asyncpg.Pool,
    redis: Redis,
    tenant_id: UUID,
    *,
    now: datetime,
    tenant_name: str = "",
) -> Stats:
    """Every `/stats` aggregate for one tenant, with the window ending on `now`'s UTC day."""
    today = now.astimezone(UTC).date()
    days = _days(today)
    start = datetime.combine(days[0], time(), tzinfo=UTC)
    end = datetime.combine(today + timedelta(days=1), time(), tzinfo=UTC)
    window = (tenant_id, start, end)

    async with pool.acquire() as conn:
        corpus = await conn.fetchrow(CORPUS, tenant_id)
        sources = {r["kind"]: r["n"] for r in await conn.fetch(SOURCES, tenant_id)}
        drift_rows = await conn.fetch(DRIFT, *window)
        ask_rows = {r["day"]: r for r in await conn.fetch(ASKS_PER_DAY, *window)}
        ask_total = await conn.fetchrow(ASKS_TOTAL, *window)
        answer_rows = {r["day"]: r for r in await conn.fetch(ANSWERS_PER_DAY, *window)}
        llm = await conn.fetchrow(LLM_SPEND, *window)
        backlog = {r["kind"]: r["n"] for r in await conn.fetch(BACKLOG, tenant_id)}
        latest = await conn.fetchrow(LATEST_EVAL)

    drift: dict[date, dict[str, int]] = {d: dict.fromkeys(get_args(DriftVerdict), 0) for d in days}
    for row in drift_rows:
        drift[row["day"]][row["verdict"]] = row["n"]
    drift_days = [DriftDay(day=d, total=sum(v.values()), **v) for d, v in drift.items()]

    ask_days = []
    for d in days:
        row = ask_rows.get(d)
        ask_days.append(
            AskDay(
                day=d,
                asks=row["n"] if row else 0,
                p50_ms=_float(row["p50"]) if row else None,
                p95_ms=_float(row["p95"]) if row else None,
            )
        )

    answers = sum(r["n"] for r in answer_rows.values())
    answers_usd = sum(float(r["usd"]) for r in answer_rows.values())
    cost_days = [
        CostDay(
            day=d,
            answers=answer_rows[d]["n"] if d in answer_rows else 0,
            per_answer_usd=float(answer_rows[d]["usd"]) / answer_rows[d]["n"]
            if d in answer_rows
            else None,
        )
        for d in days
    ]

    return Stats(
        tenant=tenant_name,
        generated_at=now,
        window_days=WINDOW_DAYS,
        corpus=CorpusStats(
            documents=corpus["documents"],
            versions=corpus["versions"],
            chunks=corpus["chunks"],
            sources=[KindCount(kind=k, count=sources.get(k, 0)) for k in get_args(SourceKind)],
        ),
        drift=DriftStats(total=sum(d.total for d in drift_days), per_day=drift_days),
        asks=AskStats(
            latency=Latency(
                p50_ms=_float(ask_total["p50"]),
                p95_ms=_float(ask_total["p95"]),
                samples=ask_total["n"],
            ),
            per_day=ask_days,
        ),
        cost=CostStats(
            answers=answers,
            answers_cost_usd=answers_usd,
            per_answer_usd=answers_usd / answers if answers else None,
            llm_calls=llm["n"],
            llm_cost_usd=float(llm["usd"]),
            per_day=cost_days,
        ),
        cache=await _cache_stats(redis, tenant_id),
        review_backlog=[
            ReviewBacklog(kind=k, open=backlog.get(k, 0)) for k in get_args(ReviewKind)
        ],
        latest_eval=EvalSummary(
            git_sha=latest["git_sha"],
            corpus=latest["corpus"],
            created_at=latest["created_at"],
            metrics=_numeric_metrics(latest["metrics"]),
        )
        if latest
        else None,
    )


def build_stats_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["stats"])

    @router.get(
        "/stats",
        response_model=Stats,
        responses={**AUTH_RESPONSES, 404: {"description": "unknown tenant"}},
    )
    async def stats(request: Request, caller: TenantRow = CallerTenant) -> Stats:
        """Corpus size, drift, ask latency and throughput, cost, cache hit rate, review
        backlog and the latest eval metrics for the caller's tenant (last 30 UTC days)."""
        state = request.app.state
        return await collect_stats(
            state.pg, state.redis, caller.id, now=datetime.now(UTC), tenant_name=caller.name
        )

    return router
