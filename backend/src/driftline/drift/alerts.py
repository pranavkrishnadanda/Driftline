"""Per-tenant drift alert log on `events:alerts:{tenant_id}` (P4).

The outbox relay appends each `drift.alert` row here as an `AlertEvent`, deduped on the
outbox event id (the relay delivers at least once). The alert SSE stream replays from it
by `Last-Event-ID`, with the same monotonic ids, MAXLEN cap, TTL and gap detection as the
per-ask log, because it is the same `EventLog` with a different key and event union.
"""

from uuid import UUID

from redis.asyncio import Redis

from driftline.agents.eventlog import EventLog
from driftline.agents.events import ALERT_EVENT_ADAPTER, AlertEvent, AlertStreamEvent


def alert_stream_key(tenant_id: UUID | str) -> str:
    return f"events:alerts:{tenant_id}"


class AlertLog:
    def __init__(self, redis: Redis, *, maxlen: int = 10_000, ttl_s: int = 30 * 24 * 3600) -> None:
        self._log = EventLog(
            redis, key=alert_stream_key, adapter=ALERT_EVENT_ADAPTER, maxlen=maxlen, ttl_s=ttl_s
        )

    async def append(
        self, tenant_id: UUID | str, event: AlertEvent, *, dedupe_id: str | None = None
    ) -> int:
        """Store one alert for the tenant; returns its id. A repeated `dedupe_id` (the
        outbox event id) returns the original id without storing a duplicate."""
        return await self._log.append(tenant_id, event, dedupe_id=dedupe_id)

    async def read(
        self,
        tenant_id: UUID | str,
        *,
        after: int = 0,
        count: int = 100,
        block_ms: int | None = None,
    ) -> list[tuple[int, AlertStreamEvent]]:
        return await self._log.read(tenant_id, after=after, count=count, block_ms=block_ms)

    async def first_id(self, tenant_id: UUID | str) -> int | None:
        return await self._log.first_id(tenant_id)

    async def last_id(self, tenant_id: UUID | str) -> int:
        return await self._log.last_id(tenant_id)

    async def has_gap(self, tenant_id: UUID | str, after: int) -> bool:
        return await self._log.has_gap(tenant_id, after)
