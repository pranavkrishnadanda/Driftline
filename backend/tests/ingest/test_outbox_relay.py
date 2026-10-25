import asyncio
import json

import asyncpg

from driftline.clock import ManualClock
from driftline.ingest.outbox import TOPIC_STREAMS, OutboxRelay, streams_for
from driftline.streams.bus import StreamBus


async def add_rows(pool, n: int, topic: str = "version.created") -> list[int]:
    async with pool.acquire() as conn:
        return [
            await conn.fetchval(
                "INSERT INTO outbox (topic, payload) VALUES ($1, $2::jsonb) RETURNING id",
                topic,
                json.dumps({"n": i}),
            )
            for i in range(n)
        ]


async def stream_payloads(redis_client, stream: str) -> list[dict]:
    return [json.loads(fields["data"]) for _, fields in await redis_client.xrange(stream)]


async def test_relay_publishes_and_marks(fresh_pool, redis_client):
    ids = await add_rows(fresh_pool, 2)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client))
    assert await relay.relay_once() == 2
    payloads = await stream_payloads(redis_client, "embed")
    assert [p["event_id"] for p in payloads] == ids
    assert payloads[0] == {"n": 0, "event_id": ids[0], "topic": "version.created"}
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM outbox WHERE published_at IS NULL") == 0


async def test_published_rows_are_not_sent_again(fresh_pool, redis_client):
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client))
    assert await relay.relay_once() == 0
    await add_rows(fresh_pool, 1)
    assert await relay.relay_once() == 1
    assert await relay.relay_once() == 0
    assert len(await redis_client.xrange("embed")) == 1


async def test_crash_between_publish_and_mark_republishes_same_event_id(
    fresh_pool, fresh_dsn, redis_client
):
    [row_id] = await add_rows(fresh_pool, 1)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client))
    crashing = await asyncpg.connect(fresh_dsn)
    tx = crashing.transaction()
    await tx.start()
    assert await relay.claim_and_publish(crashing) == [row_id]
    await crashing.close()  # the relay dies before mark_published commits
    assert await relay.relay_once() == 1
    events = [p["event_id"] for p in await stream_payloads(redis_client, "embed")]
    assert events == [row_id, row_id]  # at-least-once; consumers dedupe on event_id
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT published_at IS NOT NULL FROM outbox WHERE id = $1", row_id
        )


async def test_concurrent_relays_skip_locked_rows(fresh_pool, fresh_dsn, redis_client):
    await add_rows(fresh_pool, 3)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client))
    holder = await asyncpg.connect(fresh_dsn)
    try:
        async with holder.transaction():
            claimed = await relay.claim_and_publish(holder)
            assert len(claimed) == 3
            assert await relay.relay_once() == 0  # every row is locked by the other relay
            await relay.mark_published(holder, claimed)
    finally:
        await holder.close()
    assert len(await redis_client.xrange("embed")) == 3


async def test_unknown_topic_publishes_to_stream_named_after_topic(fresh_pool, redis_client):
    assert streams_for("version.created") == TOPIC_STREAMS["version.created"] == ("embed",)
    await add_rows(fresh_pool, 1, topic="custom.topic")
    await OutboxRelay(fresh_pool, StreamBus(redis_client)).relay_once()
    assert len(await redis_client.xrange("custom.topic")) == 1


async def test_batch_size_limits_one_pass(fresh_pool, redis_client):
    await add_rows(fresh_pool, 5)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client), batch_size=2)
    assert [await relay.relay_once() for _ in range(4)] == [2, 2, 1, 0]


async def test_run_sleeps_when_idle_and_stops(fresh_pool, redis_client):
    await add_rows(fresh_pool, 1)
    relay = OutboxRelay(fresh_pool, StreamBus(redis_client))
    stop, clock = asyncio.Event(), ManualClock()
    task = asyncio.create_task(relay.run(stop, idle_sleep_s=0.5, clock=clock))
    while clock.now() < 1.0:  # at least two idle sleeps after publishing the row
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, 5)
    assert len(await redis_client.xrange("embed")) == 1
