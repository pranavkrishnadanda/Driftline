import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ConsumeResult:
    processed: int = 0
    failed: int = 0
    dead_lettered: int = 0


class StreamBus:
    """At-least-once work distribution over Redis Streams consumer groups."""

    def __init__(self, redis: Redis, *, max_deliveries: int = 3, dlq_prefix: str = "dlq:") -> None:
        self._redis = redis
        self._max_deliveries = max_deliveries
        self._dlq_prefix = dlq_prefix

    async def publish(self, stream: str, payload: dict[str, Any]) -> str:
        return await self._redis.xadd(stream, {"data": json.dumps(payload)})

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_once(
        self, stream: str, group: str, consumer: str, handler: Handler,
        *, count: int = 10, block_ms: int = 100,
    ) -> ConsumeResult:
        resp = await self._redis.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        entries = resp[0][1] if resp else []
        return await self._process(stream, group, entries, handler)

    async def reclaim_once(
        self, stream: str, group: str, consumer: str, handler: Handler,
        *, min_idle_ms: int, count: int = 10,
    ) -> ConsumeResult:
        resp = await self._redis.xautoclaim(
            stream, group, consumer, min_idle_time=min_idle_ms, start_id="0-0", count=count
        )
        return await self._process(stream, group, resp[1], handler)

    async def _process(self, stream, group, entries, handler) -> ConsumeResult:
        processed = failed = dead = 0
        for msg_id, fields in entries:
            if fields is None:  # entry was deleted from the stream while pending
                await self._redis.xack(stream, group, msg_id)
                continue
            try:
                payload = json.loads(fields["data"])
                await handler(msg_id, payload)
            except Exception as exc:  # noqa: BLE001 - any handler failure counts as a failed delivery
                if await self._delivery_count(stream, group, msg_id) >= self._max_deliveries:
                    await self._redis.xadd(
                        f"{self._dlq_prefix}{stream}",
                        {"data": fields.get("data", ""), "source_id": msg_id, "error": repr(exc)},
                    )
                    await self._redis.xack(stream, group, msg_id)
                    dead += 1
                else:
                    failed += 1
                continue
            await self._redis.xack(stream, group, msg_id)
            processed += 1
        return ConsumeResult(processed=processed, failed=failed, dead_lettered=dead)

    async def _delivery_count(self, stream: str, group: str, msg_id: str) -> int:
        info = await self._redis.xpending_range(stream, group, min=msg_id, max=msg_id, count=1)
        return int(info[0]["times_delivered"]) if info else 0
