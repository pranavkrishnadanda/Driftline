"""Event logs on Redis Streams, so SSE clients can replay with Last-Event-ID.

Each event gets the next integer id for its stream from a counter, and is stored at
stream entry id `<n>-0`, atomically (one Lua script), so ids are gap-free, strictly
increasing and safe with concurrent writers (parallel subagents). The stream is capped
(MAXLEN) and expires after its TTL: a client that falls further behind than the cap gets
an `events_expired` error instead of silently missing events.

`EventLog` is the generic log, given the stream key function and the event union to
parse. `AskEventLog` is the per-ask log (`events:ask:{job}`); the per-tenant alert log
(`driftline.drift.alerts.AlertLog`) composes an `EventLog` the same way.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, TypeAdapter
from redis.asyncio import Redis

from driftline.agents.events import ASK_EVENT_ADAPTER, AskEvent

# KEYS[1] stream, KEYS[2] counter, KEYS[3] dedupe hash (dedupe id -> event id);
# ARGV: payload, maxlen, ttl_s, dedupe id ('' = no dedupe).
# A dedupe id seen before writes nothing and returns the id it was first stored under.
_APPEND = """
if ARGV[4] ~= '' then
  local seen = redis.call('HGET', KEYS[3], ARGV[4])
  if seen then return tonumber(seen) end
end
local n = redis.call('INCR', KEYS[2])
redis.call('XADD', KEYS[1], 'MAXLEN', ARGV[2], n .. '-0', 'data', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
if ARGV[4] ~= '' then
  redis.call('HSET', KEYS[3], ARGV[4], n)
  redis.call('EXPIRE', KEYS[3], ARGV[3])
end
return n
"""


def stream_key(job_id: UUID | str) -> str:
    return f"events:ask:{job_id}"


def _seq(entry_id: str) -> int:
    return int(entry_id.split("-", 1)[0])


class EventLog:
    """A family of capped, expiring event streams, one per scope (an ask, a tenant)."""

    def __init__(
        self,
        redis: Redis,
        *,
        key: Callable[[UUID | str], str],
        adapter: TypeAdapter[Any],
        maxlen: int,
        ttl_s: int,
    ) -> None:
        self._redis = redis
        self._key = key
        self._adapter = adapter
        self._maxlen = maxlen
        self._ttl_s = ttl_s
        self._append = redis.register_script(_APPEND)

    async def append(
        self, scope_id: UUID | str, event: BaseModel, *, dedupe_id: str | None = None
    ) -> int:
        """Store one event; returns its id (1, 2, 3, ... per scope). With `dedupe_id`, an
        event already stored under that id (within the TTL) is not stored again and its
        original id is returned."""
        stream = self._key(scope_id)
        n = await self._append(
            keys=[stream, f"{stream}:seq", f"{stream}:dedupe"],
            args=[event.model_dump_json(), self._maxlen, self._ttl_s, dedupe_id or ""],
        )
        return int(n)

    async def read(
        self, scope_id: UUID | str, *, after: int = 0, count: int = 100, block_ms: int | None = None
    ) -> list[tuple[int, Any]]:
        """Events with id > `after`, oldest first. With `block_ms`, wait up to that long
        for the first one (0 waits forever, None does not wait)."""
        resp = await self._redis.xread(
            {self._key(scope_id): f"{after}-0"}, count=count, block=block_ms
        )
        if not resp:
            return []
        return [
            (_seq(entry_id), self._adapter.validate_json(fields["data"]))
            for entry_id, fields in resp[0][1]
        ]

    async def first_id(self, scope_id: UUID | str) -> int | None:
        """The oldest id still stored, or None when nothing is stored."""
        entries = await self._redis.xrange(self._key(scope_id), count=1)
        return _seq(entries[0][0]) if entries else None

    async def last_id(self, scope_id: UUID | str) -> int:
        value = await self._redis.get(f"{self._key(scope_id)}:seq")
        return int(value) if value else 0

    async def has_gap(self, scope_id: UUID | str, after: int) -> bool:
        """True when events after `after` were already trimmed away."""
        first = await self.first_id(scope_id)
        if first is None:
            return after < await self.last_id(scope_id)
        return first > after + 1


class AskEventLog(EventLog):
    """The per-ask event log, on `events:ask:{job_id}`."""

    def __init__(self, redis: Redis, *, maxlen: int = 10_000, ttl_s: int = 24 * 3600) -> None:
        super().__init__(
            redis, key=stream_key, adapter=ASK_EVENT_ADAPTER, maxlen=maxlen, ttl_s=ttl_s
        )

    async def read(
        self, job_id: UUID | str, *, after: int = 0, count: int = 100, block_ms: int | None = None
    ) -> list[tuple[int, AskEvent]]:
        """Ask events with id > `after`, oldest first (see `EventLog.read`)."""
        return await super().read(job_id, after=after, count=count, block_ms=block_ms)
