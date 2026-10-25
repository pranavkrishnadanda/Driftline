"""Bounded "run until the queues are empty" for batch runs of the workers (`--drain`).

The nightly drift-watch job runs the ingest worker, then the drift worker, each until its
work is done, with the outbox relay running beside them. "Done" is checked against the
real backlog, not a quiet spell, so a slow relay cannot end a run early:

1. no committed outbox row is unpublished (the relay publishes before it commits
   `published_at`, so once this holds every event is already on its stream), then
2. every consumer group has read up to its stream's last entry and has nothing pending.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

import asyncpg
from redis.asyncio import Redis


class DrainTimeout(Exception):
    """The backlog was not empty when the drain's time budget ran out."""


async def outbox_drained(pool: asyncpg.Pool) -> bool:
    async with pool.acquire() as conn:
        return not await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM outbox WHERE published_at IS NULL)"
        )


async def group_drained(redis: Redis, stream: str, group: str) -> bool:
    """True when `group` has read every entry of `stream` and acked all it read."""
    info = next((g for g in await redis.xinfo_groups(stream) if g["name"] == group), None)
    if info is None:
        raise LookupError(f"no consumer group {group!r} on stream {stream!r}")
    if int(info["pending"]):
        return False
    last = (await redis.xinfo_stream(stream))["last-generated-id"]
    return info["last-delivered-id"] == last


async def pipeline_drained(
    pool: asyncpg.Pool, redis: Redis, groups: Sequence[tuple[str, str]]
) -> bool:
    """The outbox first, then the groups: see the module docstring for why."""
    if not await outbox_drained(pool):
        return False
    for stream, group in groups:
        if not await group_drained(redis, stream, group):
            return False
    return True


async def drain(
    step: Callable[[], Awaitable[int]],
    drained: Callable[[], Awaitable[bool]],
    *,
    timeout_s: float,
    idle_sleep_s: float = 0.2,
) -> int:
    """Call `step` (one worker pass; returns messages processed) until a pass processes
    nothing and `drained()` holds. Returns the messages processed; raises DrainTimeout
    when `timeout_s` elapses first."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    total = 0
    while True:
        processed = await step()
        total += processed
        if processed == 0 and await drained():
            return total
        if loop.time() >= deadline:
            raise DrainTimeout(f"backlog not empty after {timeout_s:g}s ({total} processed)")
        if processed == 0:
            await asyncio.sleep(idle_sleep_s)
