"""The agent worker over the real `agent` stream: real Postgres (+ checkpointer), Redis,
TEI embedder, and the DeterministicAdapter running the in-repo ExtractiveResponder."""

import asyncio
import json
import time
from datetime import UTC, datetime

import pytest
from dbseed import EMBED_MODEL, VersionSeed, embed_all, seed_history, seed_source

from driftline.agents.__main__ import amain, build_agent_router, setup_checkpointer
from driftline.agents.eventlog import AskEventLog
from driftline.agents.events import ErrorEvent, FinalEvent
from driftline.agents.graph import AgentDeps, build_answer_graph
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.agents.schemas import AGENT_GROUP, AGENT_STREAM, AnswerSchema, AskJob
from driftline.agents.worker import AgentWorker, reap_lost_asks
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.latency import LatencyStubAdapter, worker_seed
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.llm.types import ProviderError
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.streams.bus import StreamBus

NEW_RULE = "Check ALT monthly during therapy."
NOW = datetime(2026, 10, 25, tzinfo=UTC)


@pytest.fixture
async def setup(fresh_pool, fresh_conn, redis_client, checkpointer, embedder_url):
    tenant, source = await seed_source(fresh_conn, kind="openfda")
    _, versions, chunks = await seed_history(
        fresh_conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[VersionSeed(datetime(2024, 4, 15, tzinfo=UTC), [("Liver", NEW_RULE)])],
    )
    await embed_all(fresh_conn, embedder_url)

    def make(script=None, *, checkpointed=True, clock=None, reclaim_idle_ms=60_000, latency_ms=0.0):
        det = DeterministicAdapter(
            "det", script=script, responder=ExtractiveResponder(), latency_ms=latency_ms
        )
        tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
        router = LLMRouter(
            providers={"det": det, "tei": TEIEmbeddingAdapter(embedder_url)},
            chains={**tiers, "embed": [Route("tei", EMBED_MODEL)]},
            clock=ManualClock(),
        )
        deps = AgentDeps(
            pool=fresh_pool,
            llm=AgentLLM(router, ledger=CostLedger(fresh_pool)),
            retriever=HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL),
            reranker=TEIReranker(None),
            clock=ManualClock(NOW.timestamp()),
        )
        compiled = build_answer_graph(deps)
        # Without a checkpointer the real graph raises on its first state read: an
        # unexpected (non-LLM) failure, with no mock involved.
        graph = compiled.compile(checkpointer=checkpointer) if checkpointed else compiled.compile()
        bus = StreamBus(redis_client)
        worker = AgentWorker(
            pool=fresh_pool,
            redis=redis_client,
            bus=bus,
            events=AskEventLog(redis_client),
            graph=graph,
            consumer="w1",
            clock=clock or ManualClock(NOW.timestamp()),
            reclaim_idle_ms=reclaim_idle_ms,
        )
        return det, worker, bus

    return {"tenant": tenant, "versions": versions, "chunks": chunks, "make": make}


async def insert_job(conn, tenant, kind="ask"):
    return await conn.fetchval(
        "INSERT INTO jobs (tenant_id, kind) VALUES ($1, $2) RETURNING id", tenant, kind
    )


async def enqueue(fresh_conn, bus, tenant, *, payload_tenant=None) -> AskJob:
    job = AskJob(
        job_id=await insert_job(fresh_conn, tenant),
        tenant_id=payload_tenant or tenant,
        question="How often should ALT be checked?",
        as_of=datetime(2024, 6, 1, tzinfo=UTC),
    )
    await bus.publish(AGENT_STREAM, job.model_dump(mode="json"))
    return job


async def job_row(conn, job_id):
    return await conn.fetchrow("SELECT status, error FROM jobs WHERE id = $1", job_id)


async def test_worker_answers_persists_and_publishes_final(setup, fresh_conn, redis_client):
    _, worker, bus = setup["make"]()
    await worker.setup()
    job = await enqueue(fresh_conn, bus, setup["tenant"])
    assert await worker.run_once() == 1
    row = await fresh_conn.fetchrow(
        "SELECT a.id, a.tenant_id, a.question, a.as_of, a.body, a.confidence, a.status, "
        "a.degraded, a.cost_usd, j.status AS job_status, j.finished_at "
        "FROM answers a JOIN jobs j ON j.id = a.job_id WHERE a.job_id = $1",
        job.job_id,
    )
    assert (row["status"], row["job_status"]) == ("answered", "succeeded")
    assert row["tenant_id"] == setup["tenant"] and row["question"] == job.question
    assert row["as_of"] == job.as_of and row["finished_at"] is not None
    assert row["degraded"] is False and row["cost_usd"] == 0 and row["confidence"] == 1.0
    body = AnswerSchema.model_validate(json.loads(row["body"]))
    assert body.answer == NEW_RULE and body.answer_id is None  # the id lives in its column
    citations = await fresh_conn.fetch(
        "SELECT claim_idx, chunk_id FROM answer_citations WHERE answer_id = $1", row["id"]
    )
    assert [(c["claim_idx"], c["chunk_id"]) for c in citations] == [(0, setup["chunks"][0][0])]
    events = await AskEventLog(redis_client).read(job.job_id)
    final = events[-1][1]
    assert isinstance(final, FinalEvent) and final.answer.answer_id == row["id"]
    assert final.answer.answer == NEW_RULE
    assert [n for n, _ in events] == list(range(1, len(events) + 1))
    pending = await redis_client.xpending(AGENT_STREAM, AGENT_GROUP)
    assert pending["pending"] == 0


async def test_redelivered_finished_job_is_not_rerun(setup, fresh_conn, redis_client):
    det, worker, bus = setup["make"]()
    await worker.setup()
    job = await enqueue(fresh_conn, bus, setup["tenant"])
    await worker.run_once()
    calls = list(det.calls)
    events_before = await AskEventLog(redis_client).last_id(job.job_id)
    await bus.publish(AGENT_STREAM, job.model_dump(mode="json"))
    assert await worker.run_once() == 1
    assert det.calls == calls
    assert await AskEventLog(redis_client).last_id(job.job_id) == events_before
    assert await fresh_conn.fetchval("SELECT count(*) FROM answers") == 1


async def test_running_ask_keeps_its_claim_so_no_other_worker_reclaims_it(
    setup, fresh_conn, redis_client
):
    # Each LLM call sleeps in real time, outlasting the 300 ms reclaim threshold.
    det, worker, bus = setup["make"](reclaim_idle_ms=300, latency_ms=700)
    await worker.setup()
    job = await enqueue(fresh_conn, bus, setup["tenant"])
    first = asyncio.create_task(worker.run_once())
    stolen = []

    async def second_worker(msg_id, payload):
        stolen.append(msg_id)

    deadline = time.monotonic() + 60
    while not det.calls and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert det.calls, "the first worker never reached the LLM"
    passes = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(0.45)  # longer than reclaim_idle_ms
        if first.done():
            break
        await bus.reclaim_once(AGENT_STREAM, AGENT_GROUP, "w2", second_worker, min_idle_ms=300)
        passes += 1
    assert passes >= 1, "the first worker finished before any reclaim pass ran"
    assert stolen == []
    assert await first == 1
    assert (await job_row(fresh_conn, job.job_id))["status"] == "succeeded"
    assert (await redis_client.xpending(AGENT_STREAM, AGENT_GROUP))["pending"] == 0


async def test_llm_outage_fails_the_job_with_a_terminal_error(setup, fresh_conn, redis_client):
    outage = ProviderError("down", retryable=False, status=400)
    _, worker, bus = setup["make"](script=[outage])
    await worker.setup()
    job = await enqueue(fresh_conn, bus, setup["tenant"])
    assert await worker.run_once() == 1  # handled and acked: retrying cannot help
    row = await job_row(fresh_conn, job.job_id)
    assert (row["status"], row["error"]) == ("failed", "llm_unavailable")
    last = (await AskEventLog(redis_client).read(job.job_id))[-1][1]
    assert isinstance(last, ErrorEvent) and last.code == "llm_unavailable" and not last.retryable
    assert (await redis_client.xpending(AGENT_STREAM, AGENT_GROUP))["pending"] == 0


async def test_unexpected_failure_retries_then_dead_letters_and_fails_the_job(
    setup, fresh_conn, redis_client
):
    _, worker, bus = setup["make"](checkpointed=False, reclaim_idle_ms=0)
    await worker.setup()
    job = await enqueue(fresh_conn, bus, setup["tenant"])
    assert await worker.run_once() == 0  # delivery 1 (read) and 2 (reclaimed) both fail
    assert (await job_row(fresh_conn, job.job_id))["status"] == "running"
    assert await worker.run_once() == 0  # delivery 3 fails: dead-lettered
    row = await job_row(fresh_conn, job.job_id)
    assert (row["status"], row["error"]) == ("failed", "internal")
    events = [e for _, e in await AskEventLog(redis_client).read(job.job_id)]
    assert [(e.code, e.retryable) for e in events if isinstance(e, ErrorEvent)] == [
        ("internal", True),
        ("internal", True),
        ("internal", False),
    ]
    assert await redis_client.xlen(f"dlq:{AGENT_STREAM}") == 1
    assert (await redis_client.xpending(AGENT_STREAM, AGENT_GROUP))["pending"] == 0


async def test_payload_naming_another_tenant_is_never_run(setup, fresh_conn, redis_client):
    det, worker, bus = setup["make"](reclaim_idle_ms=0)
    await worker.setup()
    other, _ = await seed_source(fresh_conn)
    job = await enqueue(fresh_conn, bus, setup["tenant"], payload_tenant=other)
    await worker.run_once()
    await worker.run_once()
    assert det.calls == []
    assert (await job_row(fresh_conn, job.job_id))["status"] == "queued"
    assert await AskEventLog(redis_client).last_id(job.job_id) == 0
    assert await fresh_conn.fetchval("SELECT count(*) FROM answers") == 0
    assert await redis_client.xlen(f"dlq:{AGENT_STREAM}") == 1


async def test_reaper_fails_only_stale_queued_asks_without_a_stream_entry(
    fresh_pool, fresh_conn, redis_client
):
    tenant, _ = await seed_source(fresh_conn)
    bus, events = StreamBus(redis_client), AskEventLog(redis_client)
    clock = ManualClock(time.time())
    lost = await insert_job(fresh_conn, tenant)  # its publish never happened
    published = (await enqueue(fresh_conn, bus, tenant)).job_id  # queued behind a backlog
    ingest = await insert_job(fresh_conn, tenant, kind="ingest")
    running = await insert_job(fresh_conn, tenant)
    await fresh_conn.execute("UPDATE jobs SET status = 'running' WHERE id = $1", running)

    async def reap():
        return await reap_lost_asks(
            fresh_pool, redis_client, events, now=clock.now(), timeout_s=300
        )

    assert await reap() == []  # too young: the publish may still be on its way
    clock.advance(301)
    assert await reap() == [lost]
    row = await job_row(fresh_conn, lost)
    assert (row["status"], row["error"]) == ("failed", "enqueue_lost")
    last = (await events.read(lost))[-1][1]
    assert isinstance(last, ErrorEvent) and last.code == "enqueue_lost" and not last.retryable
    for job_id, status in ((published, "queued"), (ingest, "queued"), (running, "running")):
        assert (await job_row(fresh_conn, job_id))["status"] == status
        assert await events.last_id(job_id) == 0
    assert await reap() == []  # idempotent
    assert await events.last_id(lost) == 1


async def test_reaper_spares_asks_waiting_in_the_outbox(fresh_pool, fresh_conn, redis_client):
    """A review follow-up (regeneration) is queued through the outbox: while its row is
    unpublished (the relay is down or behind), the ask is not lost and is not reaped."""
    tenant, _ = await seed_source(fresh_conn)
    clock = ManualClock(time.time())
    waiting = await insert_job(fresh_conn, tenant)
    job = AskJob(job_id=waiting, tenant_id=tenant, question="q")
    await fresh_conn.execute(
        "INSERT INTO outbox (topic, payload) VALUES ('ask.regenerate', $1::jsonb)",
        job.model_dump_json(),
    )
    clock.advance(301)
    reaped = await reap_lost_asks(
        fresh_pool, redis_client, AskEventLog(redis_client), now=clock.now(), timeout_s=300
    )
    assert reaped == []
    assert (await job_row(fresh_conn, waiting))["status"] == "queued"


async def test_worker_reaps_periodically(setup, fresh_conn, redis_client):
    clock = ManualClock(time.time())
    _, worker, _ = setup["make"](clock=clock)
    lost = await insert_job(fresh_conn, setup["tenant"])
    assert await worker.maybe_reap() == []  # first pass runs at once; the job is young
    clock.advance(301)
    assert await worker.maybe_reap() == [lost]
    late = await insert_job(fresh_conn, setup["tenant"])
    await fresh_conn.execute(
        "UPDATE jobs SET created_at = created_at - interval '1 hour' WHERE id = $1", late
    )
    assert await worker.maybe_reap() is None  # not due yet
    clock.advance(60)
    assert await worker.maybe_reap() == [late]


async def test_run_loop_reaps_and_stops(setup, fresh_conn, redis_client):
    lost = await insert_job(fresh_conn, setup["tenant"])
    _, worker, _ = setup["make"](clock=ManualClock(time.time() + 301))
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    try:
        async with asyncio.timeout(15):
            while (await job_row(fresh_conn, lost))["status"] != "failed":
                await asyncio.sleep(0.05)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=15)


def test_offline_mode_builds_a_keyless_router(redis_client):
    settings = Settings(_env_file=None, llm_offline=True)
    router = build_agent_router(settings, redis_client, clock=ManualClock())
    assert set(router.chains) == {"extract", "answer", "judge", "embed"}
    assert "anthropic" not in router.providers and "gemini" not in router.providers
    with pytest.raises(ValueError):
        build_agent_router(Settings(_env_file=None), redis_client, clock=ManualClock())


async def test_concurrent_worker_startups_set_up_the_checkpointer_once(fresh_dsn, fresh_pool):
    """`--scale agent-worker=8` on a fresh database: every worker runs the checkpointer
    setup at once. Unserialised, LangGraph's migrations race and all but one worker die
    with UniqueViolation on checkpoint_migrations_pkey (seen in the P7 bench)."""
    from contextlib import AsyncExitStack

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncExitStack() as stack:
        savers = [
            await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(fresh_dsn))
            for _ in range(8)
        ]
        await asyncio.gather(*(setup_checkpointer(s, fresh_pool) for s in savers))
    async with fresh_pool.acquire() as conn:
        versions = await conn.fetchval("SELECT count(*) FROM checkpoint_migrations")
    assert versions > 0


def test_bench_mode_wins_over_offline_mode(redis_client):
    settings = Settings(_env_file=None, llm_offline=True, llm_bench=True)
    router = build_agent_router(settings, redis_client, clock=ManualClock(), consumer="w1")
    assert set(router.providers) == {"bench", "tei"}
    assert isinstance(router.providers["bench"], LatencyStubAdapter)
    for tier in ("extract", "answer", "judge"):
        assert router.chains[tier] == [Route("bench", f"bench-{tier}")]


def test_bench_stub_seed_is_derived_per_worker(redis_client):
    settings = Settings(_env_file=None, llm_bench=True, llm_bench_seed=7)

    def seed(consumer: str | None) -> int:
        router = build_agent_router(settings, redis_client, clock=ManualClock(), consumer=consumer)
        return router.providers["bench"].seed

    assert seed("agent-1") == seed("agent-1") == worker_seed(7, "agent-1")
    assert len({seed("agent-1"), seed("agent-2"), seed("agent-3")}) == 3
    assert seed(None) == 7  # no consumer (a one-off CLI): the configured seed as-is


async def test_reap_cli_fails_lost_asks(fresh_dsn, fresh_conn, redis_url, redis_client):
    tenant, _ = await seed_source(fresh_conn)
    lost = await insert_job(fresh_conn, tenant)
    await fresh_conn.execute(
        "UPDATE jobs SET created_at = now() - interval '1 hour' WHERE id = $1", lost
    )
    settings = Settings(_env_file=None, database_url=fresh_dsn, redis_url=redis_url)
    assert await amain(["reap"], settings) == 0
    assert (await job_row(fresh_conn, lost))["error"] == "enqueue_lost"
