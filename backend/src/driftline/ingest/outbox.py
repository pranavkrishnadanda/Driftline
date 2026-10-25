"""Transactional outbox relay: committed outbox rows -> Redis Streams, at least once."""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from pydantic import ValidationError

from driftline.agents.events import AlertEvent
from driftline.clock import Clock, SystemClock
from driftline.drift.alerts import AlertLog
from driftline.streams.bus import StreamBus

logger = logging.getLogger(__name__)

ALERT_TOPIC = "drift.alert"

# Which streams each outbox topic fans out to; a topic not listed here goes to a stream
# named after it. "drift.alert" maps to no static stream: each alert goes to its tenant's
# alert log (events:alerts:{tenant}), see `OutboxRelay._publish_alert`.
TOPIC_STREAMS: dict[str, tuple[str, ...]] = {
    "version.created": ("embed", "drift"),
    ALERT_TOPIC: (),
}


def streams_for(topic: str) -> tuple[str, ...]:
    return TOPIC_STREAMS.get(topic, (topic,))


class _AlertRow(AlertEvent):
    """A `drift.alert` outbox payload: the alert plus the tenant whose stream it goes to."""

    tenant_id: UUID


class OutboxRelay:
    def __init__(
        self,
        pool: asyncpg.Pool,
        bus: StreamBus,
        *,
        batch_size: int = 100,
        alerts: AlertLog | None = None,
    ) -> None:
        self._pool = pool
        self._bus = bus
        self._batch_size = batch_size
        # Default: the alert log on the bus's own Redis client, with AlertLog's defaults.
        self._alerts = alerts if alerts is not None else AlertLog(bus._redis)

    async def claim_and_publish(self, conn: asyncpg.Connection) -> list[int]:
        """Lock a batch of unpublished rows and publish them. Call inside a transaction.

        Rows stay locked (and other relays skip them) until the caller's transaction ends.
        If it ends without `mark_published` committing, the rows are published again
        later: delivery is at-least-once, and every message carries `event_id`.
        """
        rows = await conn.fetch(
            "SELECT id, topic, payload FROM outbox WHERE published_at IS NULL "
            "ORDER BY id LIMIT $1 FOR UPDATE SKIP LOCKED",
            self._batch_size,
        )
        for row in rows:
            payload = {**json.loads(row["payload"]), "event_id": row["id"], "topic": row["topic"]}
            if row["topic"] == ALERT_TOPIC:
                await self._publish_alert(payload)
            for stream in streams_for(row["topic"]):
                await self._bus.publish(stream, payload)
        return [row["id"] for row in rows]

    async def _publish_alert(self, payload: dict[str, Any]) -> None:
        """Append the alert to its tenant's log, deduped on the outbox event id, so a
        redelivered row never shows the tenant the same alert twice.

        A payload that does not validate can never succeed on a retry, so it is logged and
        dead-lettered to `dlq:drift.alert` (and its row is then marked published) rather
        than blocking every row behind it. Redis errors still propagate: the transaction
        rolls back and the row is retried later, as for any other topic.
        """
        try:
            row = _AlertRow.model_validate(payload)
        except ValidationError as exc:
            logger.error(
                "outbox row %s: invalid drift.alert payload, dead-lettered: %s",
                payload["event_id"],
                exc,
            )
            await self._bus.publish(f"dlq:{ALERT_TOPIC}", {**payload, "error": str(exc)})
            return
        event = AlertEvent.model_validate(row.model_dump(exclude={"tenant_id"}))
        await self._alerts.append(row.tenant_id, event, dedupe_id=str(payload["event_id"]))

    async def mark_published(self, conn: asyncpg.Connection, ids: list[int]) -> None:
        if ids:
            await conn.execute(
                "UPDATE outbox SET published_at = now() WHERE id = ANY($1::bigint[])", ids
            )

    async def relay_once(self) -> int:
        async with self._pool.acquire() as conn, conn.transaction():
            ids = await self.claim_and_publish(conn)
            await self.mark_published(conn, ids)
        return len(ids)

    async def run(
        self, stop: asyncio.Event, *, idle_sleep_s: float = 0.5, clock: Clock | None = None
    ) -> None:
        clock = clock or SystemClock()
        while not stop.is_set():
            if await self.relay_once() == 0:
                await clock.sleep(idle_sleep_s)
