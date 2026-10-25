import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import redis.asyncio as aioredis
from dbseed import seed_source
from livesrv import serve

from driftline.agents.eventlog import AskEventLog
from driftline.agents.events import ASK_EVENT_ADAPTER, FinalEvent, StepEvent, TokenEvent
from driftline.agents.schemas import AGENT_GROUP, AGENT_STREAM, AnswerSchema, AskJob
from driftline.config import Settings
from driftline.gateway.app import create_app
from driftline.gateway.contract import CONTRACT_PATH, build_contract

ANSWER = AnswerSchema(
    status="answered",
    answer="Check ALT monthly.",
    as_of=datetime(2024, 6, 1, tzinfo=UTC),
    confidence=1.0,
)


def settings_for(fresh_dsn, redis_url, **overrides) -> Settings:
    values = {"database_url": fresh_dsn, "redis_url": redis_url, "sse_heartbeat_s": 0.2}
    return Settings(_env_file=None, **(values | overrides))


@asynccontextmanager
async def asgi_client(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def frames(text: str) -> list[dict]:
    """Parse an SSE body into frames: {"id", "event", "data"} or {"comment"}."""
    out = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        frame: dict = {}
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            else:
                key, _, value = line.partition(": ")
                frame[key] = (
                    int(value) if key == "id" else json.loads(value) if key == "data" else value
                )
        out.append(frame)
    return out


# Every SSE read is bounded, so a stream that never ends fails the test instead of hanging.
READ_TIMEOUT_S = 10.0


class FrameReader:
    """Reads a live SSE response frame by frame; can be called repeatedly."""

    def __init__(self, response) -> None:
        self._chunks = response.aiter_text()
        self._buf = ""

    async def until(self, done) -> list[dict]:
        return await asyncio.wait_for(self._until(done), READ_TIMEOUT_S)

    async def _until(self, done) -> list[dict]:
        got: list[dict] = []
        while not done(got):
            while "\n\n" not in self._buf:
                self._buf += await anext(self._chunks)
            block, self._buf = self._buf.split("\n\n", 1)
            got.extend(frames(block + "\n\n"))
        return got


async def read_frames(response, until) -> list[dict]:
    """Read a live SSE response frame by frame until `until(frames)` is true.

    Only for a stream that is closed right after: the dropped body iterator is finalised
    by the garbage collector, and httpcore then closes the connection. To keep a stream
    open, hold a FrameReader instead.
    """
    return await FrameReader(response).until(until)


async def stream_status(client, url: str) -> int:
    """Open a stream, return its status code and close it (never reads the body)."""
    async with client.stream("GET", url) as r:
        return r.status_code


async def get(client, url: str, **kwargs) -> httpx.Response:
    """A whole (buffered) GET, bounded: an SSE body that never ends times out."""
    return await asyncio.wait_for(client.get(url, **kwargs), READ_TIMEOUT_S)


@pytest.fixture
async def tenant(fresh_conn):
    tenant_id, _ = await seed_source(fresh_conn, tenant="pharma")
    return tenant_id


async def new_job(fresh_conn, tenant, status="running"):
    return await fresh_conn.fetchval(
        "INSERT INTO jobs (tenant_id, kind, status) VALUES ($1, 'ask', $2) RETURNING id",
        tenant,
        status,
    )


async def test_post_ask_queues_a_job(fresh_dsn, redis_url, redis_client, fresh_conn, tenant):
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.post(
            "/v1/ask",
            json={
                "question": "How often is ALT checked?",
                "tenant": "pharma",
                "as_of": "2024-06-01T00:00:00Z",
                "source_kinds": ["upload"],
            },
        )
    assert r.status_code == 202
    body = r.json()
    job_id = body["job_id"]
    assert body["events_url"] == f"/v1/jobs/{job_id}/events"
    assert body["status_url"] == f"/v1/jobs/{job_id}"
    row = await fresh_conn.fetchrow(
        "SELECT kind, status, payload FROM jobs WHERE id = $1", uuid_of(job_id)
    )
    assert (row["kind"], row["status"]) == ("ask", "queued")
    assert json.loads(row["payload"])["question"] == "How often is ALT checked?"
    [(_, fields)] = await redis_client.xrange(AGENT_STREAM)
    job = AskJob.model_validate_json(fields["data"])
    assert (str(job.job_id), job.tenant_id, job.source_kinds) == (job_id, tenant, ["upload"])
    assert job.as_of == datetime(2024, 6, 1, tzinfo=UTC)


def uuid_of(value: str):
    from uuid import UUID

    return UUID(value)


async def test_unknown_tenant_is_404_and_bad_bodies_are_422(fresh_dsn, redis_url, tenant):
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        assert (
            await client.post("/v1/ask", json={"question": "q", "tenant": "nobody"})
        ).status_code == 404
        assert (
            await client.post("/v1/ask", json={"question": "", "tenant": "pharma"})
        ).status_code == 422
        bad_kind = {"question": "q", "tenant": "pharma", "source_kinds": ["wiki"]}
        assert (await client.post("/v1/ask", json=bad_kind)).status_code == 422


async def test_ask_returns_429_with_retry_after_when_backlog_exceeds_limit(
    fresh_dsn, redis_url, redis_client, fresh_conn, tenant
):
    settings = settings_for(fresh_dsn, redis_url, ask_max_pending=2, ask_retry_after_s=7)
    ask = {"question": "q", "tenant": "pharma"}
    async with asgi_client(settings) as client:
        codes = [(await client.post("/v1/ask", json=ask)).status_code for _ in range(3)]
        assert codes == [202, 202, 202]  # backlog 0, 1, 2: none exceeds 2
        rejected = await client.post("/v1/ask", json=ask)
        assert rejected.status_code == 429
        assert rejected.headers["retry-after"] == "7"
        assert rejected.json()["detail"] == {"code": "backpressure", "backlog": 3}
        assert await fresh_conn.fetchval("SELECT count(*) FROM jobs") == 3  # nothing written
        # A worker group drains the stream: the backlog falls and asks are accepted again.
        await redis_client.xgroup_create(AGENT_STREAM, AGENT_GROUP, id="0")
        entries = await redis_client.xreadgroup(AGENT_GROUP, "w1", {AGENT_STREAM: ">"}, count=10)
        assert (await client.post("/v1/ask", json=ask)).status_code == 429  # 3 pending + 0 lag
        await redis_client.xack(AGENT_STREAM, AGENT_GROUP, *[e for e, _ in entries[0][1]])
        assert (await client.post("/v1/ask", json=ask)).status_code == 202


async def test_job_status_reports_the_answer_and_cost(fresh_dsn, redis_url, fresh_conn, tenant):
    job = await new_job(fresh_conn, tenant, status="succeeded")
    await fresh_conn.execute(
        "INSERT INTO answers (tenant_id, question, as_of, body, job_id) VALUES ($1, 'q', now(), $2::jsonb, $3)",
        tenant,
        ANSWER.model_dump_json(),
        job,
    )
    await fresh_conn.execute(
        "INSERT INTO llm_calls (job_id, tenant_id, node, tier, provider, model, input_tokens, "
        "output_tokens, cost_usd, latency_ms) VALUES ($1, $2, 'draft', 'answer', 'anthropic', "
        "'claude-sonnet-5-5', 1000, 500, 0.007, 900)",
        job,
        tenant,
    )
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.get(f"/v1/jobs/{job}")
        missing = await client.get(f"/v1/jobs/{uuid4()}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded" and body["cost_usd"] == pytest.approx(0.007)
    assert body["answer"]["answer"] == "Check ALT monthly." and body["answer"]["answer_id"]
    assert missing.status_code == 404


async def test_sse_replays_the_log_and_ends_after_final(
    fresh_dsn, redis_url, redis_client, fresh_conn, tenant
):
    job = await new_job(fresh_conn, tenant)
    log = AskEventLog(redis_client)
    for event in (
        StepEvent(node="plan", status="started"),
        TokenEvent(text="Check"),
        FinalEvent(answer=ANSWER),
    ):
        await log.append(job, event)
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await get(client, f"/v1/jobs/{job}/events")
        alias = await get(client, f"/v1/ask/{job}/events", headers={"Last-Event-ID": "2"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    got = frames(r.text)
    assert [(f["id"], f["event"]) for f in got] == [(1, "step"), (2, "token"), (3, "final")]
    assert ASK_EVENT_ADAPTER.validate_python(got[2]["data"]).answer == ANSWER
    assert [f["id"] for f in frames(alias.text)] == [3]


async def test_a_client_connecting_as_the_job_starts_gets_event_1_not_events_expired(
    fresh_dsn, redis_url, redis_client, fresh_conn, tenant
):
    """The first event is appended the moment a client connects: the client must get ids
    1, 2, 3, never a false `events_expired`. A Redis MONITOR sees the gateway's up-front
    gap check reach Redis and appends the first event right then, racing the check."""
    jobs = {str(await new_job(fresh_conn, tenant)) for _ in range(40)}
    writer = aioredis.from_url(redis_url, decode_responses=True)
    log = AskEventLog(writer)
    started: set[str] = set()
    writes: list[asyncio.Task] = []

    async def write(job):
        for event in (StepEvent(node="plan", status="started"), TokenEvent(text="Check")):
            await log.append(job, event)
        await log.append(job, FinalEvent(answer=ANSWER))

    async def start_jobs_when_checked(monitor):
        # The gateway first reads the counter (`events:ask:{job}:seq`, the clamp); the
        # first command naming the stream key itself is the gap check.
        async for command in monitor.listen():
            for word in command["command"].split():
                job = word.removeprefix("events:ask:")
                if job in jobs and job not in started:
                    started.add(job)
                    writes.append(asyncio.create_task(write(job)))

    try:
        async with redis_client.monitor() as monitor:
            watcher = asyncio.create_task(start_jobs_when_checked(monitor))
            async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
                results = await asyncio.gather(
                    *(get(client, f"/v1/jobs/{job}/events") for job in jobs)
                )
            watcher.cancel()
        await asyncio.gather(*writes)
    finally:
        await writer.aclose()
    assert started == jobs
    bodies = [frames(r.text) for r in results]
    expired = [b for b in bodies if any(f.get("event") == "error" for f in b)]
    assert expired == []
    assert all([f["id"] for f in b if "id" in f] == [1, 2, 3] for b in bodies)


async def test_reconnect_with_last_event_id_replays_only_missed_events(
    fresh_dsn, redis_url, redis_client, fresh_conn, tenant
):
    job = await new_job(fresh_conn, tenant)
    log = AskEventLog(redis_client)
    for n in range(3):
        await log.append(job, TokenEvent(text=f"t{n}"))
    app = create_app(settings_for(fresh_dsn, redis_url))
    async with serve(app) as base, httpx.AsyncClient(base_url=base, timeout=10) as client:
        async with client.stream("GET", f"/v1/jobs/{job}/events") as r:
            first = await read_frames(r, lambda fs: sum("id" in f for f in fs) == 2)
        # The client dropped after id 2; the worker kept going meanwhile.
        await log.append(job, TokenEvent(text="t3"))
        await log.append(job, FinalEvent(answer=ANSWER))
        async with client.stream(
            "GET", f"/v1/jobs/{job}/events", headers={"Last-Event-ID": "2"}
        ) as r:
            second = await read_frames(r, lambda fs: any(f.get("event") == "final" for f in fs))
        by_query = (await get(client, f"/v1/jobs/{job}/events?last_event_id=4")).text
    assert [f["id"] for f in first if "id" in f] == [1, 2]
    assert [f["id"] for f in second if "id" in f] == [3, 4, 5]
    assert [f["data"].get("text") for f in second if "id" in f][:2] == ["t2", "t3"]
    assert [f["id"] for f in frames(by_query)] == [5]


async def test_live_events_arrive_while_connected_with_heartbeats(
    fresh_dsn, redis_url, redis_client, fresh_conn, tenant
):
    job = await new_job(fresh_conn, tenant)
    log = AskEventLog(redis_client)
    app = create_app(settings_for(fresh_dsn, redis_url, sse_heartbeat_s=0.1))
    async with (
        serve(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10) as client,
        client.stream("GET", f"/v1/jobs/{job}/events") as r,
    ):
        reader = FrameReader(r)
        pings = await reader.until(lambda fs: len(fs) >= 2)
        assert all(f == {"comment": "ping"} for f in pings)
        await log.append(job, TokenEvent(text="live"))
        await log.append(job, FinalEvent(answer=ANSWER))
        rest = await reader.until(lambda fs: any(f.get("event") == "final" for f in fs))
    events = [f for f in rest if "event" in f]
    assert [(f["id"], f["event"]) for f in events] == [(1, "token"), (2, "final")]


async def test_client_too_far_behind_gets_events_expired(
    fresh_dsn, redis_url, redis_client, fresh_conn, tenant
):
    settings = settings_for(fresh_dsn, redis_url, ask_events_maxlen=3)
    job = await new_job(fresh_conn, tenant)
    async with asgi_client(settings) as client:
        # Write through a log with the same cap the gateway uses.
        app_log = AskEventLog(redis_client, maxlen=3)
        for n in range(6):
            await app_log.append(job, TokenEvent(text=str(n)))
        await app_log.append(job, FinalEvent(answer=ANSWER))
        r = await get(client, f"/v1/jobs/{job}/events", headers={"Last-Event-ID": "1"})
    [frame] = frames(r.text)
    assert frame["event"] == "error" and "id" not in frame
    assert frame["data"]["code"] == "events_expired" and frame["data"]["retryable"] is False


async def test_finished_job_without_stored_events_streams_its_final_answer(
    fresh_dsn, redis_url, fresh_conn, tenant
):
    job = await new_job(fresh_conn, tenant, status="succeeded")
    await fresh_conn.execute(
        "INSERT INTO answers (tenant_id, question, as_of, body, job_id) VALUES ($1, 'q', now(), $2::jsonb, $3)",
        tenant,
        ANSWER.model_dump_json(),
        job,
    )
    failed = await new_job(fresh_conn, tenant, status="failed")
    await fresh_conn.execute("UPDATE jobs SET error = 'llm_unavailable' WHERE id = $1", failed)
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        done = frames((await get(client, f"/v1/jobs/{job}/events")).text)
        broken = frames((await get(client, f"/v1/jobs/{failed}/events")).text)
    assert [f["event"] for f in done] == ["final"]
    assert done[0]["data"]["answer"]["answer"] == "Check ALT monthly."
    assert [f["event"] for f in broken] == ["error"]
    assert broken[0]["data"]["code"] == "job_failed"


async def test_stream_limit_returns_503_and_unknown_job_404(
    fresh_dsn, redis_url, fresh_conn, tenant
):
    job = await new_job(fresh_conn, tenant)
    app = create_app(settings_for(fresh_dsn, redis_url, sse_max_connections=1, sse_heartbeat_s=0.1))
    url = f"/v1/jobs/{job}/events"
    async with serve(app) as base, httpx.AsyncClient(base_url=base, timeout=10) as client:
        async with client.stream("GET", url) as r:
            # Keep the reader (and its body iterator) alive: dropping it lets httpcore
            # close the connection, which frees the slot and defeats the test.
            reader = FrameReader(r)
            await reader.until(lambda fs: len(fs) >= 1)
            second = await get(client, url)
            assert second.status_code == 503 and second.headers["retry-after"] == "5"
            await reader.until(lambda fs: len(fs) >= 1)  # the first stream is still live
        # The server notices the disconnect and frees the slot.
        deadline = asyncio.get_running_loop().time() + READ_TIMEOUT_S
        while (status := await stream_status(client, url)) == 503:
            assert asyncio.get_running_loop().time() < deadline, "slot never released"
            await asyncio.sleep(0.05)
        assert status == 200
        assert (await get(client, f"/v1/jobs/{uuid4()}/events")).status_code == 404


async def test_last_event_id_beyond_the_log_is_clamped_to_its_last_id(
    fresh_dsn, redis_url, redis_client, fresh_conn, tenant
):
    """A client whose Last-Event-ID is ahead of the log (a stale tab, a bogus header)
    must still get the next real events, not heartbeats until the job ends."""
    job = await new_job(fresh_conn, tenant)
    log = AskEventLog(redis_client)
    await log.append(job, TokenEvent(text="a"))
    await log.append(job, TokenEvent(text="b"))
    app = create_app(settings_for(fresh_dsn, redis_url, sse_heartbeat_s=0.1))
    async with (
        serve(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10) as client,
        client.stream("GET", f"/v1/jobs/{job}/events", headers={"Last-Event-ID": "99"}) as r,
    ):
        reader = FrameReader(r)
        await reader.until(lambda fs: len(fs) >= 1)  # connected and idle
        await log.append(job, FinalEvent(answer=ANSWER))
        rest = await reader.until(lambda fs: any(f.get("event") == "final" for f in fs))
    assert [(f["id"], f["event"]) for f in rest if "id" in f] == [(3, "final")]


async def test_a_client_gone_before_the_stream_starts_still_frees_its_slot(
    fresh_dsn, redis_url, fresh_conn, tenant
):
    """Drive the ASGI app directly: the client disconnects at once, so Starlette may
    cancel the response before the body generator first runs (its `finally` never
    would). The slot must come back regardless."""
    job = await new_job(fresh_conn, tenant)
    app = create_app(settings_for(fresh_dsn, redis_url, sse_max_connections=1))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/v1/jobs/{job}/events",
        "raw_path": f"/v1/jobs/{job}/events".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        await asyncio.sleep(0)  # a real transport may yield while writing
        sent.append(message)

    async with app.router.lifespan_context(app) as state:
        for _ in range(2):  # with a leaked slot, the second call gets 503
            sent.clear()
            await asyncio.wait_for(app({**scope, "state": dict(state or {})}, receive, send), 5)
            starts = [m for m in sent if m["type"] == "http.response.start"]
            assert all(m["status"] == 200 for m in starts)


async def test_stream_redis_client_has_a_socket_timeout_above_the_heartbeat(fresh_dsn, redis_url):
    """Blocking reads wait up to one heartbeat, so the stream client cannot use the 1 s
    request timeout, but it must not wait forever on a dead Redis either."""
    app = create_app(settings_for(fresh_dsn, redis_url, sse_heartbeat_s=15.0))
    async with app.router.lifespan_context(app):
        timeout = app.state.redis_stream.connection_pool.connection_kwargs["socket_timeout"]
    assert timeout is not None and 15.0 < timeout <= 30.0


async def test_openapi_documents_the_event_stream(fresh_dsn, redis_url):
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        spec = (await get(client, "/openapi.json")).json()
    route = spec["paths"]["/v1/jobs/{job_id}/events"]["get"]
    content = route["responses"]["200"]["content"]["text/event-stream"]
    assert content["schema"] == {"$ref": "#/components/schemas/AskEvent"}
    schemas = spec["components"]["schemas"]
    assert {
        "AskEvent",
        "StepEvent",
        "TokenEvent",
        "ClaimEvent",
        "FinalEvent",
        "ErrorEvent",
        "AnswerSchema",
    } <= set(schemas)
    assert schemas["AskEvent"]["discriminator"]["propertyName"] == "type"
    assert "/v1/ask" in spec["paths"] and "/v1/ask/{job_id}/events" not in spec["paths"]


def test_committed_contract_fixture_matches_the_code():
    assert (
        CONTRACT_PATH
        == Path(__file__).resolve().parents[3] / "contracts" / "sse" / "ask-events.v1.json"
    )
    committed = json.loads(CONTRACT_PATH.read_text())
    assert committed == json.loads(json.dumps(build_contract()))  # regenerate with --write
    ids = [e["id"] for e in committed["examples"] if e["id"] is not None]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for example in committed["examples"]:
        event = ASK_EVENT_ADAPTER.validate_python(example["data"])
        assert event.type == example["event"]
