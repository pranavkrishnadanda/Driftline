"""`python -m driftline.drift {worker,poll}`: the drift worker, and the source scheduler."""

import argparse
import asyncio
import signal
import socket
import sys

import asyncpg
import httpx
import redis.asyncio as aioredis

from driftline.agents.__main__ import build_agent_router
from driftline.clock import Clock, SystemClock
from driftline.config import Settings
from driftline.drift.engine import DriftEngine
from driftline.drift.worker import DriftWorker, SourcePoller
from driftline.health import run_with_heartbeat
from driftline.ingest.worker import default_connector_factory
from driftline.streams.bus import StreamBus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m driftline.drift")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker", help="consume the drift stream")
    worker.add_argument("--consumer", default=socket.gethostname())
    poll = sub.add_parser("poll", help="enqueue ingest jobs for sources whose schedule is due")
    poll.add_argument("--once", action="store_true", help="one pass, then exit (for cron)")
    return parser


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return stop


async def amain(argv: list[str], settings: Settings, *, clock: Clock | None = None) -> int:
    args = _parser().parse_args(argv)
    clock = clock or SystemClock()
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
        stop = _stop_on_signals()
        await run_with_heartbeat(worker.run(stop), stop, settings.heartbeat_path)
        return 0
    finally:
        await redis.aclose()
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv[1:], Settings())))
