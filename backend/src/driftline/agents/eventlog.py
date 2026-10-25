"""Per-ask event log on a Redis Stream, so SSE clients can replay with Last-Event-ID.

Each event gets the next integer id for its ask from a counter, and is stored at stream
entry id `<n>-0`, atomically (one Lua script), so ids are gap-free, strictly increasing
and safe with concurrent writers (parallel subagents). The stream is capped (MAXLEN) and
expires after the ask: a client that falls further behind than the cap gets an
`events_expired` error instead of silently missing events.
"""

from uuid import UUID

from pydantic import BaseModel
from redis.asyncio import Redis

from driftline.agents.events import ASK_EVENT_ADAPTER, AskEvent

# KEYS[1] stream, KEYS[2] counter; ARGV: payload, maxlen, ttl_s
_APPEND = """
local n = redis.call('INCR', KEYS[2])
redis.call('XADD', KEYS[1], 'MAXLEN', ARGV[2], n .. '-0', 'data', ARGV[1])
redis.call('EXPIRE', KEYS[1], ARGV[3])
redis.call('EXPIRE', KEYS[2], ARGV[3])
return n
"""


def stream_key(job_id: UUID | str) -> str:
    return f"events:ask:{job_id}"


def _counter_key(job_id: UUID | str) -> str:
    return f"events:ask:{job_id}:seq"


def _seq(entry_id: str) -> int:
    return int(entry_id.split("-", 1)[0])


class AskEventLog:
    def __init__(self, redis: Redis, *, maxlen: int = 10_000, ttl_s: int = 24 * 3600) -> None:
        self._redis = redis
        self._maxlen = maxlen
        self._ttl_s = ttl_s
        self._append = redis.register_script(_APPEND)

    async def append(self, job_id: UUID | str, event: BaseModel) -> int:
        """Store one event; returns its id (1, 2, 3, ... per ask)."""
        payload = event.model_dump_json()
        n = await self._append(
            keys=[stream_key(job_id), _counter_key(job_id)],
            args=[payload, self._maxlen, self._ttl_s],
        )
        return int(n)

    async def read(
        self, job_id: UUID | str, *, after: int = 0, count: int = 100, block_ms: int | None = None
    ) -> list[tuple[int, AskEvent]]:
        """Events with id > `after`, oldest first. With `block_ms`, wait up to that long
        for the first one (0 waits forever, None does not wait)."""
        resp = await self._redis.xread(
            {stream_key(job_id): f"{after}-0"}, count=count, block=block_ms
        )
        if not resp:
            return []
        return [
            (_seq(entry_id), ASK_EVENT_ADAPTER.validate_json(fields["data"]))
            for entry_id, fields in resp[0][1]
        ]

    async def first_id(self, job_id: UUID | str) -> int | None:
        """The oldest id still stored, or None when nothing is stored."""
        entries = await self._redis.xrange(stream_key(job_id), count=1)
        return _seq(entries[0][0]) if entries else None

    async def last_id(self, job_id: UUID | str) -> int:
        value = await self._redis.get(_counter_key(job_id))
        return int(value) if value else 0

    async def has_gap(self, job_id: UUID | str, after: int) -> bool:
        """True when events after `after` were already trimmed away."""
        first = await self.first_id(job_id)
        if first is None:
            return after < await self.last_id(job_id)
        return first > after + 1
