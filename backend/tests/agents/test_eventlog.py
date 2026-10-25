import asyncio
import re
from uuid import uuid4

import redis.asyncio as aioredis

from driftline.agents.eventlog import AskEventLog, stream_key
from driftline.agents.events import ASK_EVENT_ADAPTER, ErrorEvent, StepEvent, TokenEvent
from driftline.gateway.sse import HEARTBEAT, ask_event_stream, format_event, parse_last_event_id


async def test_ids_are_sequential_per_ask_and_events_round_trip(redis_client):
    log = AskEventLog(redis_client)
    job, other = uuid4(), uuid4()
    assert await log.append(job, StepEvent(node="plan", status="started")) == 1
    assert await log.append(job, TokenEvent(text="Check")) == 2
    assert await log.append(other, TokenEvent(text="x")) == 1
    events = await log.read(job)
    assert [n for n, _ in events] == [1, 2]
    assert events[0][1] == StepEvent(node="plan", status="started")
    assert events[1][1] == TokenEvent(text="Check")
    assert [n for n, _ in await log.read(job, after=1)] == [2]
    assert await log.read(job, after=2) == []
    assert await log.last_id(job) == 2


async def test_concurrent_writers_get_unique_increasing_ids(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()
    ids = await asyncio.gather(*(log.append(job, TokenEvent(text=str(i))) for i in range(50)))
    assert sorted(ids) == list(range(1, 51))
    stored = await log.read(job, count=100)
    assert [n for n, _ in stored] == list(range(1, 51))


async def test_concurrent_writers_on_separate_clients_never_reuse_an_id(redis_url):
    clients = [aioredis.from_url(redis_url, decode_responses=True) for _ in range(3)]
    try:
        logs = [AskEventLog(c) for c in clients]
        job = uuid4()
        ids = await asyncio.gather(
            *(logs[i % 3].append(job, TokenEvent(text=str(i))) for i in range(60))
        )
        assert sorted(ids) == list(range(1, 61))
        stored = await logs[0].read(job, count=100)
        assert [n for n, _ in stored] == list(range(1, 61))
    finally:
        for c in clients:
            await c.aclose()


async def test_blocking_read_wakes_up_on_append(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()
    reader = asyncio.create_task(log.read(job, after=0, block_ms=5000))
    await asyncio.sleep(0.05)
    await log.append(job, TokenEvent(text="late"))
    [(n, event)] = await asyncio.wait_for(reader, 5)
    assert (n, event.text) == (1, "late")
    assert await log.read(job, after=1, block_ms=50) == []  # times out empty


async def test_replay_after_an_id_honours_count(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()
    for i in range(6):
        await log.append(job, TokenEvent(text=str(i)))
    page = await log.read(job, after=2, count=2)
    assert [(n, e.text) for n, e in page] == [(3, "2"), (4, "3")]
    assert await log.last_id(uuid4()) == 0


async def test_stream_is_capped_and_gaps_are_detected(redis_client):
    log = AskEventLog(redis_client, maxlen=5)
    job = uuid4()
    for i in range(20):
        await log.append(job, TokenEvent(text=str(i)))
    assert await log.first_id(job) == 16
    assert await log.has_gap(job, after=3)
    assert not await log.has_gap(job, after=15)
    assert [n for n, _ in await log.read(job, after=15)] == [16, 17, 18, 19, 20]
    assert await redis_client.ttl(stream_key(job)) > 0
    unknown = uuid4()
    assert await log.first_id(unknown) is None and not await log.has_gap(unknown, after=0)


async def test_gap_is_detected_when_the_whole_stream_is_gone(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()
    for i in range(3):
        await log.append(job, TokenEvent(text=str(i)))
    await redis_client.delete(stream_key(job))
    assert await log.first_id(job) is None
    assert await log.has_gap(job, after=1)
    assert not await log.has_gap(job, after=3)


async def test_gap_check_racing_the_first_append_never_reports_a_gap(redis_url):
    """A client checking `has_gap(after=0)` while the writer appends the first event must
    never see a gap: nothing was trimmed. Reading the oldest entry and the counter in two
    round trips lets the append land in between ("no entries" plus counter 1)."""
    checker = aioredis.from_url(redis_url, decode_responses=True)
    writer = aioredis.from_url(redis_url, decode_responses=True)
    try:
        check_log, write_log = AskEventLog(checker), AskEventLog(writer)
        false_gaps = 0
        for _ in range(20):
            jobs = [uuid4() for _ in range(25)]
            results = await asyncio.gather(
                *(check_log.has_gap(job, after=0) for job in jobs),
                *(write_log.append(job, TokenEvent(text="first")) for job in jobs),
            )
            false_gaps += sum(1 for gap in results[: len(jobs)] if gap)
        assert false_gaps == 0
    finally:
        await checker.aclose()
        await writer.aclose()


async def test_ttl_is_set_on_stream_and_counter_and_refreshed_on_append(redis_client):
    log = AskEventLog(redis_client, ttl_s=100)
    job = uuid4()
    await log.append(job, TokenEvent(text="a"))
    counter = f"{stream_key(job)}:seq"
    assert 0 < await redis_client.ttl(stream_key(job)) <= 100
    assert 0 < await redis_client.ttl(counter) <= 100
    await redis_client.expire(stream_key(job), 5)
    await redis_client.expire(counter, 5)
    await log.append(job, TokenEvent(text="b"))
    assert await redis_client.ttl(stream_key(job)) > 5
    assert await redis_client.ttl(counter) > 5


# --- SSE framing -------------------------------------------------------------


def _parse_sse(text: str) -> list[dict[str, str]]:
    """Minimal WHATWG event-stream parser: lines end in CRLF, LF or CR."""
    frames: list[dict[str, str]] = []
    current: dict[str, str] = {}
    data: list[str] = []
    for line in re.split(r"\r\n|\r|\n", text):
        if line == "":
            if data or current:
                if data:
                    current["data"] = "\n".join(data)
                frames.append(current)
            current, data = {}, []
            continue
        if line.startswith(":"):
            current.setdefault("comment", line[1:].strip())
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "data":
            data.append(value)
        else:
            current[name] = value
    return frames


def test_format_event_frames_id_type_and_json_data():
    frame = format_event(TokenEvent(text="hi"), seq=3)
    assert frame == 'id: 3\nevent: token\ndata: {"type":"token","text":"hi"}\n\n'
    assert format_event(TokenEvent(text="hi")).startswith("event: token\n")


def test_multiline_text_stays_in_one_data_line_and_round_trips():
    text = "line one\nline two\r\nline three\rend  \x00"
    frame = format_event(TokenEvent(text=text), seq=7)
    [parsed] = _parse_sse(frame)
    assert parsed["id"] == "7" and parsed["event"] == "token"
    assert ASK_EVENT_ADAPTER.validate_json(parsed["data"]) == TokenEvent(text=text)
    assert frame.count("\n") == 4 and "\r" not in frame


def test_parse_last_event_id():
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("") == 0
    assert parse_last_event_id("7") == 7
    assert parse_last_event_id("-3") == 0
    assert parse_last_event_id("abc") == 0
    assert parse_last_event_id("1e3") == 0


async def _collect(gen, limit=20, timeout=5):
    async def run():
        frames = []
        async for frame in gen:
            frames.append(frame)
            if len(frames) >= limit:
                break
        return frames

    return await asyncio.wait_for(run(), timeout)


async def _never_finished():
    return None


async def test_stream_replays_only_events_after_the_id_and_stops_at_terminal(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()
    await log.append(job, StepEvent(node="plan", status="started"))
    await log.append(job, TokenEvent(text="a"))
    await log.append(job, ErrorEvent(code="boom", retryable=False))
    await log.append(job, TokenEvent(text="after terminal"))
    frames = await _collect(
        ask_event_stream(log, job, after=1, heartbeat_s=0.05, finished=_never_finished)
    )
    parsed = [_parse_sse(f)[0] for f in frames]
    assert [(p["id"], p["event"]) for p in parsed] == [("2", "token"), ("3", "error")]


async def test_stream_follows_live_events(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()

    async def produce():
        await asyncio.sleep(0.1)
        await log.append(job, TokenEvent(text="live"))
        await log.append(job, ErrorEvent(code="done", retryable=False))

    producer = asyncio.create_task(produce())
    frames = await _collect(
        ask_event_stream(log, job, after=0, heartbeat_s=0.05, finished=_never_finished)
    )
    await producer
    assert frames[0] == HEARTBEAT
    ids = [_parse_sse(f)[0]["id"] for f in frames if f != HEARTBEAT]
    assert ids == ["1", "2"]


async def test_client_behind_the_cap_gets_events_expired(redis_client):
    log = AskEventLog(redis_client, maxlen=3)
    job = uuid4()
    for i in range(6):
        await log.append(job, TokenEvent(text=str(i)))
    frames = await _collect(
        ask_event_stream(log, job, after=1, heartbeat_s=0.05, finished=_never_finished)
    )
    [parsed] = [_parse_sse(f)[0] for f in frames]
    assert parsed["event"] == "error" and "id" not in parsed
    assert ASK_EVENT_ADAPTER.validate_json(parsed["data"]).code == "events_expired"


async def test_trimming_while_streaming_gives_events_expired_not_a_silent_skip(redis_client):
    log = AskEventLog(redis_client, maxlen=2)
    job = uuid4()
    await log.append(job, TokenEvent(text="1"))
    await log.append(job, TokenEvent(text="2"))
    stream = ask_event_stream(
        log, job, after=0, heartbeat_s=0.05, finished=_never_finished, batch=1
    )
    first = await asyncio.wait_for(anext(stream), 5)
    assert _parse_sse(first)[0]["id"] == "1"
    await log.append(job, TokenEvent(text="3"))
    await log.append(job, TokenEvent(text="4"))  # event 2 is trimmed away
    rest = await _collect(stream)
    [parsed] = [_parse_sse(f)[0] for f in rest]
    assert ASK_EVENT_ADAPTER.validate_json(parsed["data"]).code == "events_expired"


async def test_finished_job_ends_the_stream_with_its_outcome(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()
    calls = 0

    async def finished():
        nonlocal calls
        calls += 1
        return ErrorEvent(code="job_failed", retryable=False) if calls > 1 else None

    frames = await _collect(
        ask_event_stream(log, job, after=0, heartbeat_s=0.05, finished=finished)
    )
    assert frames[0] == HEARTBEAT
    [parsed] = [_parse_sse(f)[0] for f in frames[1:]]
    assert "id" not in parsed
    assert ASK_EVENT_ADAPTER.validate_json(parsed["data"]).code == "job_failed"


async def test_events_appended_just_before_finish_are_not_lost(redis_client):
    log = AskEventLog(redis_client)
    job = uuid4()

    async def finished():
        # The worker appends its last events, then marks the job done, between the
        # gateway's empty read and this check.
        if await log.last_id(job) == 0:
            await log.append(job, TokenEvent(text="tail"))
            await log.append(job, ErrorEvent(code="done", retryable=False))
        return ErrorEvent(code="job_failed", retryable=False)

    frames = await _collect(
        ask_event_stream(log, job, after=0, heartbeat_s=0.05, finished=finished)
    )
    parsed = [_parse_sse(f)[0] for f in frames]
    assert [(p.get("id"), p["event"]) for p in parsed] == [("1", "token"), ("2", "error")]
