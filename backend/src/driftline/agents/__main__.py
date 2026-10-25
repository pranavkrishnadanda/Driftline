"""`python -m driftline.agents {worker,reap}`: the agent worker process, and a one-off
pass that fails asks whose stream entry was lost."""

import argparse
import asyncio
import signal
import socket
import sys

import asyncpg
import redis.asyncio as aioredis
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis

from driftline.agents.eventlog import AskEventLog
from driftline.agents.graph import AgentConfig, AgentDeps, build_answer_graph
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.agents.worker import AgentWorker, reap_lost_asks
from driftline.cache.semantic import SemanticCache
from driftline.clock import Clock, SystemClock
from driftline.config import Settings
from driftline.health import run_with_heartbeat
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route, build_bench_router, build_router
from driftline.obs.cost import CostLedger
from driftline.obs.tracing import build_tracer
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.streams.bus import StreamBus


def build_agent_router(
    settings: Settings, redis: Redis, *, clock: Clock, consumer: str | None = None
) -> LLMRouter:
    """Claude (and Gemini) when keys are set; the keyless offline ExtractiveResponder when
    DRIFTLINE_LLM_OFFLINE=true; the bench stub (seeded per `consumer`) when
    DRIFTLINE_LLM_BENCH=true, which wins over both. Embeddings always come from TEI.
    Raises ValueError when no key, offline or bench mode is configured."""
    if settings.llm_bench:
        return build_bench_router(settings, clock=clock, consumer=consumer)
    if settings.llm_offline:
        det = DeterministicAdapter("deterministic", responder=ExtractiveResponder())
        tiers = {
            t: [Route("deterministic", f"offline-{t}")] for t in ("extract", "answer", "judge")
        }
        return LLMRouter(
            providers={"deterministic": det, "tei": TEIEmbeddingAdapter(settings.embed_url)},
            chains={**tiers, "embed": [Route("tei", settings.model_embed)]},
            clock=clock,
        )
    return build_router(settings, redis, clock=clock)


# Arbitrary constant key for pg_advisory_lock: "checkpointer setup" across all workers.
CHECKPOINTER_SETUP_LOCK = 0x44524C43  # "DRLC"


async def setup_checkpointer(
    saver: AsyncPostgresSaver, pool: asyncpg.Pool, *, timeout_s: float = 300.0
) -> None:
    """`saver.setup()` under a Postgres advisory lock. Workers started together
    (`--scale agent-worker=N` on a fresh database) otherwise run LangGraph's migrations
    concurrently and all but one die with a UniqueViolation.

    Polls `pg_try_advisory_lock` rather than blocking in `pg_advisory_lock`: a session
    blocked inside that statement holds a snapshot, and the migrations' CREATE INDEX
    CONCURRENTLY waits for every such snapshot, so the holder would wait forever.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    async with pool.acquire() as conn:
        while not await conn.fetchval("SELECT pg_try_advisory_lock($1)", CHECKPOINTER_SETUP_LOCK):
            if loop.time() >= deadline:
                raise TimeoutError(f"checkpointer setup lock not acquired in {timeout_s}s")
            await asyncio.sleep(0.2)
        try:
            await saver.setup()
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", CHECKPOINTER_SETUP_LOCK)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m driftline.agents")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker", help="consume the agent stream")
    worker.add_argument("--consumer", default=socket.gethostname())
    sub.add_parser("reap", help="fail queued asks whose stream entry was lost")
    return parser


def _stop_on_signals() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    return stop


def _events(settings: Settings, redis: Redis) -> AskEventLog:
    return AskEventLog(redis, maxlen=settings.ask_events_maxlen, ttl_s=settings.ask_events_ttl_s)


async def _run_worker(
    settings: Settings, pool: asyncpg.Pool, redis: Redis, *, consumer: str, clock: Clock
) -> None:
    router = build_agent_router(settings, redis, clock=clock, consumer=consumer)
    tracer = build_tracer(settings)
    try:
        deps = AgentDeps(
            pool=pool,
            llm=AgentLLM(router, ledger=CostLedger(pool), tracer=tracer),
            retriever=HybridRetriever(
                pool,
                router,
                embed_model=settings.model_embed,
                dim=settings.embed_dim,
                candidates=settings.retrieval_candidates,
                rrf_k=settings.rrf_k,
            ),
            reranker=TEIReranker(settings.rerank_url),
            cache=SemanticCache(
                redis,
                router,
                threshold=settings.semantic_cache_threshold,
                ttl_s=settings.semantic_cache_ttl_s,
                dim=settings.embed_dim,
            )
            if settings.semantic_cache_enabled
            else None,
            tracer=tracer,
            clock=clock,
            config=AgentConfig.from_settings(settings),
        )
        async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
            await setup_checkpointer(saver, pool)
            worker = AgentWorker(
                pool=pool,
                redis=redis,
                bus=StreamBus(redis),
                events=_events(settings, redis),
                graph=build_answer_graph(deps).compile(checkpointer=saver),
                consumer=consumer,
                clock=clock,
                queue_timeout_s=settings.ask_queue_timeout_s,
            )
            stop = _stop_on_signals()
            await run_with_heartbeat(worker.run(stop), stop, settings.heartbeat_path)
    finally:
        tracer.shutdown()


async def amain(argv: list[str], settings: Settings, *, clock: Clock | None = None) -> int:
    args = _parser().parse_args(argv)
    clock = clock or SystemClock()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=8)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        if args.command == "reap":
            reaped = await reap_lost_asks(
                pool,
                redis,
                _events(settings, redis),
                now=clock.now(),
                timeout_s=settings.ask_queue_timeout_s,
            )
            print(f"reaped {len(reaped)} lost ask(s)")
            return 0
        await _run_worker(settings, pool, redis, consumer=args.consumer, clock=clock)
        return 0
    finally:
        await redis.aclose()
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv[1:], Settings())))
