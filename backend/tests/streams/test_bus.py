import pytest

from driftline.streams.bus import StreamBus

STREAM, GROUP = "jobs", "workers"


@pytest.fixture
async def bus(redis_client):
    b = StreamBus(redis_client, max_deliveries=3)
    await b.ensure_group(STREAM, GROUP)
    return b


async def test_publish_consume_acks(bus, redis_client):
    seen = []

    async def handler(msg_id, payload):
        seen.append(payload)

    await bus.publish(STREAM, {"job": 1})
    result = await bus.consume_once(STREAM, GROUP, "c1", handler)
    assert result.processed == 1
    assert seen == [{"job": 1}]
    summary = await redis_client.xpending(STREAM, GROUP)
    assert summary["pending"] == 0


async def test_ensure_group_is_idempotent(bus):
    await bus.ensure_group(STREAM, GROUP)


async def test_consumers_in_group_split_work(bus):
    got_a, got_b = [], []

    async def a(_, p):
        got_a.append(p["n"])

    async def b(_, p):
        got_b.append(p["n"])

    for n in range(10):
        await bus.publish(STREAM, {"n": n})
    await bus.consume_once(STREAM, GROUP, "a", a, count=5)
    await bus.consume_once(STREAM, GROUP, "b", b, count=5)
    assert len(got_a) == 5 and len(got_b) == 5
    assert set(got_a).isdisjoint(got_b)
    assert sorted(got_a + got_b) == list(range(10))


async def test_failed_message_stays_pending(bus, redis_client):
    async def boom(_, __):
        raise RuntimeError("handler failed")

    await bus.publish(STREAM, {"x": 1})
    result = await bus.consume_once(STREAM, GROUP, "c1", boom)
    assert result.failed == 1
    summary = await redis_client.xpending(STREAM, GROUP)
    assert summary["pending"] == 1


async def test_stalled_message_is_reclaimed_by_another_consumer(bus, redis_client):
    # consumer "crashed" reads the message and never acks (real XREADGROUP, no handler)
    await bus.publish(STREAM, {"job": "stalled"})
    await redis_client.xreadgroup(GROUP, "crashed", {STREAM: ">"}, count=1)

    seen = []

    async def handler(_, payload):
        seen.append(payload)

    result = await bus.reclaim_once(STREAM, GROUP, "rescuer", handler, min_idle_ms=0)
    assert result.processed == 1
    assert seen == [{"job": "stalled"}]
    assert (await redis_client.xpending(STREAM, GROUP))["pending"] == 0


async def test_message_is_dead_lettered_after_max_deliveries(bus, redis_client):
    async def boom(_, __):
        raise RuntimeError("always fails")

    await bus.publish(STREAM, {"x": 1})
    await bus.consume_once(STREAM, GROUP, "c1", boom)  # delivery 1
    await bus.reclaim_once(STREAM, GROUP, "c1", boom, min_idle_ms=0)  # delivery 2
    result = await bus.reclaim_once(STREAM, GROUP, "c1", boom, min_idle_ms=0)  # delivery 3
    assert result.dead_lettered == 1
    dlq = await redis_client.xrange(f"dlq:{STREAM}")
    assert len(dlq) == 1
    assert "always fails" in dlq[0][1]["error"]
    assert (await redis_client.xpending(STREAM, GROUP))["pending"] == 0


async def test_invalid_json_is_dead_lettered(bus, redis_client):
    seen = []

    async def handler(_, payload):
        seen.append(payload)

    await redis_client.xadd(STREAM, {"data": "not json{"})
    await bus.consume_once(STREAM, GROUP, "c1", handler)
    await bus.reclaim_once(STREAM, GROUP, "c1", handler, min_idle_ms=0)
    result = await bus.reclaim_once(STREAM, GROUP, "c1", handler, min_idle_ms=0)
    assert seen == []
    assert result.dead_lettered == 1
    assert len(await redis_client.xrange(f"dlq:{STREAM}")) == 1
