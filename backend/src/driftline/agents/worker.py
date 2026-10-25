"""Agent worker: consumes the `agent` stream, runs the answer graph, publishes events and
persists the answer. Idempotent on job_id; a crashed run resumes from its checkpoint."""

import asyncio
import json
from typing import Any
from uuid import UUID

import asyncpg
from pydantic import BaseModel
from redis.asyncio import Redis

from driftline.agents.eventlog import AskEventLog
from driftline.agents.events import ErrorEvent, FinalEvent
from driftline.agents.graph import run_ask
from driftline.agents.schemas import AGENT_GROUP, AGENT_STREAM, AnswerSchema, AskJob
from driftline.clock import Clock, SystemClock
from driftline.llm.router import AllRoutesFailed
from driftline.obs.cost import job_cost
from driftline.streams.bus import StreamBus

RECLAIM_IDLE_MS = 60_000  # spec section 3: reclaim stalled messages after 60 s
MAX_DELIVERIES = 3  # StreamBus's default: the 3rd failed delivery is dead-lettered
REAP_INTERVAL_S = 60.0
# Stream entry ids are Redis-clock milliseconds and created_at is the Postgres clock:
# start the scan for a job's entry this far before its created_at to absorb skew.
REAP_SCAN_SLACK_MS = 5 * 60_000
REAP_SCAN_PAGE = 500


async def persist_answer(
    conn: asyncpg.Connection, job: AskJob, answer: AnswerSchema
) -> AnswerSchema:
    """Write the answer, its citations and the job's cost, and mark the job succeeded.
    One answer row per job: a rerun (redelivery, two workers) reuses the existing row."""
    cost = await job_cost(conn, job.job_id, tenant_id=job.tenant_id)
    answer = answer.model_copy(update={"cost_usd": float(cost.cost_usd)})
    async with conn.transaction():
        answer_id = await conn.fetchval(
            "INSERT INTO answers (tenant_id, question, as_of, body, confidence, job_id, "
            "status, degraded, cost_usd) VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9) "
            "ON CONFLICT (job_id) WHERE job_id IS NOT NULL DO NOTHING RETURNING id",
            job.tenant_id,
            job.question,
            answer.as_of,
            answer.model_dump_json(exclude={"answer_id"}),
            answer.confidence,
            job.job_id,
            answer.status,
            answer.degraded,
            cost.cost_usd,
        )
        if answer_id is None:  # already persisted by an earlier delivery
            answer_id = await conn.fetchval(
                "SELECT id FROM answers WHERE job_id = $1 AND tenant_id = $2",
                job.job_id,
                job.tenant_id,
            )
        else:
            await conn.executemany(
                "INSERT INTO answer_citations (answer_id, claim_idx, chunk_id) "
                "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                [(answer_id, c.idx, cit.chunk_id) for c in answer.claims for cit in c.citations],
            )
        await conn.execute(
            "UPDATE jobs SET status = 'succeeded', error = NULL, finished_at = now() "
            "WHERE id = $1 AND tenant_id = $2",
            job.job_id,
            job.tenant_id,
        )
    return answer.model_copy(update={"answer_id": answer_id})


async def _published_job_ids(redis: Redis, start_ms: int, wanted: set[str]) -> set[str]:
    """Job ids among `wanted` that have an entry on the agent stream from `start_ms` on."""
    found: set[str] = set()
    start = f"{max(start_ms, 0)}-0"
    while found != wanted:
        entries = await redis.xrange(AGENT_STREAM, min=start, max="+", count=REAP_SCAN_PAGE)
        for _, fields in entries:
            try:
                job_id = str(json.loads(fields["data"])["job_id"])
            except (KeyError, TypeError, ValueError):
                continue  # not an ask payload; nothing to match
            if job_id in wanted:
                found.add(job_id)
        if len(entries) < REAP_SCAN_PAGE:
            break
        start = f"({entries[-1][0]}"  # exclusive: resume after the last entry seen
    return found


async def reap_lost_asks(
    pool: asyncpg.Pool, redis: Redis, events: AskEventLog, *, now: float, timeout_s: float
) -> list[UUID]:
    """Fail asks still `queued` after `timeout_s` that never reached the agent stream (the
    gateway inserted the job, then its publish failed). Their clients get a terminal
    `enqueue_lost` error instead of waiting forever. Returns the reaped job ids."""
    async with pool.acquire() as conn:
        stale = await conn.fetch(
            "SELECT id, created_at FROM jobs WHERE kind = 'ask' AND status = 'queued' "
            "AND created_at < to_timestamp($1) ORDER BY created_at",
            now - timeout_s,
        )
    if not stale:
        return []
    start_ms = int(stale[0]["created_at"].timestamp() * 1000) - REAP_SCAN_SLACK_MS
    published = await _published_job_ids(redis, start_ms, {str(r["id"]) for r in stale})
    lost = [r["id"] for r in stale if str(r["id"]) not in published]
    if not lost:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "UPDATE jobs SET status = 'failed', error = 'enqueue_lost', finished_at = now() "
            "WHERE id = ANY($1::uuid[]) AND status = 'queued' RETURNING id",
            lost,
        )
    reaped = {r["id"] for r in rows}
    for job_id in lost:
        if job_id in reaped:
            await events.append(
                job_id,
                ErrorEvent(
                    code="enqueue_lost",
                    retryable=False,
                    message="the ask was never queued for a worker; please ask again",
                ),
            )
    return [job_id for job_id in lost if job_id in reaped]


class AgentWorker:
    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        redis: Redis,
        bus: StreamBus,
        events: AskEventLog,
        graph,
        consumer: str,
        clock: Clock | None = None,
        queue_timeout_s: float = 300.0,
        reap_interval_s: float = REAP_INTERVAL_S,
        reclaim_idle_ms: int = RECLAIM_IDLE_MS,
        max_deliveries: int = MAX_DELIVERIES,
    ) -> None:
        self._pool = pool
        self._redis = redis
        self._bus = bus
        self._events = events
        self._graph = graph
        self._consumer = consumer
        self._clock = clock or SystemClock()
        self._queue_timeout_s = queue_timeout_s
        self._reap_interval_s = reap_interval_s
        self._reclaim_idle_ms = reclaim_idle_ms
        self._max_deliveries = max_deliveries  # must match the bus's, see _is_last_delivery
        self._next_reap: float | None = None

    async def setup(self) -> None:
        await self._bus.ensure_group(AGENT_STREAM, AGENT_GROUP)

    async def _emit(self, job: AskJob, event: BaseModel) -> None:
        await self._events.append(job.job_id, event)

    async def _fail(self, job: AskJob, error: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'failed', error = $3, finished_at = now() "
                "WHERE id = $1 AND tenant_id = $2",
                job.job_id,
                job.tenant_id,
                error,
            )

    async def _is_last_delivery(self, msg_id: str) -> bool:
        """True when the bus will dead-letter this message if the handler fails now."""
        info = await self._redis.xpending_range(
            AGENT_STREAM, AGENT_GROUP, min=msg_id, max=msg_id, count=1
        )
        return bool(info) and int(info[0]["times_delivered"]) >= self._max_deliveries

    async def handle_ask(self, msg_id: str, payload: dict[str, Any]) -> None:
        job = AskJob.model_validate(payload)
        async with self._pool.acquire() as conn:
            status = await conn.fetchval(
                "SELECT status FROM jobs WHERE id = $1 AND tenant_id = $2 AND kind = 'ask'",
                job.job_id,
                job.tenant_id,
            )
            if status is None:
                # Unknown job, or a payload naming another tenant: never run it. Raising
                # retries it and then dead-letters it for inspection.
                raise LookupError(f"no ask job {job.job_id} for tenant {job.tenant_id}")
            if status in ("succeeded", "failed"):
                return  # redelivered after completion
            await conn.execute(
                "UPDATE jobs SET status = 'running' WHERE id = $1 AND status = 'queued'",
                job.job_id,
            )

        async def emit(event: BaseModel) -> None:
            await self._emit(job, event)

        try:
            answer = await run_ask(self._graph, job, emit=emit, clock=self._clock)
            async with self._pool.acquire() as conn:
                answer = await persist_answer(conn, job, answer)
        except AllRoutesFailed:
            # Every model route is down: a terminal, explained failure (spec section 10).
            await self._fail(job, "llm_unavailable")
            await emit(
                ErrorEvent(
                    code="llm_unavailable",
                    retryable=False,
                    message="no language model is reachable right now; please try again later",
                )
            )
            return
        except Exception as exc:
            # Unknown failure: the message stays pending, and the next delivery resumes from
            # the checkpoint. On the last delivery the bus dead-letters it, so fail the job
            # and end the client's stream instead of leaving it waiting.
            last = await self._is_last_delivery(msg_id)
            if last:
                await self._fail(job, "internal")
            await emit(ErrorEvent(code="internal", retryable=not last, message=type(exc).__name__))
            raise
        await emit(FinalEvent(answer=answer))

    async def maybe_reap(self) -> list[UUID] | None:
        """Reap lost asks when a pass is due (at once, then every `reap_interval_s`);
        returns the reaped ids, or None when no pass was due."""
        now = self._clock.now()
        if self._next_reap is not None and now < self._next_reap:
            return None
        self._next_reap = now + self._reap_interval_s
        return await reap_lost_asks(
            self._pool, self._redis, self._events, now=now, timeout_s=self._queue_timeout_s
        )

    async def run_once(self, *, block_ms: int = 100) -> int:
        """One read plus one reclaim pass; returns messages processed."""
        result = await self._bus.consume_once(
            AGENT_STREAM, AGENT_GROUP, self._consumer, self.handle_ask, count=1, block_ms=block_ms
        )
        reclaimed = await self._bus.reclaim_once(
            AGENT_STREAM,
            AGENT_GROUP,
            self._consumer,
            self.handle_ask,
            min_idle_ms=self._reclaim_idle_ms,
            count=1,
        )
        return result.processed + reclaimed.processed

    async def run(self, stop: asyncio.Event) -> None:
        await self.setup()
        while not stop.is_set():
            await self.maybe_reap()
            if await self.run_once(block_ms=1000) == 0:
                await self._clock.sleep(0.05)
