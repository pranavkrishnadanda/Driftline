"""Source scheduler (`python -m driftline.drift poll`): enqueue ingest jobs for sources
whose schedule is due, and count failed discoveries towards the `stale_source` streak.
Real Postgres, real Redis, the real upload connector and `ManualClock`."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from dbseed import seed_source

from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.drift.__main__ import amain
from driftline.drift.worker import SourcePoller, parse_schedule
from driftline.ingest.worker import INGEST_STREAM, default_connector_factory
from driftline.streams.bus import StreamBus

NOW = 1_800_000_000.0
HOUR = 3600.0


@pytest.fixture
async def http():
    async with httpx.AsyncClient() as client:
        yield client


def make_poller(pool, redis_client, http, clock, *, stale_after=3) -> SourcePoller:
    return SourcePoller(
        pool=pool,
        bus=StreamBus(redis_client),
        redis=redis_client,
        connector_factory=default_connector_factory(Settings(_env_file=None), http),
        clock=clock,
        stale_after_failures=stale_after,
    )


def upload_root(tmp_path: Path, name: str, files: tuple[str, ...] = ("a.md",)) -> Path:
    root = tmp_path / name
    root.mkdir()
    for f in files:
        (root / f).write_text(f"# {f}\n\nbody\n")
    return root


async def add_source(
    conn, root: Path, *, schedule: str | None, polled_ago: float | None, status="active"
):
    _, source = await seed_source(conn, config={"root": str(root)})
    await conn.execute(
        "UPDATE sources SET schedule = $2, status = $3, last_polled_at = $4 WHERE id = $1",
        source,
        schedule,
        status,
        None if polled_ago is None else datetime.fromtimestamp(NOW - polled_ago, tz=UTC),
    )
    return source


async def queued_sources(redis_client) -> list[str]:
    return [json.loads(f["data"])["source_id"] for _, f in await redis_client.xrange(INGEST_STREAM)]


async def source_row(conn, source_id):
    return await conn.fetchrow(
        "SELECT status, last_polled_at FROM sources WHERE id = $1", source_id
    )


def test_parse_schedule():
    assert parse_schedule("90") == 90
    assert parse_schedule("45s") == 45
    assert parse_schedule("15m") == 15 * 60
    assert parse_schedule("6h") == 6 * HOUR
    assert parse_schedule("1d") == 24 * HOUR
    assert parse_schedule(" @hourly ") == HOUR
    assert parse_schedule("@daily") == 24 * HOUR
    assert parse_schedule("@weekly") == 7 * 24 * HOUR
    for bad in ("", "0", "-5m", "5x", "every day", "0h"):
        with pytest.raises(ValueError):
            parse_schedule(bad)


async def test_poll_enqueues_only_due_sources(fresh_pool, fresh_conn, redis_client, http, tmp_path):
    due = await add_source(
        fresh_conn, upload_root(tmp_path, "due"), schedule="1h", polled_ago=2 * HOUR
    )
    never = await add_source(
        fresh_conn, upload_root(tmp_path, "never"), schedule="1h", polled_ago=None
    )
    recent = await add_source(
        fresh_conn, upload_root(tmp_path, "recent"), schedule="1h", polled_ago=10 * 60
    )
    await add_source(fresh_conn, upload_root(tmp_path, "manual"), schedule=None, polled_ago=None)
    await add_source(
        fresh_conn,
        upload_root(tmp_path, "paused"),
        schedule="1h",
        polled_ago=2 * HOUR,
        status="paused",
    )
    clock = ManualClock(NOW)
    poller = make_poller(fresh_pool, redis_client, http, clock)

    result = await poller.poll_once()

    assert sorted(result.polled) == sorted([due, never])
    assert sorted(await queued_sources(redis_client)) == sorted([str(due), str(never)])
    assert await fresh_conn.fetchval("SELECT count(*) FROM jobs WHERE kind = 'ingest'") == 2
    for source in (due, never):
        row = await source_row(fresh_conn, source)
        assert row["last_polled_at"].timestamp() == NOW
    assert (await source_row(fresh_conn, recent))["last_polled_at"].timestamp() == NOW - 600

    clock.advance(30 * 60)  # recent is 40 min old, the others 30 min: nothing is due
    assert (await poller.poll_once()).polled == []

    clock.advance(31 * 60)  # 61 min since the first pass, 71 min for `recent`
    assert sorted((await poller.poll_once()).polled) == sorted([due, never, recent])
    assert len(await queued_sources(redis_client)) == 5


async def test_concurrent_pollers_enqueue_a_due_source_once(
    fresh_pool, fresh_conn, redis_client, http, tmp_path
):
    source = await add_source(
        fresh_conn, upload_root(tmp_path, "s", ("a.md", "b.md")), schedule="1h", polled_ago=None
    )
    clock = ManualClock(NOW)
    first, second = (make_poller(fresh_pool, redis_client, http, clock) for _ in range(2))

    results = await asyncio.gather(first.poll_once(), second.poll_once())

    assert sorted(len(r.polled) for r in results) == [0, 1]
    assert await queued_sources(redis_client) == [str(source)] * 2  # a.md and b.md, once each


async def test_repeated_fetch_failures_mark_source_stale(
    fresh_pool, fresh_conn, redis_client, http, tmp_path
):
    missing = tmp_path / "gone"  # the upload root does not exist: discovery fails
    source = await add_source(fresh_conn, missing, schedule="1h", polled_ago=None)
    clock = ManualClock(NOW)
    poller = make_poller(fresh_pool, redis_client, http, clock, stale_after=3)

    for attempt in (1, 2):
        result = await poller.poll_once()
        assert result.failed == [source] and result.stale == []
        assert (await source_row(fresh_conn, source))["status"] == "active", attempt
        clock.advance(HOUR)
    result = await poller.poll_once()

    assert result.failed == [source] and result.stale == [source]
    row = await source_row(fresh_conn, source)
    assert row["status"] == "stale_source"
    assert row["last_polled_at"].timestamp() == NOW + 2 * HOUR  # retried at its cadence
    assert await queued_sources(redis_client) == []
    assert await fresh_conn.fetchval("SELECT count(*) FROM jobs") == 0

    # A stale source is still polled, but a working discovery alone does not revive it:
    # only the next successful fetch of the queued job does (in the ingest worker).
    missing.mkdir()
    (missing / "a.md").write_text("# A\n\nbody\n")
    clock.advance(HOUR)
    result = await poller.poll_once()
    assert result.polled == [source] and result.failed == []
    assert (await source_row(fresh_conn, source))["status"] == "stale_source"
    assert await queued_sources(redis_client) == [str(source)]


async def test_successful_discovery_does_not_reset_failure_streak(
    fresh_pool, fresh_conn, redis_client, http, tmp_path
):
    """Only a successful fetch resets the streak (tested in tests/ingest). A discovery
    that succeeds between two failed ones proves nothing about fetching, so the streak
    keeps counting: fail, fail, succeed, fail is 3 failures and the source goes stale."""
    root = tmp_path / "flaky"
    source = await add_source(fresh_conn, root, schedule="1h", polled_ago=None)
    clock = ManualClock(NOW)
    poller = make_poller(fresh_pool, redis_client, http, clock, stale_after=3)

    for exists in (False, False, True):
        if exists and not root.exists():
            root.mkdir()
        if not exists and root.exists():
            root.rmdir()
        await poller.poll_once()
        clock.advance(HOUR)
        assert (await source_row(fresh_conn, source))["status"] == "active"

    root.rmdir()
    result = await poller.poll_once()

    assert result.failed == [source] and result.stale == [source]
    assert (await source_row(fresh_conn, source))["status"] == "stale_source"


async def test_invalid_schedule_is_skipped_not_counted_as_failure(
    fresh_pool, fresh_conn, redis_client, http, tmp_path
):
    bad = await add_source(
        fresh_conn, upload_root(tmp_path, "bad"), schedule="whenever", polled_ago=None
    )
    good = await add_source(
        fresh_conn, upload_root(tmp_path, "good"), schedule="1h", polled_ago=None
    )
    poller = make_poller(fresh_pool, redis_client, http, ManualClock(NOW), stale_after=1)

    result = await poller.poll_once()

    assert result.polled == [good] and result.failed == []
    assert (await source_row(fresh_conn, bad))["status"] == "active"


async def test_cli_poll_once_enqueues_due_sources(
    fresh_dsn, fresh_conn, redis_url, redis_client, tmp_path
):
    source = await add_source(
        fresh_conn, upload_root(tmp_path, "s"), schedule="@daily", polled_ago=None
    )
    settings = Settings(_env_file=None, database_url=fresh_dsn, redis_url=redis_url)

    assert await amain(["poll", "--once"], settings, clock=ManualClock(NOW)) == 0

    assert await queued_sources(redis_client) == [str(source)]
    assert (await source_row(fresh_conn, source))["last_polled_at"].timestamp() == NOW
