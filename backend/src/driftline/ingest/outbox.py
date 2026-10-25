"""Transactional outbox relay: committed outbox rows -> Redis Streams, at least once."""

import asyncio
import json

import asyncpg

from driftline.clock import Clock, SystemClock
from driftline.streams.bus import StreamBus

# Which streams each outbox topic fans out to. P4 adds "drift" to version.created.
TOPIC_STREAMS: dict[str, tuple[str, ...]] = {"version.created": ("embed",)}


def streams_for(topic: str) -> tuple[str, ...]:
    return TOPIC_STREAMS.get(topic, (topic,))


class OutboxRelay:
    def __init__(self, pool: asyncpg.Pool, bus: StreamBus, *, batch_size: int = 100) -> None:
        self._pool = pool
        self._bus = bus
        self._batch_size = batch_size

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
            for stream in streams_for(row["topic"]):
                await self._bus.publish(stream, payload)
        return [row["id"] for row in rows]

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
