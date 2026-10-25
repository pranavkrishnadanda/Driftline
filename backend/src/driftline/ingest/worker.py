"""Ingest worker: `ingest` stream (fetch -> hash -> diff -> chunk -> store) and
`embed` stream (embed -> supersession extraction), both via StreamBus consumer groups.
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

import asyncpg
import httpx
from redis.asyncio import Redis

from driftline.clock import Clock, SystemClock
from driftline.config import Settings
from driftline.ingest.chunker import chunk_sections
from driftline.ingest.connectors.k8s_docs import KubernetesDocsConnector
from driftline.ingest.connectors.openfda import OpenFDAConnector
from driftline.ingest.connectors.upload import UploadConnector
from driftline.ingest.embed import EmbedStage
from driftline.ingest.store import load_cursor, save_cursor, upsert_version
from driftline.ingest.supersession import SupersessionExtractor
from driftline.ingest.types import Connector, SourceFetchError
from driftline.streams.bus import StreamBus, keepalive_interval_ms

INGEST_STREAM = "ingest"
EMBED_STREAM = "embed"
INGEST_GROUP = "ingest-workers"
EMBED_GROUP = "embed-workers"
RECLAIM_IDLE_MS = 60_000  # spec section 3: reclaim stalled messages after 60 s
KEEPALIVE_MS = keepalive_interval_ms(RECLAIM_IDLE_MS)
DEDUPE_TTL_S = 7 * 24 * 3600
FAILURE_TTL_S = 7 * 24 * 3600  # how long one failed job is remembered as already counted

ConnectorFactory = Callable[[str, dict[str, Any]], Connector]


# --- one rule for "stale" -------------------------------------------------------------
# A source is `stale_source` once its fetches have failed `stale_after_failures` times in
# a row. Failed scheduler discoveries (`driftline.drift.worker.SourcePoller`) and failed
# ingest fetches feed the same Redis streak; a successful fetch or discovery resets it.


def failure_key(source_id: UUID) -> str:
    return f"poll:failures:{source_id}"


async def record_fetch_failure(
    db: asyncpg.Pool | asyncpg.Connection,
    redis: Redis,
    source_id: UUID,
    *,
    stale_after: int,
    attempt: str | None = None,
) -> bool:
    """Count one failed fetch towards the source's streak; returns True when this failure
    marked the source `stale_source`. `attempt` names the failure (an ingest job id): a
    redelivery of the same failed job is not counted twice."""
    if attempt is not None:
        first = await redis.set(
            f"{failure_key(source_id)}:attempt:{attempt}", "1", nx=True, ex=FAILURE_TTL_S
        )
        if not first:
            return False
    streak = await redis.incr(failure_key(source_id))
    if streak < stale_after:
        return False
    marked = await db.fetchval(
        "UPDATE sources SET status = 'stale_source' WHERE id = $1 AND status = 'active' "
        "RETURNING id",
        source_id,
    )
    return marked is not None


async def clear_fetch_failures(redis: Redis, source_id: UUID) -> None:
    await redis.delete(failure_key(source_id))


def default_connector_factory(settings: Settings, http: httpx.AsyncClient) -> ConnectorFactory:
    def build(kind: str, config: dict[str, Any]) -> Connector:
        if kind == "openfda":
            return OpenFDAConnector(
                http,
                search=config.get("search", "_exists_:boxed_warning"),
                limit=int(config.get("limit", 10)),
                api_key=settings.openfda_api_key,
            )
        if kind == "git_docs":
            kwargs = {
                k: config[k] for k in ("branches", "paths", "repo", "release_repo") if k in config
            }
            return KubernetesDocsConnector(http, github_token=settings.github_token, **kwargs)
        if kind == "upload":
            return UploadConnector(config.get("root", settings.upload_root))
        raise ValueError(f"unknown source kind {kind!r}")

    return build


async def ensure_source(
    conn: asyncpg.Connection, *, tenant: str, kind: str, config: dict[str, Any]
) -> UUID:
    """Find or create the tenant and a source of this kind with exactly this config."""
    tenant_id = await conn.fetchval(
        "INSERT INTO tenants (name, api_key_hash) VALUES ($1, '') "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        tenant,
    )
    source_id = await conn.fetchval(
        "SELECT id FROM sources WHERE tenant_id = $1 AND kind = $2 AND config = $3::jsonb",
        tenant_id,
        kind,
        json.dumps(config),
    )
    if source_id is None:
        source_id = await conn.fetchval(
            "INSERT INTO sources (tenant_id, kind, config) VALUES ($1, $2, $3::jsonb) RETURNING id",
            tenant_id,
            kind,
            json.dumps(config),
        )
    return source_id


async def enqueue_ingest(
    pool: asyncpg.Pool, bus: StreamBus, *, source_id: UUID, external_id: str
) -> UUID:
    async with pool.acquire() as conn:
        tenant_id = await conn.fetchval("SELECT tenant_id FROM sources WHERE id = $1", source_id)
        job_id = await conn.fetchval(
            "INSERT INTO jobs (tenant_id, kind) VALUES ($1, 'ingest') RETURNING id", tenant_id
        )
    await bus.publish(
        INGEST_STREAM,
        {"job_id": str(job_id), "source_id": str(source_id), "external_id": external_id},
    )
    return job_id


class IngestWorker:
    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        bus: StreamBus,
        redis: Redis,
        connector_factory: ConnectorFactory,
        embed_stage: EmbedStage,
        extractor: SupersessionExtractor | None,
        consumer: str,
        chunk_tokens: int = 256,
        overlap_tokens: int = 32,
        clock: Clock | None = None,
        stale_after_failures: int = 3,
    ) -> None:
        if stale_after_failures < 1:
            raise ValueError("stale_after_failures must be at least 1")
        self._stale_after = stale_after_failures
        self._pool = pool
        self._bus = bus
        self._redis = redis
        self._factory = connector_factory
        self._embed = embed_stage
        self._extractor = extractor
        self._consumer = consumer
        self._chunk_tokens = chunk_tokens
        self._overlap_tokens = overlap_tokens
        self._clock = clock or SystemClock()

    async def setup(self) -> None:
        await self._bus.ensure_group(INGEST_STREAM, INGEST_GROUP)
        await self._bus.ensure_group(EMBED_STREAM, EMBED_GROUP)

    async def handle_ingest(self, msg_id: str, payload: dict[str, Any]) -> None:
        job_id, source_id = UUID(payload["job_id"]), UUID(payload["source_id"])
        external_id = payload["external_id"]
        async with self._pool.acquire() as conn:
            await conn.execute("UPDATE jobs SET status = 'running' WHERE id = $1", job_id)
            source = await conn.fetchrow(
                "SELECT kind, config FROM sources WHERE id = $1", source_id
            )
            if source is None:
                raise LookupError(f"source {source_id} not found")
            connector = self._factory(source["kind"], json.loads(source["config"]))
            try:
                cursor = await load_cursor(conn, source_id, external_id)
                async for raw in connector.fetch(external_id, since=cursor):
                    chunks = chunk_sections(
                        raw.sections,
                        chunk_tokens=self._chunk_tokens,
                        overlap_tokens=self._overlap_tokens,
                    )
                    await upsert_version(conn, source_id=source_id, raw=raw, chunks=chunks)
                    await save_cursor(conn, source_id, external_id, raw.version_key)
            except SourceFetchError as exc:
                await record_fetch_failure(
                    conn,
                    self._redis,
                    source_id,
                    stale_after=self._stale_after,
                    attempt=str(job_id),
                )
                await conn.execute(
                    "UPDATE jobs SET status = 'failed', error = $2, finished_at = now() "
                    "WHERE id = $1",
                    job_id,
                    str(exc),
                )
                raise
            await conn.execute(
                "UPDATE sources SET status = 'active', last_polled_at = now() WHERE id = $1",
                source_id,
            )
            await clear_fetch_failures(self._redis, source_id)
            await conn.execute(
                "UPDATE jobs SET status = 'succeeded', error = NULL, finished_at = now() "
                "WHERE id = $1",
                job_id,
            )

    async def handle_embed(self, msg_id: str, payload: dict[str, Any]) -> None:
        """Consumes `version.created` events; dedupes on event_id after success."""
        dedupe_key = f"dedupe:{EMBED_STREAM}:{payload['event_id']}"
        if await self._redis.exists(dedupe_key):
            return
        version_id = UUID(payload["version_id"])
        async with self._pool.acquire() as conn:
            await self._embed.embed_version(conn, version_id)
            if self._extractor is not None:
                await self._extractor.extract_for_version(conn, version_id)
        await self._redis.set(dedupe_key, "1", ex=DEDUPE_TTL_S)

    async def run_once(self, *, block_ms: int = 100) -> int:
        """One poll of both streams plus a reclaim pass; returns messages processed."""
        processed = 0
        for stream, group, handler in (
            (INGEST_STREAM, INGEST_GROUP, self.handle_ingest),
            (EMBED_STREAM, EMBED_GROUP, self.handle_embed),
        ):
            # Fetching a large source or embedding and extracting a long version can outlast
            # the reclaim window: keep the claim alive so no other worker reruns it.
            result = await self._bus.consume_once(
                stream, group, self._consumer, handler, block_ms=block_ms, keepalive_ms=KEEPALIVE_MS
            )
            reclaimed = await self._bus.reclaim_once(
                stream,
                group,
                self._consumer,
                handler,
                min_idle_ms=RECLAIM_IDLE_MS,
                keepalive_ms=KEEPALIVE_MS,
            )
            processed += result.processed + reclaimed.processed
        return processed

    async def run(self, stop: asyncio.Event) -> None:
        await self.setup()
        while not stop.is_set():
            if await self.run_once(block_ms=1000) == 0:
                await self._clock.sleep(0.1)
