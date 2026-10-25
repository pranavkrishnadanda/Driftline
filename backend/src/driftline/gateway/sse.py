"""Server-sent events framing and the per-ask event stream (spec section 8)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

from pydantic import BaseModel

from driftline.agents.eventlog import AskEventLog
from driftline.agents.events import ErrorEvent, is_terminal

HEARTBEAT = ": ping\n\n"


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


def _expired(job_id: UUID, after: int) -> str:
    return format_event(
        ErrorEvent(
            code="events_expired",
            retryable=False,
            message=f"events after {after} are no longer stored; GET /v1/jobs/{job_id}",
        )
    )


async def ask_event_stream(
    log: AskEventLog,
    job_id: UUID,
    *,
    after: int,
    heartbeat_s: float,
    finished: Callable[[], Awaitable[BaseModel | None]],
    batch: int = 100,
) -> AsyncIterator[str]:
    """Replay events after `after`, then follow live ones until a terminal event.

    Reads block for at most `heartbeat_s`; an idle wait sends a heartbeat comment. A
    client that asks for events already trimmed from the log gets `events_expired`, both
    up front and when trimming overtakes it mid-stream (ids are gap-free, so any jump
    means lost events). When the log has nothing more and the job is over (`finished`
    returns its outcome, built from the database), events appended just before the job
    finished are drained first, then that outcome is sent and the stream ends.
    """
    if await log.has_gap(job_id, after):
        yield _expired(job_id, after)
        return
    while True:
        events = await log.read(job_id, after=after, count=batch, block_ms=int(heartbeat_s * 1000))
        if not events:
            outcome = await finished()
            if outcome is None:
                yield HEARTBEAT
                continue
            # The worker may have appended its last events between our read and the
            # check; send them (they may end with the real terminal event) before the
            # database outcome.
            events = await log.read(job_id, after=after, count=batch)
            if not events:
                yield format_event(outcome)
                return
        for seq, event in events:
            if seq != after + 1:
                yield _expired(job_id, after)
                return
            yield format_event(event, seq=seq)
            after = seq
            if is_terminal(event):
                return
