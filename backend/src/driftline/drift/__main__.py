"""`python -m driftline.drift {worker,poll,report}`: the drift worker, the source
scheduler, and the drift log writer."""

import argparse
import asyncio
import signal
import socket
import sys
from pathlib import Path

import asyncpg
import httpx
import redis.asyncio as aioredis

from driftline.agents.__main__ import build_agent_router
from driftline.clock import Clock, SystemClock
from driftline.config import Settings
from driftline.drift.engine import DriftEngine
from driftline.drift.report import build_report, render_json, render_markdown
from driftline.drift.worker import DRIFT_GROUP, DRIFT_STREAM, DriftWorker, SourcePoller
from driftline.health import run_with_heartbeat
from driftline.ingest.worker import default_connector_factory
from driftline.streams.bus import StreamBus
from driftline.streams.drain import DrainTimeout, drain, pipeline_drained


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m driftline.drift")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker", help="consume the drift stream")
    worker.add_argument("--consumer", default=socket.gethostname())
    worker.add_argument(
        "--drain",
        action="store_true",
        help="exit once the drift stream and the outbox are empty (needs a relay running)",
    )
    worker.add_argument("--timeout", type=float, default=3600.0, help="--drain time budget (s)")
    poll = sub.add_parser("poll", help="enqueue ingest jobs for sources whose schedule is due")
    poll.add_argument("--once", action="store_true", help="one pass, then exit (for cron)")
    report = sub.add_parser("report", help="write drift-log.md and drift-latest.json")
    report.add_argument("--out", default="reports", help="output directory")
    report.add_argument("--tenant", help="only this tenant's documents (default: all)")
    return parser


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return stop


async def write_report(settings: Settings, out: Path, *, tenant: str | None) -> int:
    conn = await asyncpg.connect(settings.database_url)
    try:
        report = await build_report(conn, tenant=tenant, llm_offline=settings.llm_offline)
    finally:
        await conn.close()
    out.mkdir(parents=True, exist_ok=True)
    (out / "drift-log.md").write_text(render_markdown(report), encoding="utf-8")
    (out / "drift-latest.json").write_text(render_json(report), encoding="utf-8")
    totals = report["totals"]
    print(
        f"wrote {out / 'drift-log.md'} and {out / 'drift-latest.json'}: "
        f"{totals['documents']} document(s), {totals['changes']} change(s)"
    )
    return 0


async def amain(argv: list[str], settings: Settings, *, clock: Clock | None = None) -> int:
    args = _parser().parse_args(argv)
    clock = clock or SystemClock()
    if args.command == "report":
        return await write_report(settings, Path(args.out), tenant=args.tenant)
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    bus = StreamBus(redis)
    try:
        if args.command == "poll":
            async with httpx.AsyncClient(timeout=settings.http_timeout_s) as http:
                poller = SourcePoller(
                    pool=pool,
                    bus=bus,
                    redis=redis,
                    connector_factory=default_connector_factory(settings, http),
                    clock=clock,
                    stale_after_failures=settings.source_stale_after_failures,
                )
                if args.once:
                    result = await poller.poll_once()
                    print(
                        f"polled {len(result.polled)} source(s), {len(result.jobs)} job(s); "
                        f"{len(result.failed)} failed, {len(result.stale)} marked stale"
                    )
                    return 0
                stop = _stop_on_signals()
                await run_with_heartbeat(
                    poller.run(stop, interval_s=settings.poll_interval_s),
                    stop,
                    settings.heartbeat_path,
                )
                return 0
        router = build_agent_router(settings, redis, clock=clock)
        worker = DriftWorker(
            bus,
            DriftEngine(pool, router, clock, settings),
            clock,
            redis=redis,
            consumer=args.consumer,
        )
        if args.drain:
            await worker.setup()
            try:
                processed = await drain(
                    worker.run_once,
                    lambda: pipeline_drained(pool, redis, [(DRIFT_STREAM, DRIFT_GROUP)]),
                    timeout_s=args.timeout,
                )
            except DrainTimeout as exc:
                print(f"drift worker --drain: {exc}", file=sys.stderr)
                return 1
            dead = await redis.xlen(f"dlq:{DRIFT_STREAM}")
            print(f"drained: {processed} drift event(s) processed; dlq:{DRIFT_STREAM}={dead}")
            return 0
        stop = _stop_on_signals()
        await run_with_heartbeat(worker.run(stop), stop, settings.heartbeat_path)
        return 0
    finally:
        await redis.aclose()
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv[1:], Settings())))
