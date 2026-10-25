import pytest

from driftline.clock import ManualClock
from driftline.llm.ratelimit import RateLimitTimeout, RedisTokenBucket


def bucket(redis_client, clock, capacity=2, rate=1.0, key="rl:test"):
    return RedisTokenBucket(redis_client, key, capacity=capacity, refill_per_sec=rate, clock=clock)


async def test_allows_up_to_capacity_then_denies_with_wait(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=2, rate=0.5)
    assert (await b.try_acquire())[0] is True
    assert (await b.try_acquire())[0] is True
    allowed, wait = await b.try_acquire()
    assert allowed is False
    assert wait == pytest.approx(2.0)


async def test_refills_over_time(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=1, rate=1.0)
    assert (await b.try_acquire())[0]
    assert not (await b.try_acquire())[0]
    clock.advance(1.0)
    assert (await b.try_acquire())[0]


async def test_two_instances_share_one_quota(redis_client):
    clock = ManualClock(1000.0)
    worker_a = bucket(redis_client, clock, capacity=2)
    worker_b = bucket(redis_client, clock, capacity=2)
    assert (await worker_a.try_acquire())[0]
    assert (await worker_b.try_acquire())[0]
    assert not (await worker_a.try_acquire())[0]


async def test_acquire_waits_for_refill(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=1, rate=1.0)
    await b.acquire(timeout=5)
    await b.acquire(timeout=5)
    assert clock.now() == pytest.approx(1001.0)


async def test_acquire_times_out(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=1, rate=0.1)
    await b.acquire(timeout=1)
    with pytest.raises(RateLimitTimeout):
        await b.acquire(timeout=1)


async def test_cost_above_capacity_is_rejected(redis_client):
    b = bucket(redis_client, ManualClock(0.0), capacity=2)
    with pytest.raises(ValueError):
        await b.acquire(cost=3, timeout=10)


async def test_clock_behind_last_writer_does_not_go_negative(redis_client):
    ahead, behind = ManualClock(2000.0), ManualClock(1990.0)
    b_ahead = bucket(redis_client, ahead, capacity=2, rate=1.0)
    b_behind = bucket(redis_client, behind, capacity=2, rate=1.0)
    assert (await b_ahead.try_acquire())[0]
    allowed, _ = await b_behind.try_acquire()
    assert allowed is True
    tokens = float(await redis_client.hget("rl:test", "tokens"))
    assert 0.0 <= tokens <= 2.0
