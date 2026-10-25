import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import httpx
import pytest
import yaml

from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.drift.alerts import AlertLog
from driftline.drift.worker import SourcePoller
from driftline.ingest.__main__ import amain, build_ingest_router
from driftline.ingest.connectors.k8s_docs import KubernetesDocsConnector
from driftline.ingest.connectors.openfda import OpenFDAConnector
from driftline.ingest.connectors.upload import UploadConnector
from driftline.ingest.embed import EmbedStage
from driftline.ingest.outbox import OutboxRelay
from driftline.ingest.supersession import SupersessionExtractor
from driftline.ingest.types import SourceFetchError
from driftline.ingest.worker import (
    EMBED_STREAM,
    INGEST_GROUP,
    INGEST_STREAM,
    IngestWorker,
    default_connector_factory,
    enqueue_ingest,
    ensure_source,
    failure_key,
)
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.streams.bus import StreamBus

COMPOSE = Path(__file__).resolve().parents[3] / "deploy" / "compose" / "docker-compose.yml"
T1, T2 = 1_700_000_000, 1_800_000_000


@pytest.fixture
def det() -> DeterministicAdapter:
    return DeterministicAdapter("det")


@pytest.fixture
async def worker(fresh_pool, redis_client, det) -> IngestWorker:
    router = LLMRouter(
        providers={"det": det},
        chains={"embed": [Route("det", "det-embed")], "extract": [Route("det", "det-extract")]},
        clock=ManualClock(),
    )
    w = IngestWorker(
        pool=fresh_pool,
        bus=StreamBus(redis_client),
        redis=redis_client,
        connector_factory=lambda kind, config: UploadConnector(config["root"]),
        embed_stage=EmbedStage(router, model_name="det-embed"),
        extractor=SupersessionExtractor(router),
        consumer="w1",
        clock=ManualClock(),
    )
    await w.setup()
    return w


async def upload_source(pool, root: Path):
    async with pool.acquire() as conn:
        return await ensure_source(conn, tenant="demo", kind="upload", config={"root": str(root)})


def write(root: Path, name: str, text: str, mtime: int) -> Path:
    path = root / name
    path.write_text(text)
    os.utime(path, (mtime, mtime))
    return path


async def ingest(pool, redis_client, worker, source, name: str):
    job = await enqueue_ingest(pool, StreamBus(redis_client), source_id=source, external_id=name)
    await worker.run_once()
    return job


async def test_ingest_message_stores_version_and_completes_job(
    worker, fresh_pool, redis_client, tmp_path
):
    write(tmp_path, "runbook.md", "# Rollout runbook\n\n## Undo\n\nkubectl rollout undo.\n", T1)
    source = await upload_source(fresh_pool, tmp_path)
    job = await enqueue_ingest(
        fresh_pool, StreamBus(redis_client), source_id=source, external_id="runbook.md"
    )
    assert await worker.run_once() == 1
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT status FROM jobs WHERE id = $1", job) == "succeeded"
        assert await conn.fetchval("SELECT count(*) FROM doc_versions") == 1
        assert await conn.fetchval("SELECT count(*) FROM chunks") == 1
        assert await conn.fetchval("SELECT cursor FROM source_cursors") is not None
        src = await conn.fetchrow(
            "SELECT status, last_polled_at FROM sources WHERE id = $1", source
        )
        assert src["status"] == "active" and src["last_polled_at"] is not None


async def test_reingest_identical_file_is_noop(worker, fresh_pool, redis_client, tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n", T1)
    source = await upload_source(fresh_pool, tmp_path)
    await ingest(fresh_pool, redis_client, worker, source, "a.md")
    await ingest(fresh_pool, redis_client, worker, source, "a.md")  # cursor short-circuits
    async with fresh_pool.acquire() as conn:
        await conn.execute("DELETE FROM source_cursors")
    await ingest(fresh_pool, redis_client, worker, source, "a.md")  # content hash dedupes
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM doc_versions") == 1
        assert await conn.fetchval("SELECT count(*) FROM outbox") == 1
        statuses = {r["status"] for r in await conn.fetch("SELECT status FROM jobs")}
        assert statuses == {"succeeded"}


async def test_changed_file_creates_second_version(worker, fresh_pool, redis_client, tmp_path):
    write(tmp_path, "a.md", "# A\n\n## Dose\n\n10 mg.\n", T1)
    source = await upload_source(fresh_pool, tmp_path)
    await ingest(fresh_pool, redis_client, worker, source, "a.md")
    write(tmp_path, "a.md", "# A\n\n## Dose\n\n20 mg.\n", T2)
    await ingest(fresh_pool, redis_client, worker, source, "a.md")
    async with fresh_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT valid_from, valid_to, diff_from_prev FROM doc_versions ORDER BY version_no"
        )
        assert len(rows) == 2
        assert rows[0]["valid_to"] == rows[1]["valid_from"] == datetime.fromtimestamp(T2, tz=UTC)
        assert json.loads(rows[1]["diff_from_prev"])["changed"] == ["A > Dose"]
        assert await conn.fetchval("SELECT count(*) FROM outbox") == 2


async def test_fetch_failure_feeds_the_failure_streak_and_fails_the_job(
    worker, fresh_pool, redis_client, tmp_path
):
    """One rule for "stale" (shared with the scheduler): a failed fetch counts towards
    the source's consecutive-failure streak, and the source is marked `stale_source`
    only once the streak reaches `stale_after_failures` (3), never on the first failure."""
    source = await upload_source(fresh_pool, tmp_path)
    bus = StreamBus(redis_client)
    job = await enqueue_ingest(fresh_pool, bus, source_id=source, external_id="missing.md")
    assert await worker.run_once() == 0
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT status FROM sources WHERE id = $1", source) == ("active")
        job_row = await conn.fetchrow("SELECT status, error FROM jobs WHERE id = $1", job)
        assert job_row["status"] == "failed" and "missing.md" in job_row["error"]
    assert await redis_client.get(failure_key(source)) == "1"
    # The message stays pending: it is reclaimed later and dead-lettered after 3 deliveries.
    assert (await redis_client.xpending(INGEST_STREAM, INGEST_GROUP))["pending"] == 1

    # A redelivery of the same job is the same failure: it does not grow the streak.
    payload = {"job_id": str(job), "source_id": str(source), "external_id": "missing.md"}
    with pytest.raises(SourceFetchError):
        await worker.handle_ingest("redelivered", payload)
    assert await redis_client.get(failure_key(source)) == "1"

    # Two more failed jobs make three in a row: now the source is stale.
    for n in (2, 3):
        await enqueue_ingest(fresh_pool, bus, source_id=source, external_id="missing.md")
        await worker.run_once()
        assert await redis_client.get(failure_key(source)) == str(n)
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT status FROM sources WHERE id = $1", source) == (
            "stale_source"
        )

    # A successful fetch makes it active again and resets the streak.
    write(tmp_path, "missing.md", "# Back\n\nbody\n", T1)
    await enqueue_ingest(fresh_pool, bus, source_id=source, external_id="missing.md")
    await worker.run_once()
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT status FROM sources WHERE id = $1", source) == ("active")
    assert await redis_client.get(failure_key(source)) is None


async def test_ingest_and_scheduler_failures_share_one_streak(
    worker, fresh_pool, redis_client, tmp_path
):
    """The scheduler's discovery failures and the worker's fetch failures add up."""
    source = await upload_source(fresh_pool, tmp_path)
    bus = StreamBus(redis_client)
    async with fresh_pool.acquire() as conn:
        await conn.execute("UPDATE sources SET schedule = '1h' WHERE id = $1", source)
    for _ in range(2):
        await enqueue_ingest(fresh_pool, bus, source_id=source, external_id="missing.md")
        await worker.run_once()
    poller = SourcePoller(
        pool=fresh_pool,
        bus=bus,
        redis=redis_client,
        connector_factory=lambda kind, config: UploadConnector(str(tmp_path / "gone")),
        clock=ManualClock(T2),
        stale_after_failures=3,
    )
    result = await poller.poll_once()
    assert result.failed == [source] and result.stale == [source]
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT status FROM sources WHERE id = $1", source) == (
            "stale_source"
        )


async def test_discovery_succeeds_but_fetches_fail_marks_source_stale(
    worker, fresh_pool, redis_client, tmp_path
):
    """Regression: a successful discovery must not reset the streak. Discovery lists
    `a.md` every cycle, but every fetch of it fails: after 3 cycles the source is stale.
    Only a successful fetch makes it `active` again; a successful discovery alone does not."""
    listed = tmp_path / "listed"
    listed.mkdir()
    write(listed, "a.md", "# A\n\nbody\n", T1)
    fetched = tmp_path / "fetched"  # the worker fetches from here: a.md is missing
    fetched.mkdir()
    source = await upload_source(fresh_pool, fetched)
    async with fresh_pool.acquire() as conn:
        await conn.execute("UPDATE sources SET schedule = '1h' WHERE id = $1", source)
    clock = ManualClock(T2)
    poller = SourcePoller(
        pool=fresh_pool,
        bus=StreamBus(redis_client),
        redis=redis_client,
        connector_factory=lambda kind, config: UploadConnector(str(listed)),
        clock=clock,
        stale_after_failures=3,
    )

    async def status() -> str:
        async with fresh_pool.acquire() as conn:
            return await conn.fetchval("SELECT status FROM sources WHERE id = $1", source)

    for cycle in (1, 2, 3):
        result = await poller.poll_once()
        assert result.polled == [source] and result.failed == [], cycle
        assert await worker.run_once() == 0  # the fetch failed
        assert await redis_client.get(failure_key(source)) == str(cycle)
        clock.advance(3600)
    assert await status() == "stale_source"

    # A stale source is still polled, but a successful discovery alone does not revive it.
    assert (await poller.poll_once()).polled == [source]
    assert await status() == "stale_source"
    assert await redis_client.get(failure_key(source)) == "3"

    # The next successful fetch does: the queued job now finds the file.
    write(fetched, "a.md", "# A\n\nbody\n", T1)
    assert await worker.run_once() == 1
    assert await status() == "active"
    assert await redis_client.get(failure_key(source)) is None


async def test_embed_event_embeds_runs_extraction_and_dedupes(
    worker, fresh_pool, redis_client, det, tmp_path
):
    write(tmp_path, "a.md", "# Atorvastatin dosing\n\n## Liver\n\nCheck enzymes.\n", T1)
    write(
        tmp_path,
        "b.md",
        "# Atorvastatin dosing update\n\n## Liver\n\nThis update supersedes the earlier guide.\n",
        T1,
    )
    source = await upload_source(fresh_pool, tmp_path)
    for name in ("a.md", "b.md"):
        await enqueue_ingest(
            fresh_pool, StreamBus(redis_client), source_id=source, external_id=name
        )
    assert await worker.run_once() == 2
    assert (
        await OutboxRelay(
            fresh_pool, StreamBus(redis_client), alerts=AlertLog(redis_client)
        ).relay_once()
        == 2
    )
    assert await worker.run_once() == 2
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0
        assert await conn.fetchval("SELECT DISTINCT embed_model FROM chunks") == "det-embed"
        # Each document is the other's candidate; the deterministic reply is not JSON.
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM review_items WHERE payload->>'error' = 'malformed_extraction'"
            )
            == 2
        )
    assert det.calls.count("det-extract") == 2
    # Redeliver the same events (at-least-once): they are acknowledged without new work.
    for _, fields in await redis_client.xrange(EMBED_STREAM):
        await redis_client.xadd(EMBED_STREAM, fields)
    assert await worker.run_once() == 2
    assert det.calls.count("det-extract") == 2


async def test_ensure_source_is_idempotent(fresh_pool):
    async with fresh_pool.acquire() as conn:
        a = await ensure_source(conn, tenant="demo", kind="openfda", config={"search": "x"})
        b = await ensure_source(conn, tenant="demo", kind="openfda", config={"search": "x"})
        c = await ensure_source(conn, tenant="demo", kind="openfda", config={"search": "y"})
        assert await conn.fetchval("SELECT count(*) FROM tenants") == 1
    assert a == b and a != c


async def test_connector_factory_builds_each_kind(tmp_path):
    settings = Settings(_env_file=None, github_token="gh-test")
    async with httpx.AsyncClient() as http:
        build = default_connector_factory(settings, http)
        assert isinstance(build("openfda", {"search": "x", "limit": 2}), OpenFDAConnector)
        k8s = build("git_docs", {"branches": ["release-1.30"], "paths": ["a.md"]})
        assert isinstance(k8s, KubernetesDocsConnector)
        assert await k8s.list_external_ids() == ["a.md"]
        assert isinstance(build("upload", {"root": str(tmp_path)}), UploadConnector)
        with pytest.raises(ValueError):
            build("ftp", {})


async def test_cli_enqueue_discovers_and_queues_jobs(fresh_dsn, redis_url, redis_client, tmp_path):
    write(tmp_path, "a.md", "# A\n\nbody\n", T1)
    write(tmp_path, "b.md", "# B\n\nbody\n", T1)
    settings = Settings(_env_file=None, database_url=fresh_dsn, redis_url=redis_url)
    config = json.dumps({"root": str(tmp_path)})
    argv = ["enqueue", "--tenant", "demo", "--kind", "upload", "--config", config, "--discover"]
    assert await amain(argv, settings) == 0
    messages = [json.loads(f["data"]) for _, f in await redis_client.xrange(INGEST_STREAM)]
    assert sorted(m["external_id"] for m in messages) == ["a.md", "b.md"]
    conn = await asyncpg.connect(fresh_dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM jobs WHERE status = 'queued'") == 2
    finally:
        await conn.close()


async def run_relay_beside(pool, redis_client, coro):
    """Run `coro` (a worker CLI) with the real outbox relay running beside it."""
    stop = asyncio.Event()
    relay = OutboxRelay(pool, StreamBus(redis_client), alerts=AlertLog(redis_client))
    relay_task = asyncio.create_task(relay.run(stop, idle_sleep_s=0.05))
    try:
        return await coro
    finally:
        stop.set()
        await relay_task


async def test_cli_worker_drain_ingests_relays_and_embeds_then_exits(
    fresh_dsn, fresh_pool, redis_url, redis_client, embedder_url, tmp_path
):
    write(tmp_path, "a.md", "# A\n\n## Undo\n\nkubectl rollout undo.\n", T1)
    write(tmp_path, "b.md", "# B\n\n## Scale\n\nkubectl scale deployment.\n", T1)
    settings = Settings(
        _env_file=None, database_url=fresh_dsn, redis_url=redis_url, embed_url=embedder_url
    )
    config = json.dumps({"root": str(tmp_path)})
    enqueue = ["enqueue", "--tenant", "demo", "--kind", "upload", "--config", config, "--discover"]
    assert await amain(enqueue, settings) == 0

    code = await run_relay_beside(
        fresh_pool, redis_client, amain(["worker", "--drain", "--timeout", "120"], settings)
    )

    assert code == 0
    async with fresh_pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM jobs WHERE status = 'succeeded'") == 2
        assert await conn.fetchval("SELECT count(*) FROM doc_versions") == 2
        assert await conn.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0
        assert await conn.fetchval("SELECT count(*) FROM outbox WHERE published_at IS NULL") == 0
    for stream in (INGEST_STREAM, EMBED_STREAM):
        groups = await redis_client.xinfo_groups(stream)
        assert [g["pending"] for g in groups] == [0]
    assert await redis_client.xlen("drift") == 2  # version.created also fans out to drift


async def test_cli_worker_drain_times_out_without_a_relay(
    fresh_dsn, redis_url, redis_client, embedder_url, tmp_path
):
    write(tmp_path, "a.md", "# A\n\nbody\n", T1)
    settings = Settings(
        _env_file=None, database_url=fresh_dsn, redis_url=redis_url, embed_url=embedder_url
    )
    config = json.dumps({"root": str(tmp_path)})
    enqueue = ["enqueue", "--tenant", "demo", "--kind", "upload", "--config", config, "--discover"]
    assert await amain(enqueue, settings) == 0

    # The version is stored, but its outbox row is never published: not drained.
    assert await amain(["worker", "--drain", "--timeout", "2"], settings) == 1


def test_build_ingest_router_degrades_to_embed_only_without_llm_key(redis_client):
    router, extraction = build_ingest_router(
        Settings(_env_file=None), redis_client, clock=ManualClock()
    )
    assert extraction is False and set(router.chains) == {"embed"}
    keyed = Settings(_env_file=None, anthropic_api_key="test-key")
    router, extraction = build_ingest_router(keyed, redis_client, clock=ManualClock())
    assert extraction is True and {"embed", "extract"} <= set(router.chains)


def test_compose_ingest_worker_is_scalable_and_relay_exists():
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    worker = services["ingest-worker"]
    assert worker["command"] == ["python", "-m", "driftline.ingest", "worker"]
    assert "ports" not in worker and "container_name" not in worker
    assert worker["depends_on"]["gateway"]["condition"] == "service_healthy"
    assert services["outbox-relay"]["command"] == ["python", "-m", "driftline.ingest", "relay"]
