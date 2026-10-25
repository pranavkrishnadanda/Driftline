"""`python -m driftline.ingest {worker,relay,enqueue}`: the ingestion processes.

`worker --drain` is the batch mode (the nightly drift-watch job): it exits once the
ingest and embed streams and the outbox are empty, with a relay running beside it.
"""

import argparse
import asyncio
import json
import signal
import socket
import sys

import asyncpg
import httpx
import redis.asyncio as aioredis
from redis.asyncio import Redis

from driftline.clock import Clock, SystemClock
from driftline.config import Settings
from driftline.drift.alerts import AlertLog
from driftline.health import run_with_heartbeat
from driftline.ingest.embed import EmbedStage
from driftline.ingest.outbox import OutboxRelay
from driftline.ingest.supersession import SupersessionExtractor
from driftline.ingest.worker import (
    EMBED_GROUP,
    EMBED_STREAM,
    INGEST_GROUP,
    INGEST_STREAM,
    IngestWorker,
    default_connector_factory,
    enqueue_ingest,
    ensure_source,
)
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route, build_router
from driftline.streams.bus import StreamBus
from driftline.streams.drain import DrainTimeout, drain, pipeline_drained


def build_ingest_router(
    settings: Settings, redis: Redis, *, clock: Clock
) -> tuple[LLMRouter, bool]:
    """(router, extraction_enabled). Without any LLM key the worker still embeds."""
    try:
        return build_router(settings, redis, clock=clock), True
    except ValueError:
        router = LLMRouter(
            providers={"tei": TEIEmbeddingAdapter(settings.embed_url)},
            chains={"embed": [Route("tei", settings.model_embed)]},
            clock=clock,
        )
        return router, False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m driftline.ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker", help="consume the ingest and embed streams")
    worker.add_argument("--consumer", default=socket.gethostname())
    worker.add_argument(
        "--drain",
        action="store_true",
        help="exit once the ingest and embed streams and the outbox are empty "
        "(needs a relay running)",
    )
    worker.add_argument("--timeout", type=float, default=3600.0, help="--drain time budget (s)")
    sub.add_parser("relay", help="publish committed outbox rows to Redis Streams")
    enqueue = sub.add_parser("enqueue", help="queue ingest jobs for a source")
    enqueue.add_argument("--tenant", required=True)
    enqueue.add_argument("--kind", required=True, choices=["openfda", "git_docs", "upload"])
    enqueue.add_argument("--config", default="{}", help="source config as a JSON object")
    target = enqueue.add_mutually_exclusive_group(required=True)
    target.add_argument("--external-id", action="append", dest="external_ids")
    target.add_argument("--discover", action="store_true", help="queue every id the source lists")
    return parser


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return stop


async def _drain_worker(
    worker: IngestWorker, pool: asyncpg.Pool, redis: Redis, *, timeout_s: float
) -> int:
    """Run the worker until the ingest pipeline is empty (see `streams.drain`); 1 on timeout."""
    groups = [(INGEST_STREAM, INGEST_GROUP), (EMBED_STREAM, EMBED_GROUP)]
    await worker.setup()
    try:
        processed = await drain(
            worker.run_once, lambda: pipeline_drained(pool, redis, groups), timeout_s=timeout_s
        )
    except DrainTimeout as exc:
        print(f"ingest worker --drain: {exc}", file=sys.stderr)
        return 1
    dead = {s: await redis.xlen(f"dlq:{s}") for s in (INGEST_STREAM, EMBED_STREAM)}
    failed = " ".join(f"dlq:{s}={n}" for s, n in dead.items())
    print(f"drained: {processed} message(s) processed; {failed}")
    return 0


async def amain(argv: list[str], settings: Settings, *, clock: Clock | None = None) -> int:
    args = _parser().parse_args(argv)
    clock = clock or SystemClock()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    bus = StreamBus(redis)
    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_s) as http:
            factory = default_connector_factory(settings, http)
            if args.command == "enqueue":
                config = json.loads(args.config)
                async with pool.acquire() as conn:
                    source_id = await ensure_source(
                        conn, tenant=args.tenant, kind=args.kind, config=config
                    )
                ids = args.external_ids or await factory(args.kind, config).list_external_ids()
                for external_id in ids:
                    job_id = await enqueue_ingest(
                        pool, bus, source_id=source_id, external_id=external_id
                    )
                    print(f"enqueued {external_id} job={job_id}")
                return 0
            stop = _stop_on_signals()
            if args.command == "relay":
                relay = OutboxRelay(
                    pool,
                    bus,
                    batch_size=settings.outbox_batch_size,
                    alerts=AlertLog(
                        redis,
                        maxlen=settings.alert_events_maxlen,
                        ttl_s=settings.alert_events_ttl_s,
                    ),
                )
                await run_with_heartbeat(
                    relay.run(stop, clock=clock), stop, settings.heartbeat_path
                )
                return 0
            router, extraction = build_ingest_router(settings, redis, clock=clock)
            if not extraction:
                print("no LLM key configured: supersession extraction disabled", file=sys.stderr)
            worker = IngestWorker(
                pool=pool,
                bus=bus,
                redis=redis,
                connector_factory=factory,
                embed_stage=EmbedStage(
                    router,
                    model_name=settings.model_embed,
                    dim=settings.embed_dim,
                    batch_size=settings.embed_batch_size,
                ),
                extractor=SupersessionExtractor(
                    router,
                    threshold=settings.relation_apply_threshold,
                    max_output_tokens=settings.default_max_output_tokens,
                )
                if extraction
                else None,
                consumer=args.consumer,
                chunk_tokens=settings.chunk_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
                clock=clock,
            )
            if args.drain:
                return await _drain_worker(worker, pool, redis, timeout_s=args.timeout)
            await run_with_heartbeat(worker.run(stop), stop, settings.heartbeat_path)
            return 0
    finally:
        await redis.aclose()
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv[1:], Settings())))
