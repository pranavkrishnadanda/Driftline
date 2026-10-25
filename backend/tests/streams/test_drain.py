"""Drain checks against real Redis and Postgres: a group is drained only when it has
read every entry and acked all it read; `drain` stops on that, or times out."""

import json

import pytest

from driftline.streams.bus import StreamBus
from driftline.streams.drain import (
    DrainTimeout,
    drain,
    group_drained,
    outbox_drained,
    pipeline_drained,
)

STREAM, GROUP = "jobs", "workers"


async def test_group_drained_tracks_unread_and_pending(redis_client):
    bus = StreamBus(redis_client)
    await bus.ensure_group(STREAM, GROUP)
    assert await group_drained(redis_client, STREAM, GROUP)

    await bus.publish(STREAM, {"job": 1})
    assert not await group_drained(redis_client, STREAM, GROUP)  # unread

    [[_, [(msg_id, _)]]] = await redis_client.xreadgroup(GROUP, "c1", {STREAM: ">"}, count=1)
    assert not await group_drained(redis_client, STREAM, GROUP)  # read, not acked

    await redis_client.xack(STREAM, GROUP, msg_id)
    assert await group_drained(redis_client, STREAM, GROUP)


async def test_group_drained_rejects_unknown_group(redis_client):
    await StreamBus(redis_client).ensure_group(STREAM, GROUP)
    with pytest.raises(LookupError):
        await group_drained(redis_client, STREAM, "nobody")


async def test_outbox_must_be_published_before_the_pipeline_is_drained(fresh_pool, redis_client):
    await StreamBus(redis_client).ensure_group(STREAM, GROUP)
    async with fresh_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO outbox (topic, payload) VALUES ('jobs', $1::jsonb)", json.dumps({})
        )
    assert not await outbox_drained(fresh_pool)
    assert not await pipeline_drained(fresh_pool, redis_client, [(STREAM, GROUP)])

    async with fresh_pool.acquire() as conn:
        await conn.execute("UPDATE outbox SET published_at = now()")
    assert await pipeline_drained(fresh_pool, redis_client, [(STREAM, GROUP)])


async def test_drain_runs_steps_until_drained(redis_client):
    bus = StreamBus(redis_client)
    await bus.ensure_group(STREAM, GROUP)
    for n in range(3):
        await bus.publish(STREAM, {"job": n})
    seen = []

    async def handler(msg_id, payload):
        seen.append(payload["job"])

    async def step() -> int:
        return (await bus.consume_once(STREAM, GROUP, "c1", handler, count=1)).processed

    processed = await drain(step, lambda: group_drained(redis_client, STREAM, GROUP), timeout_s=10)

    assert processed == 3 and seen == [0, 1, 2]


async def test_drain_times_out_when_backlog_never_empties(redis_client):
    bus = StreamBus(redis_client)
    await bus.ensure_group(STREAM, GROUP)
    await bus.publish(STREAM, {"job": 1})

    async def failing(msg_id, payload):
        raise RuntimeError("never succeeds")

    async def step() -> int:
        return (await bus.consume_once(STREAM, GROUP, "c1", failing)).processed

    with pytest.raises(DrainTimeout):
        await drain(
            step,
            lambda: group_drained(redis_client, STREAM, GROUP),
            timeout_s=0.5,
            idle_sleep_s=0.05,
        )
