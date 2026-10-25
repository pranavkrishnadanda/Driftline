"""Server-sent events: framing, replayable event streams and stream slots (spec section 8).

The per-ask stream (`ask_event_stream`) and the per-tenant alert stream
(`alert_event_stream`) are one loop (`replay_stream`) over an event log: replay after
Last-Event-ID, follow live events with heartbeats, and report `events_expired` when the
client fell further behind than the log keeps. Both hold one of the gateway's
`sse_max_connections` slots for as long as they are open (`open_stream`).
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from driftline.agents.events import ErrorEvent, is_terminal

HEARTBEAT = ": ping\n\n"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class ReplayLog(Protocol):
    """What a replayable stream needs from an event log (`EventLog`, `AlertLog`)."""

    async def read(
        self, scope_id: Any, *, after: int = 0, count: int = 100, block_ms: int | None = None
    ) -> list[tuple[int, Any]]: ...

    async def last_id(self, scope_id: Any) -> int: ...

    async def has_gap(self, scope_id: Any, after: int) -> bool: ...


def format_event(event: BaseModel, *, seq: int | None = None) -> str:
    """One SSE frame. Gateway-made events (no `seq`) carry no `id:`, so they never move
    the client's Last-Event-ID."""
    head = f"id: {seq}\n" if seq is not None else ""
    return f"{head}event: {event.type}\ndata: {event.model_dump_json()}\n\n"


def parse_last_event_id(value: str | None) -> int:
    try:
        return max(0, int(value)) if value else 0
    except ValueError:
        return 0


async def resume_point(log: ReplayLog, scope_id: Any, last_event_id: str | None) -> int:
    """The id to replay after. A Last-Event-ID ahead of the log (a stale tab, a bogus
    header) would only ever see heartbeats; clamp it so the client gets the next real
    events."""
    return min(parse_last_event_id(last_event_id), await log.last_id(scope_id))


def _expired(message: str) -> str:
    return format_event(ErrorEvent(code="events_expired", retryable=False, message=message))


async def _never_finished() -> None:
    return None


async def replay_stream(
    log: ReplayLog,
    scope_id: Any,
    *,
    after: int,
    heartbeat_s: float,
    expired_message: Callable[[int], str],
    finished: Callable[[], Awaitable[BaseModel | None]] = _never_finished,
    batch: int = 100,
) -> AsyncIterator[str]:
    """Replay events after `after`, then follow live ones until a terminal event.

    Reads block for at most `heartbeat_s`; an idle wait sends a heartbeat comment. A
    client that asks for events already trimmed from the log gets `events_expired`, both
    up front and when trimming overtakes it mid-stream (ids are gap-free, so any jump
    means lost events). When the log has nothing more and the scope is over (`finished`
    returns its outcome), events appended just before it finished are drained first,
    then that outcome is sent and the stream ends. With the default `finished`, the
    stream only ends when the client goes away.
    """
    if await log.has_gap(scope_id, after):
        yield _expired(expired_message(after))
        return
    while True:
        events = await log.read(
            scope_id, after=after, count=batch, block_ms=int(heartbeat_s * 1000)
        )
        if not events:
            outcome = await finished()
            if outcome is None:
                yield HEARTBEAT
                continue
            # The writer may have appended its last events between our read and the
            # check; send them (they may end with the real terminal event) before the
            # outcome.
            events = await log.read(scope_id, after=after, count=batch)
            if not events:
                yield format_event(outcome)
                return
        for seq, event in events:
            if seq != after + 1:
                yield _expired(expired_message(after))
                return
            yield format_event(event, seq=seq)
            after = seq
            if is_terminal(event):
                return


def ask_event_stream(
    log: ReplayLog,
    job_id: UUID,
    *,
    after: int,
    heartbeat_s: float,
    finished: Callable[[], Awaitable[BaseModel | None]],
    batch: int = 100,
) -> AsyncIterator[str]:
    """One ask's events, ending after its terminal event (or the job's outcome)."""
    return replay_stream(
        log,
        job_id,
        after=after,
        heartbeat_s=heartbeat_s,
        finished=finished,
        batch=batch,
        expired_message=lambda n: f"events after {n} are no longer stored; GET /v1/jobs/{job_id}",
    )


def alert_event_stream(
    log: ReplayLog, tenant_id: UUID, *, after: int, heartbeat_s: float, batch: int = 100
) -> AsyncIterator[str]:
    """A tenant's drift alerts. Open-ended: alerts have no terminal event."""
    return replay_stream(
        log,
        tenant_id,
        after=after,
        heartbeat_s=heartbeat_s,
        batch=batch,
        expired_message=lambda n: f"alerts after {n} are no longer stored; GET /v1/drift/events",
    )


class _SlotStreamingResponse(StreamingResponse):
    """Releases its SSE slot when the response ends, however it ends.

    Releasing in the body generator's `finally` is not enough: a client that disconnects
    at once can get the response cancelled before the generator first runs, and a
    generator that never started never runs its `finally`, so the slot would leak.
    """

    def __init__(
        self, content: AsyncGenerator[str, None], *, release: Callable[[], None], **kw: Any
    ) -> None:
        super().__init__(content, **kw)
        self._content = content
        self._release = release

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Release first: in a cancelled scope every further await raises again.
            self._release()
            await self._content.aclose()


def check_stream_slot(slots: asyncio.Semaphore, retry_after_s: int) -> None:
    """503 with Retry-After when every SSE slot is taken (`sse_max_connections`)."""
    if slots.locked():
        raise HTTPException(
            status_code=503,
            detail={"code": "too_many_streams"},
            headers={"Retry-After": str(retry_after_s)},
        )


async def open_stream(
    slots: asyncio.Semaphore, content: AsyncGenerator[str, None]
) -> StreamingResponse:
    """Take an SSE slot and return the response that gives it back when it ends.

    Call `check_stream_slot` and do every fallible step before this: nothing may fail
    between acquiring the slot and returning the response that releases it.
    """
    await slots.acquire()
    return _SlotStreamingResponse(
        content, release=slots.release, media_type="text/event-stream", headers=SSE_HEADERS
    )


def sse_responses(schema_ref: str, *, ends: str, not_found: str) -> dict[int | str, dict[str, Any]]:
    """OpenAPI responses for an SSE route whose events match `schema_ref`."""
    return {
        200: {
            "description": "Server-sent events: `id: <n>`, `event: <type>`, `data: <JSON>`; "
            f"`: ping` heartbeats; {ends} "
            "Reconnect with Last-Event-ID to replay missed events.",
            "content": {"text/event-stream": {"schema": {"$ref": schema_ref}}},
        },
        404: {"description": not_found},
        503: {"description": "too many open streams"},
    }
