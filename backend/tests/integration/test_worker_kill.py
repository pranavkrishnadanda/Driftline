"""Worker crash mid-job loses nothing (spec section 3 "Distributed-processing guarantees",
section 10 "Worker crash mid-job"; P7 review focus 4).

Real Postgres (+ LangGraph Postgres checkpointer), real Redis Streams, the TEI embedder,
and the DeterministicAdapter (product code) as the LLM. No mocks.

A worker is "killed" by cancelling its asyncio task while it is inside a handler: the
handler never returns, so the message is never acked and stays pending on the dead
consumer, exactly like a process that died. Another worker's XAUTOCLAIM then takes it.

The reclaim threshold is Redis's own idle time for a pending entry (server clock), so no
`ManualClock` can advance it: the tests use a short real threshold (about a second)
instead of the production 60 s, and wait it out in real time.
"""

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import pytest
from dbseed import (
    EMBED_MODEL,
    VersionSeed,
    embed_all,
    seed_history,
    seed_source,
    seed_watched_answer,
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from driftline.agents.eventlog import AskEventLog
from driftline.agents.events import ErrorEvent, FinalEvent, StepEvent
from driftline.agents.graph import AgentDeps, build_answer_graph
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.agents.schemas import AGENT_GROUP, AGENT_STREAM, AskJob
from driftline.agents.worker import AgentWorker
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.drift.alerts import AlertLog
from driftline.drift.engine import DriftEngine
from driftline.drift.worker import DRIFT_GROUP, DRIFT_STREAM, DriftWorker
from driftline.ingest.chunker import chunk_sections
from driftline.ingest.connectors.upload import UploadConnector
from driftline.ingest.embed import EmbedStage
from driftline.ingest.outbox import OutboxRelay
from driftline.ingest.store import upsert_version
from driftline.ingest.types import RawDocument, Section
from driftline.ingest.worker import (
    INGEST_GROUP,
    INGEST_STREAM,
    IngestWorker,
    enqueue_ingest,
    ensure_source,
)
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.streams.bus import StreamBus

NOW = datetime(2026, 10, 25, tzinfo=UTC)
RULE = "Check ALT monthly during therapy."
N_ASKS = 10
RECLAIM_IDLE_MS = 1_500  # keepalive refreshes a live claim every 500 ms
LLM_LATENCY_MS = 400  # each LLM call sleeps for real, so a kill lands mid-graph
DEADLINE_S = 150


async def wait_until(predicate: Callable[[], Awaitable[bool]], what: str, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out after {timeout_s}s waiting for {what}")


async def kill(task: asyncio.Task) -> None:
    """Cancel a worker task mid-handler; it must die without returning (no ack)."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled(), "the worker finished its handler before the kill landed"


async def loop(worker, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await worker.run_once(block_ms=100)


# --- agent worker ---------------------------------------------------------------------


@pytest.fixture
async def pool(fresh_dsn):
    p = await asyncpg.create_pool(fresh_dsn, min_size=2, max_size=12)
    yield p
    await p.close()


@pytest.fixture
async def stack():
    async with AsyncExitStack() as s:
        yield s


async def agent_worker(stack, pool, redis, dsn, embedder_url, *, consumer: str):
    """One worker "process": its own checkpointer connection, LLM adapter and graph."""
    saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(dsn))
    await saver.setup()
    det = DeterministicAdapter("det", responder=ExtractiveResponder(), latency_ms=LLM_LATENCY_MS)
    tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
    router = LLMRouter(
        providers={"det": det, "tei": TEIEmbeddingAdapter(embedder_url)},
        chains={**tiers, "embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    deps = AgentDeps(
        pool=pool,
        llm=AgentLLM(router, ledger=CostLedger(pool)),
        retriever=HybridRetriever(pool, router, embed_model=EMBED_MODEL),
        reranker=TEIReranker(None),
        clock=ManualClock(NOW.timestamp()),
    )
    worker = AgentWorker(
        pool=pool,
        redis=redis,
        bus=StreamBus(redis),
        events=AskEventLog(redis),
        graph=build_answer_graph(deps).compile(checkpointer=saver),
        consumer=consumer,
        clock=ManualClock(NOW.timestamp()),
        reclaim_idle_ms=RECLAIM_IDLE_MS,
    )
    await worker.setup()
    return worker, det


async def pending_job_of(redis, consumer: str) -> UUID | None:
    """The job a consumer currently holds (pending, not acked), if any."""
    rows = await redis.xpending_range(
        AGENT_STREAM, AGENT_GROUP, min="-", max="+", count=10, consumername=consumer
    )
    if not rows:
        return None
    entry = await redis.xrange(AGENT_STREAM, min=rows[0]["message_id"], max=rows[0]["message_id"])
    return UUID(json.loads(entry[0][1]["data"])["job_id"])


async def llm_nodes(pool, job_id: UUID) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT node FROM llm_calls WHERE job_id = $1 ORDER BY created_at", job_id
        )
    return [r["node"] for r in rows]


async def test_killed_agent_worker_loses_no_ask_and_resumes_from_checkpoint(
    pool, fresh_dsn, redis_client, embedder_url, stack
):
    async with pool.acquire() as conn:
        tenant, source = await seed_source(conn, kind="openfda")
        await seed_history(
            conn,
            source,
            external_id="lipitor",
            title="Lipitor label",
            versions=[VersionSeed(datetime(2024, 4, 15, tzinfo=UTC), [("Liver", RULE)])],
        )
        await embed_all(conn, embedder_url)
    a, det_a = await agent_worker(stack, pool, redis_client, fresh_dsn, embedder_url, consumer="A")
    b, _ = await agent_worker(stack, pool, redis_client, fresh_dsn, embedder_url, consumer="B")

    bus, events = StreamBus(redis_client), AskEventLog(redis_client)
    jobs: list[UUID] = []
    for i in range(N_ASKS):
        async with pool.acquire() as conn:
            job_id = await conn.fetchval(
                "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ask') RETURNING id", tenant
            )
        job = AskJob(
            job_id=job_id,
            tenant_id=tenant,
            question=f"How often should ALT be checked? (ask {i})",
            as_of=datetime(2024, 6, 1, tzinfo=UTC),
        )
        await bus.publish(AGENT_STREAM, job.model_dump(mode="json"))
        jobs.append(job_id)

    stop = asyncio.Event()
    task_a = asyncio.create_task(loop(a, stop))
    task_b = asyncio.create_task(loop(b, stop))
    killed: list[UUID] = []

    async def a_is_drafting() -> bool:
        # The plan node finished (checkpointed) and A is inside the slow draft LLM call.
        job_id = await pending_job_of(redis_client, "A")
        if job_id is None:
            return False
        evs = [e for _, e in await events.read(job_id, count=1000)]
        drafting = any(
            isinstance(e, StepEvent) and e.node == "draft" and e.status == "started" for e in evs
        )
        if drafting and not any(isinstance(e, FinalEvent) for e in evs):
            killed.append(job_id)
            return True
        return False

    try:
        await wait_until(a_is_drafting, "worker A to be mid-draft on an ask", 60)
        calls_before_kill = await llm_nodes(pool, killed[0])
        await kill(task_a)
        pending_a = await redis_client.xpending_range(
            AGENT_STREAM, AGENT_GROUP, min="-", max="+", count=10, consumername="A"
        )
        assert len(pending_a) == 1, "the killed worker's message must stay pending (unacked)"

        async def all_finished() -> bool:
            async with pool.acquire() as conn:
                left = await conn.fetchval(
                    "SELECT count(*) FROM jobs WHERE id = ANY($1::uuid[]) "
                    "AND status NOT IN ('succeeded', 'failed')",
                    jobs,
                )
            return left == 0

        await wait_until(all_finished, "worker B to finish every ask", DEADLINE_S)
    finally:
        stop.set()
        if not task_a.done():
            task_a.cancel()
        await asyncio.gather(task_a, task_b, return_exceptions=True)

    async with pool.acquire() as conn:
        statuses = await conn.fetch(
            "SELECT status, count(*) AS n FROM jobs WHERE id = ANY($1::uuid[]) GROUP BY status",
            jobs,
        )
        answers = await conn.fetch(
            "SELECT job_id, count(*) AS n FROM answers WHERE job_id = ANY($1::uuid[]) "
            "GROUP BY job_id",
            jobs,
        )
        stuck = await conn.fetchval(
            "SELECT count(*) FROM jobs WHERE status IN ('running', 'queued')"
        )
    assert {r["status"]: r["n"] for r in statuses} == {"succeeded": N_ASKS}
    assert stuck == 0
    assert {r["job_id"]: r["n"] for r in answers} == {j: 1 for j in jobs}  # once per job

    for job_id in jobs:
        evs = [e for _, e in await events.read(job_id, count=1000)]
        finals = [e for e in evs if isinstance(e, FinalEvent)]
        assert len(finals) == 1, f"job {job_id}: {len(finals)} final events"
        assert isinstance(evs[-1], FinalEvent), f"job {job_id}: final is not the last event"
        assert not [e for e in evs if isinstance(e, ErrorEvent)], f"job {job_id} saw an error"

    assert (await redis_client.xpending(AGENT_STREAM, AGENT_GROUP))["pending"] == 0
    assert await redis_client.xlen(f"dlq:{AGENT_STREAM}") == 0

    # Resume from the Postgres checkpoint, observable in the per-job LLM call ledger:
    # an ask that ran start to finish calls `plan` once and `draft` once. The killed ask
    # had finished `plan` on A (that row was written before the kill) and was cancelled
    # inside `draft`. B resumed from the checkpoint after `plan`: had it started over,
    # `plan` would appear twice.
    victim = killed[0]
    assert calls_before_kill == ["plan"], calls_before_kill
    assert "det-answer" in det_a.calls  # A had started the draft call when it was killed
    victim_nodes = await llm_nodes(pool, victim)
    assert victim_nodes.count("plan") == 1, f"plan re-ran after the reclaim: {victim_nodes}"
    assert victim_nodes.count("draft") == 1, victim_nodes
    clean = await llm_nodes(pool, next(j for j in jobs if j != victim))
    assert victim_nodes == clean


# --- ingest worker --------------------------------------------------------------------


async def test_killed_ingest_worker_loses_no_ingest_job(pool, fresh_dsn, redis_client, tmp_path):
    """Ingest's reclaim threshold is a module constant (60 s), not injectable: worker B
    reclaims through its real bus and real handler with a short threshold instead of
    waiting a minute. A is killed while blocked on its first job's row (a lock held by
    the test), with the rest of its batch also unacked."""
    for i in range(3):
        (tmp_path / f"doc{i}.md").write_text(f"# Doc {i}\n\n## Body\n\nRollout step {i}.\n")
    async with pool.acquire() as conn:
        source = await ensure_source(
            conn, tenant="demo", kind="upload", config={"root": str(tmp_path)}
        )

    def make(consumer: str) -> IngestWorker:
        det = DeterministicAdapter("det")
        router = LLMRouter(
            providers={"det": det},
            chains={"embed": [Route("det", "det-embed")], "extract": [Route("det", "det-x")]},
            clock=ManualClock(),
        )
        return IngestWorker(
            pool=pool,
            bus=StreamBus(redis_client),
            redis=redis_client,
            connector_factory=lambda kind, config: UploadConnector(config["root"]),
            embed_stage=EmbedStage(router, model_name="det-embed"),
            extractor=None,
            consumer=consumer,
            clock=ManualClock(),
        )

    a, b = make("A"), make("B")
    await a.setup()
    bus = StreamBus(redis_client)
    jobs = [
        await enqueue_ingest(pool, bus, source_id=source, external_id=f"doc{i}.md")
        for i in range(3)
    ]

    blocker = await asyncpg.connect(fresh_dsn)
    tx = blocker.transaction()
    await tx.start()
    await blocker.execute("SELECT 1 FROM jobs WHERE id = $1 FOR UPDATE", jobs[0])
    task_a = asyncio.create_task(a.run_once(block_ms=100))
    try:

        async def a_is_blocked() -> bool:
            return bool(
                await blocker.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                    "AND datname = current_database()"
                )
            )

        await wait_until(a_is_blocked, "worker A to be inside its first ingest job", 30)
        await kill(task_a)
    finally:
        await tx.rollback()
        await blocker.close()
    assert (await redis_client.xpending(INGEST_STREAM, INGEST_GROUP))["pending"] == 3

    reclaim_ms = 300
    await asyncio.sleep(reclaim_ms / 1000 + 0.2)
    result = await bus.reclaim_once(
        INGEST_STREAM, INGEST_GROUP, "B", b.handle_ingest, min_idle_ms=reclaim_ms
    )
    assert result.processed == 3

    async with pool.acquire() as conn:
        statuses = [
            r["status"]
            for r in await conn.fetch("SELECT status FROM jobs WHERE id = ANY($1::uuid[])", jobs)
        ]
        versions = await conn.fetchval(
            "SELECT count(*) FROM doc_versions v JOIN documents d ON d.id = v.document_id "
            "WHERE d.source_id = $1",
            source,
        )
    assert statuses == ["succeeded"] * 3
    assert versions == 3  # one version per document, none written twice
    assert (await redis_client.xpending(INGEST_STREAM, INGEST_GROUP))["pending"] == 0
    assert await redis_client.xlen(f"dlq:{INGEST_STREAM}") == 0


# --- drift worker ---------------------------------------------------------------------


async def test_killed_drift_worker_loses_no_drift_event(pool, redis_client):
    """A changed cited section makes the drift engine call the judge; A's judge is slow
    and A is killed inside it. B reclaims the event and records exactly one verdict."""

    def make(consumer: str, latency_ms: float) -> tuple[DriftWorker, DeterministicAdapter]:
        det = DeterministicAdapter("det", responder=ExtractiveResponder(), latency_ms=latency_ms)
        router = LLMRouter(
            providers={"det": det}, chains={"judge": [Route("det", "judge")]}, clock=ManualClock()
        )
        engine = DriftEngine(pool, router, ManualClock(1_750_000_000), Settings(_env_file=None))
        worker = DriftWorker(
            StreamBus(redis_client),
            engine,
            ManualClock(),
            redis=redis_client,
            consumer=consumer,
            reclaim_idle_ms=1_000,
        )
        return worker, det

    a, det_a = make("A", latency_ms=5_000)
    b, _ = make("B", latency_ms=0)
    await a.setup()

    def raw(day: int, liver: str) -> RawDocument:
        sections = (Section("Dosage", "Take 10 mg once daily."), Section("Liver", liver))
        return RawDocument(
            external_id="lipitor",
            title="Lipitor label",
            version_key=f"v{day}",
            valid_from=datetime(2024, 1, day, tzinfo=UTC),
            content="",
            sections=sections,
            raw_uri="file:///lipitor",
        )

    async with pool.acquire() as conn:
        tenant, source = await seed_source(conn)
        v1_raw = raw(1, RULE)
        v1 = await upsert_version(
            conn, source_id=source, raw=v1_raw, chunks=chunk_sections(v1_raw.sections)
        )
        liver = await conn.fetchval(
            "SELECT id FROM chunks WHERE version_id = $1 AND section_path = 'Liver'",
            v1.version_id,
        )
        await seed_watched_answer(conn, tenant, v1.version_id, [liver], [(RULE, RULE)])
        await conn.execute("UPDATE outbox SET published_at = now()")
        # The quote survives in a changed section, so the judge must decide.
        v2_raw = raw(2, f"{RULE} Stop treatment if ALT exceeds 3x ULN.")
        await upsert_version(
            conn, source_id=source, raw=v2_raw, chunks=chunk_sections(v2_raw.sections)
        )
    await OutboxRelay(pool, StreamBus(redis_client), alerts=AlertLog(redis_client)).relay_once()

    task_a = asyncio.create_task(a.run_once(block_ms=100))

    async def judging() -> bool:
        return bool(det_a.calls)

    await wait_until(judging, "worker A to be inside the judge call", 30)
    await kill(task_a)
    assert (await redis_client.xpending(DRIFT_STREAM, DRIFT_GROUP))["pending"] == 1

    async def reclaimed() -> bool:
        await b.run_once(block_ms=50)
        return (await redis_client.xpending(DRIFT_STREAM, DRIFT_GROUP))["pending"] == 0

    await wait_until(reclaimed, "worker B to reclaim the drift event", 30)

    async with pool.acquire() as conn:
        drift_events = await conn.fetchval("SELECT count(*) FROM drift_events")
    assert drift_events == 1
    assert await redis_client.xlen(f"dlq:{DRIFT_STREAM}") == 0
