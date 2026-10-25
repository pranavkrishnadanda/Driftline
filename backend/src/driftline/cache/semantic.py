"""Semantic answer cache (spec section 4).

A hit needs all of: the same tenant, the same as_of day (UTC), the same corpus filter, a
question embedding with cosine similarity >= threshold, and every version the cached
answer cites still in force at the requested as_of and owned by the tenant. When the
closest match fails that check it is evicted and the next closest one is tried. Entries are also indexed by cited
version id, so `invalidate_versions` drops every answer that cites a superseded version
(the drift engine in P4 calls it; lookups re-check validity regardless).

Every lookup also counts a hit or a miss in a per-tenant Redis hash (`lookup_counts`),
which `GET /v1/stats` reports as the cache hit rate. The counter lives under its own
`semstats:` namespace, never under `semcache:`, so anything that scans or clears cache
entries by pattern neither mistakes it for an entry nor wipes the stats.
"""

import json
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg
from redis.asyncio import Redis

from driftline.llm.router import LLMRouter

PREFIX = "semcache"
STATS_PREFIX = "semstats"  # deliberately outside PREFIX; see the module docstring
IN_FORCE_COUNT = (
    "SELECT count(*) FROM doc_versions v "
    "JOIN documents d ON d.id = v.document_id JOIN sources s ON s.id = d.source_id "
    "WHERE v.id = ANY($1::uuid[]) AND s.tenant_id = $3 "
    "AND v.valid_from <= $2 AND ($2 < v.valid_to OR v.valid_to IS NULL)"
)


@dataclass(frozen=True)
class CacheHit:
    entry_id: str
    similarity: float
    question: str
    answer: dict[str, Any]
    version_ids: list[UUID]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def bucket_key(tenant_id: UUID, as_of: datetime, source_kinds: Sequence[str] | None) -> str:
    if as_of.tzinfo is None:
        raise ValueError("as_of must carry a timezone")
    kinds = ",".join(sorted(source_kinds)) if source_kinds else "all"
    day = as_of.astimezone(UTC).date().isoformat()
    return f"{PREFIX}:bucket:{tenant_id}:{day}:{kinds}"


def _entry_key(entry_id: str) -> str:
    return f"{PREFIX}:entry:{entry_id}"


def _version_key(version_id: UUID) -> str:
    return f"{PREFIX}:version:{version_id}"


def _counts_key(tenant_id: UUID) -> str:
    return f"{STATS_PREFIX}:{tenant_id}"


async def lookup_counts(redis: Redis, tenant_id: UUID) -> tuple[int, int]:
    """(hits, misses) of this tenant's cache lookups since the counter was created."""
    hits, misses = await redis.hmget(_counts_key(tenant_id), ["hits", "misses"])
    return int(hits or 0), int(misses or 0)


async def invalidate_versions(redis: Redis, version_ids: Sequence[UUID]) -> int:
    """Drop every cached answer that cites any of these versions; returns how many.

    Needs only Redis (no embedder), so the outbox relay can run it for a
    `cache.invalidate` row. Idempotent: a redelivered row drops nothing more."""
    dropped = 0
    for version_id in version_ids:
        key = _version_key(version_id)
        for entry_id in await redis.smembers(key):
            dropped += await redis.delete(_entry_key(entry_id))
        await redis.delete(key)
    return dropped


class SemanticCache:
    def __init__(
        self,
        redis: Redis,
        router: LLMRouter,
        *,
        threshold: float = 0.95,
        ttl_s: int = 7 * 24 * 3600,
        max_entries_per_bucket: int = 200,
        dim: int = 768,
        tier: str = "embed",
    ) -> None:
        self._redis = redis
        self._router = router
        self._threshold = threshold
        self._ttl_s = ttl_s
        self._max = max_entries_per_bucket
        self._dim = dim
        self._tier = tier

    async def embed(self, question: str) -> list[float]:
        [vector] = await self._router.embed(self._tier, [question], self._dim)
        return vector

    async def lookup(
        self,
        conn: asyncpg.Connection,
        *,
        tenant_id: UUID,
        question: str,
        as_of: datetime,
        source_kinds: Sequence[str] | None = None,
        vector: list[float] | None = None,
    ) -> CacheHit | None:
        hit = await self._find(conn, tenant_id, question, as_of, source_kinds, vector)
        await self._redis.hincrby(_counts_key(tenant_id), "hits" if hit else "misses", 1)
        return hit

    async def _find(
        self,
        conn: asyncpg.Connection,
        tenant_id: UUID,
        question: str,
        as_of: datetime,
        source_kinds: Sequence[str] | None,
        vector: list[float] | None,
    ) -> CacheHit | None:
        bucket = bucket_key(tenant_id, as_of, source_kinds)
        entry_ids = await self._redis.lrange(bucket, 0, -1)
        if not entry_ids:
            return None
        vector = vector if vector is not None else await self.embed(question)
        raw = await self._redis.mget([_entry_key(e) for e in entry_ids])
        candidates: list[tuple[float, str, dict[str, Any]]] = []
        for entry_id, blob in zip(entry_ids, raw, strict=True):
            if blob is None:  # expired or invalidated
                await self._redis.lrem(bucket, 0, entry_id)
                continue
            entry = json.loads(blob)
            score = cosine(vector, entry["vector"])
            if score >= self._threshold:
                candidates.append((score, entry_id, entry))
        candidates.sort(key=lambda c: c[0], reverse=True)
        for score, entry_id, entry in candidates:
            version_ids = [UUID(v) for v in entry["version_ids"]]
            if version_ids:
                in_force = await conn.fetchval(IN_FORCE_COUNT, version_ids, as_of, tenant_id)
                if in_force != len(version_ids):
                    await self._delete(entry_id, version_ids, bucket)
                    continue
            return CacheHit(entry_id, score, entry["question"], entry["answer"], version_ids)
        return None

    async def store(
        self,
        *,
        tenant_id: UUID,
        question: str,
        as_of: datetime,
        answer: dict[str, Any],
        version_ids: Sequence[UUID],
        source_kinds: Sequence[str] | None = None,
        vector: list[float] | None = None,
    ) -> str:
        vector = vector if vector is not None else await self.embed(question)
        entry_id = uuid.uuid4().hex
        bucket = bucket_key(tenant_id, as_of, source_kinds)
        unique_versions = sorted({str(v) for v in version_ids})
        blob = json.dumps(
            {
                "question": question,
                "vector": vector,
                "answer": answer,
                "version_ids": unique_versions,
                "bucket": bucket,
            }
        )
        pipe = self._redis.pipeline(transaction=True)
        pipe.set(_entry_key(entry_id), blob, ex=self._ttl_s)
        pipe.lpush(bucket, entry_id)
        pipe.ltrim(bucket, 0, self._max - 1)
        pipe.expire(bucket, self._ttl_s)
        for version_id in unique_versions:
            pipe.sadd(_version_key(UUID(version_id)), entry_id)
            pipe.expire(_version_key(UUID(version_id)), self._ttl_s)
        await pipe.execute()
        return entry_id

    async def invalidate_versions(self, version_ids: Sequence[UUID]) -> int:
        """Drop every cached answer that cites any of these versions; returns how many."""
        return await invalidate_versions(self._redis, version_ids)

    async def _delete(self, entry_id: str, version_ids: Sequence[UUID], bucket: str) -> None:
        pipe = self._redis.pipeline(transaction=True)
        pipe.delete(_entry_key(entry_id))
        pipe.lrem(bucket, 0, entry_id)
        for version_id in version_ids:
            pipe.srem(_version_key(version_id), entry_id)
        await pipe.execute()
