"""The drift processes (spec section 7).

- `DriftWorker` consumes `version.created` events from the `drift` stream (consumer
  group `drift`, fanned out by the outbox relay) and runs the drift engine on each.
  Like the ingest and agent workers it reclaims messages stalled on a dead consumer
  (XAUTOCLAIM after 60 s), and the bus dead-letters a message to `dlq:drift` on its
  3rd failed delivery. The engine is idempotent per (answer, new version, claim), so a
  redelivered or reclaimed event records nothing twice.
- `SourcePoller` is the scheduler: it enqueues ingest jobs for every source whose
  `schedule` is due, and marks a source `stale_source` once `stale_after_failures`
  fetches in a row failed (discoveries here and ingest fetches share one streak,
  `driftline.ingest.worker.record_fetch_failure`). Only a successful ingest fetch
  resets the streak or revives a stale source; a successful discovery does neither.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg
from redis.asyncio import Redis

from driftline.clock import Clock
from driftline.drift.engine import DriftEngine
from driftline.ingest.worker import ConnectorFactory, enqueue_ingest, record_fetch_failure
from driftline.streams.bus import StreamBus, keepalive_interval_ms

logger = logging.getLogger(__name__)

DRIFT_STREAM = "drift"
DRIFT_GROUP = "drift"
RECLAIM_IDLE_MS = 60_000  # spec section 3: reclaim stalled messages after 60 s
MAX_DELIVERIES = 3  # StreamBus's default: the 3rd failed delivery is dead-lettered


class DriftWorker:
    def __init__(
        self,
        bus: StreamBus,
        engine: DriftEngine,
        clock: Clock,
        *,
        redis: Redis,
        consumer: str,
        reclaim_idle_ms: int = RECLAIM_IDLE_MS,
        max_deliveries: int = MAX_DELIVERIES,
    ) -> None:
        self._bus = bus
        self._engine = engine
        self._clock = clock
        self._redis = redis
        self._consumer = consumer
        self._reclaim_idle_ms = reclaim_idle_ms
        self._max_deliveries = max_deliveries  # must match the bus's, see _is_last_delivery

    async def setup(self) -> None:
        await self._bus.ensure_group(DRIFT_STREAM, DRIFT_GROUP)

    async def _is_last_delivery(self, msg_id: str) -> bool:
        """True when the bus will dead-letter this message if the handler fails now."""
        info = await self._redis.xpending_range(
            DRIFT_STREAM, DRIFT_GROUP, min=msg_id, max=msg_id, count=1
        )
        return bool(info) and int(info[0]["times_delivered"]) >= self._max_deliveries

    async def handle(self, msg_id: str, payload: dict[str, Any]) -> None:
        try:
            await self._engine.handle_version_created(payload)
        except Exception:
            # The message stays pending and is retried. On the last delivery the bus
            # dead-letters it: the document's watched answers are then NOT re-checked
            # until its next version, so say so loudly.
            if await self._is_last_delivery(msg_id):
                logger.exception(
                    "drift event %s (outbox %s, document %s) failed %d times; "
                    "dead-lettered to dlq:%s",
                    msg_id,
                    payload.get("event_id"),
                    payload.get("document_id"),
                    self._max_deliveries,
                    DRIFT_STREAM,
                )
            else:
                logger.warning("drift event %s failed; will retry", msg_id, exc_info=True)
            raise

    async def run_once(self, *, block_ms: int = 100) -> int:
        """One read plus one reclaim pass; returns messages processed. One message at a
        time: an event can run several judge calls, and messages held unprocessed in a
        local batch would go idle and be reclaimed by another worker. The claim is kept
        alive while the handler runs: an event that re-verifies many claims can outlast
        the reclaim window."""
        keepalive_ms = keepalive_interval_ms(self._reclaim_idle_ms)
        result = await self._bus.consume_once(
            DRIFT_STREAM,
            DRIFT_GROUP,
            self._consumer,
            self.handle,
            count=1,
            block_ms=block_ms,
            keepalive_ms=keepalive_ms,
        )
        reclaimed = await self._bus.reclaim_once(
            DRIFT_STREAM,
            DRIFT_GROUP,
            self._consumer,
            self.handle,
            min_idle_ms=self._reclaim_idle_ms,
            count=1,
            keepalive_ms=keepalive_ms,
        )
        return result.processed + reclaimed.processed

    async def run(self, stop: asyncio.Event) -> None:
        await self.setup()
        while not stop.is_set():
            if await self.run_once(block_ms=1000) == 0:
                await self._clock.sleep(0.05)


# --- scheduler -----------------------------------------------------------------------

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86_400}
_ALIASES = {"@hourly": 3600, "@daily": 86_400, "@weekly": 7 * 86_400}
_INTERVAL = re.compile(r"(\d+)([smhd]?)")


def parse_schedule(schedule: str) -> float:
    """A source's `schedule` as a polling interval in seconds: `@hourly`, `@daily`,
    `@weekly`, or a positive count with an optional unit (`90`, `45s`, `15m`, `6h`, `1d`).
    Raises ValueError for anything else."""
    text = schedule.strip().lower()
    if text in _ALIASES:
        return float(_ALIASES[text])
    match = _INTERVAL.fullmatch(text)
    if match is None or int(match[1]) <= 0:
        raise ValueError(f"invalid source schedule {schedule!r}")
    return float(int(match[1]) * _UNITS[match[2] or "s"])


@dataclass
class PollResult:
    polled: list[UUID] = field(default_factory=list)  # discovered and enqueued
    failed: list[UUID] = field(default_factory=list)  # discovery failed this pass
    stale: list[UUID] = field(default_factory=list)  # marked stale_source this pass
    jobs: list[UUID] = field(default_factory=list)


class SourcePoller:
    """Enqueues ingest jobs for due sources, through the same path as
    `python -m driftline.ingest enqueue --discover`.

    A source is due when it has a `schedule`, is not `paused`, and
    `last_polled_at + interval <= now` (or it was never polled). Each pass claims a due
    source by moving `last_polled_at` to now with a compare-and-set, so concurrent
    pollers enqueue it once. `stale_source` sources are still polled, so their next
    successful fetch (in the ingest worker) can make them `active` again.

    A failed discovery still advances `last_polled_at`: a broken source is retried at its
    own cadence, not hammered every pass. The consecutive-failure streak lives in Redis
    (`poll:failures:{source}`) and is shared with the ingest worker's fetch failures. A
    failed discovery counts towards it, but a successful one does not reset it, nor
    does it make a stale source `active`: listing documents proves nothing about
    fetching them, and a source whose discovery works but whose fetches always fail
    must still go stale. Only a successful fetch resets the streak.
    """

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        bus: StreamBus,
        redis: Redis,
        connector_factory: ConnectorFactory,
        clock: Clock,
        stale_after_failures: int = 3,
        discover_timeout_s: float = 300.0,
    ) -> None:
        if stale_after_failures < 1:
            raise ValueError("stale_after_failures must be at least 1")
        self._pool = pool
        self._bus = bus
        self._redis = redis
        self._factory = connector_factory
        self._clock = clock
        self._stale_after = stale_after_failures
        self._discover_timeout_s = discover_timeout_s

    async def _due(self, now: float) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, kind, config, schedule, last_polled_at FROM sources "
                "WHERE schedule IS NOT NULL AND status <> 'paused' ORDER BY id"
            )
        due = []
        for row in rows:
            try:
                interval = parse_schedule(row["schedule"])
            except ValueError:
                logger.error("source %s: %r is not a schedule; skipped", row["id"], row["schedule"])
                continue
            last = row["last_polled_at"]
            if last is None or last.timestamp() + interval <= now:
                due.append(row)
        return due

    async def _claim(self, row: asyncpg.Record, polled_at: datetime) -> bool:
        async with self._pool.acquire() as conn:
            claimed = await conn.fetchval(
                "UPDATE sources SET last_polled_at = $2 "
                "WHERE id = $1 AND last_polled_at IS NOT DISTINCT FROM $3 RETURNING id",
                row["id"],
                polled_at,
                row["last_polled_at"],
            )
        return claimed is not None

    async def _unclaim(self, row: asyncpg.Record, polled_at: datetime) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE sources SET last_polled_at = $3 WHERE id = $1 AND last_polled_at = $2",
                row["id"],
                polled_at,
                row["last_polled_at"],
            )

    async def _record_failure(self, source_id: UUID, result: PollResult) -> None:
        result.failed.append(source_id)
        if await record_fetch_failure(
            self._pool, self._redis, source_id, stale_after=self._stale_after
        ):
            logger.warning(
                "source %s failed %d fetches in a row: stale_source", source_id, self._stale_after
            )
            result.stale.append(source_id)

    async def poll_once(self) -> PollResult:
        result = PollResult()
        now = self._clock.now()
        polled_at = datetime.fromtimestamp(now, tz=UTC)
        for row in await self._due(now):
            source_id = row["id"]
            if not await self._claim(row, polled_at):
                continue  # another poller took it
            try:
                connector = self._factory(row["kind"], json.loads(row["config"]))
                ids = await asyncio.wait_for(
                    connector.list_external_ids(), timeout=self._discover_timeout_s
                )
            except Exception:
                logger.warning("source %s: discovery failed", source_id, exc_info=True)
                await self._record_failure(source_id, result)
                continue
            try:
                for external_id in ids:
                    result.jobs.append(
                        await enqueue_ingest(
                            self._pool, self._bus, source_id=source_id, external_id=external_id
                        )
                    )
            except Exception:
                await self._unclaim(row, polled_at)  # let the next pass retry it
                raise
            result.polled.append(source_id)
        return result

    async def run(self, stop: asyncio.Event, *, interval_s: float) -> None:
        while not stop.is_set():
            await self.poll_once()
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except TimeoutError:
                pass
