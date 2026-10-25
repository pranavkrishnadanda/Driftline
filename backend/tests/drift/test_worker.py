"""Drift worker: consumes `version.created` events from the `drift` stream (consumer
group `drift`) and runs the drift engine. Real Postgres, real Redis, the real outbox
relay, and DeterministicAdapter as the judge."""

import json
from datetime import UTC, datetime

import pytest
from dbseed import seed_source, seed_watched_answer

from driftline.agents.offline import ExtractiveResponder
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.drift.alerts import AlertLog
from driftline.drift.engine import DriftEngine
from driftline.drift.worker import DRIFT_GROUP, DRIFT_STREAM, DriftWorker
from driftline.ingest.chunker import chunk_sections
from driftline.ingest.outbox import OutboxRelay
from driftline.ingest.store import upsert_version
from driftline.ingest.types import RawDocument, Section
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.streams.bus import StreamBus

DOSAGE = ("Dosage", "Take 10 mg once daily with water.")
LIVER = ("Liver", "Check ALT monthly during therapy.")
CLAIM = ("Check ALT monthly during therapy.", "Check ALT monthly during therapy.")


@pytest.fixture
def engine(fresh_pool):
    router = LLMRouter(
        providers={"det": DeterministicAdapter("det", responder=ExtractiveResponder())},
        chains={"judge": [Route("det", "judge-model")]},
        clock=ManualClock(),
    )
    return DriftEngine(fresh_pool, router, ManualClock(1_750_000_000), Settings(_env_file=None))


def make_worker(redis_client, engine, *, consumer="w1", reclaim_idle_ms=60_000) -> DriftWorker:
    return DriftWorker(
        StreamBus(redis_client),
        engine,
        ManualClock(),
        redis=redis_client,
        consumer=consumer,
        reclaim_idle_ms=reclaim_idle_ms,
    )


async def store(conn, source_id, sections, *, day: int):
    raw = RawDocument(
        external_id="lipitor",
        title="Lipitor label",
        version_key=f"v{day}",
        valid_from=datetime(2024, 1, day, tzinfo=UTC),
        content="",
        sections=tuple(Section(p, t) for p, t in sections),
        raw_uri="file:///lipitor",
    )
    return await upsert_version(
        conn, source_id=source_id, raw=raw, chunks=chunk_sections(raw.sections)
    )


async def watched_answer_then_new_version(pool) -> None:
    """v1 with a watched answer citing `Liver`, then v2 that leaves `Liver` unchanged; the
    v2 `version.created` outbox row is committed but not yet relayed."""
    async with pool.acquire() as conn:
        tenant, source = await seed_source(conn)
        v1 = await store(conn, source, [DOSAGE, LIVER], day=1)
        liver = await conn.fetchval(
            "SELECT id FROM chunks WHERE version_id = $1 AND section_path = 'Liver'",
            v1.version_id,
        )
        await seed_watched_answer(conn, tenant, v1.version_id, [liver], [CLAIM])
        await conn.execute("UPDATE outbox SET published_at = now()")  # v1's event is old news
        await store(conn, source, [DOSAGE, LIVER, ("Warnings", "Avoid alcohol.")], day=2)


async def relay(pool, redis_client) -> int:
    return await OutboxRelay(
        pool, StreamBus(redis_client), alerts=AlertLog(redis_client)
    ).relay_once()


async def pending(redis_client) -> int:
    return (await redis_client.xpending(DRIFT_STREAM, DRIFT_GROUP))["pending"]


async def drift_verdicts(pool) -> list[str]:
    async with pool.acquire() as conn:
        return [r["verdict"] for r in await conn.fetch("SELECT verdict FROM drift_events")]


async def test_drift_event_is_recorded_and_message_acked(fresh_pool, redis_client, engine):
    worker = make_worker(redis_client, engine)
    await worker.setup()
    await watched_answer_then_new_version(fresh_pool)
    assert await relay(fresh_pool, redis_client) == 1  # version.created -> embed + drift

    assert await worker.run_once() == 1

    assert await drift_verdicts(fresh_pool) == ["still_valid"]
    assert await pending(redis_client) == 0
    assert await redis_client.xlen(f"dlq:{DRIFT_STREAM}") == 0


async def test_handler_failing_three_times_goes_to_dlq(fresh_pool, redis_client, engine):
    worker = make_worker(redis_client, engine, reclaim_idle_ms=0)
    await worker.setup()
    bad = {"event_id": 7, "topic": "version.created", "document_id": "not-a-uuid"}
    await StreamBus(redis_client).publish(DRIFT_STREAM, bad)

    await worker.run_once()  # delivery 1 (read) fails, delivery 2 (reclaim) fails
    assert await redis_client.xlen(f"dlq:{DRIFT_STREAM}") == 0
    assert await pending(redis_client) == 1
    await worker.run_once()  # delivery 3 (reclaim) fails: dead-lettered

    dead = await redis_client.xrange(f"dlq:{DRIFT_STREAM}")
    assert len(dead) == 1
    assert json.loads(dead[0][1]["data"]) == bad
    assert "ValueError" in dead[0][1]["error"]
    assert await pending(redis_client) == 0


async def test_message_stalled_on_dead_consumer_is_reclaimed(fresh_pool, redis_client, engine):
    await make_worker(redis_client, engine).setup()
    await watched_answer_then_new_version(fresh_pool)
    await relay(fresh_pool, redis_client)
    # A consumer reads the event and dies before acking it.
    taken = await redis_client.xreadgroup(DRIFT_GROUP, "dead", {DRIFT_STREAM: ">"}, count=1)
    assert len(taken[0][1]) == 1

    # Not idle long enough yet: a live worker leaves it alone.
    assert await make_worker(redis_client, engine, consumer="w2").run_once() == 0
    assert await drift_verdicts(fresh_pool) == []

    reclaimer = make_worker(redis_client, engine, consumer="w2", reclaim_idle_ms=0)
    assert await reclaimer.run_once() == 1

    assert await drift_verdicts(fresh_pool) == ["still_valid"]
    assert await pending(redis_client) == 0


async def test_redelivered_event_records_one_drift_event(fresh_pool, redis_client, engine):
    worker = make_worker(redis_client, engine)
    await worker.setup()
    await watched_answer_then_new_version(fresh_pool)
    await relay(fresh_pool, redis_client)
    message = (await redis_client.xrange(DRIFT_STREAM))[0][1]
    await redis_client.xadd(DRIFT_STREAM, message)  # the relay delivered it twice

    assert [await worker.run_once() for _ in range(2)] == [1, 1]  # one message per pass

    assert await drift_verdicts(fresh_pool) == ["still_valid"]
    assert await pending(redis_client) == 0
