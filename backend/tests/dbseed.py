"""Seed rows for tests with plain SQL against a migrated database."""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

EMBED_MODEL = "BAAI/bge-base-en-v1.5"


async def seed_tenant(
    conn: asyncpg.Connection, name: str | None = None, *, api_key: str | None = "test-key"
) -> UUID:
    """Create a tenant whose API key is `api_key` (its sha256 is stored).

    With `api_key=None` the stored hash is a placeholder that no key hashes to. Give
    each tenant of one test its own key: a key identifies exactly one tenant.
    """
    from driftline.auth import hash_api_key

    return await conn.fetchval(
        "INSERT INTO tenants (name, api_key_hash) VALUES ($1, $2) RETURNING id",
        name or f"t-{uuid.uuid4()}",
        hash_api_key(api_key) if api_key is not None else "x",
    )


async def seed_source(
    conn: asyncpg.Connection,
    *,
    kind: str = "upload",
    config: dict[str, Any] | None = None,
    tenant: str | None = None,
    api_key: str | None = None,
) -> tuple[UUID, UUID]:
    """Create a tenant and one source; returns (tenant_id, source_id)."""
    tenant_id = await seed_tenant(conn, tenant, api_key=api_key)
    source_id = await conn.fetchval(
        "INSERT INTO sources (tenant_id, kind, config) VALUES ($1, $2, $3::jsonb) RETURNING id",
        tenant_id,
        kind,
        json.dumps(config or {}),
    )
    return tenant_id, source_id


async def seed_version(
    conn: asyncpg.Connection,
    source_id: UUID,
    *,
    external_id: str = "doc",
    title: str = "Doc",
    texts: Sequence[tuple[str, str]] = (("A", "alpha"),),
    tags: Sequence[Sequence[str]] | None = None,
    valid_from: datetime | None = None,
    diff: dict[str, Any] | None = None,
) -> tuple[UUID, UUID]:
    """Create a document with ONE open version and one chunk per (section_path, text).

    Returns (document_id, version_id). Seed at most one version per document: a second
    open version would overlap the first and violate the exclusion constraint.
    """
    document_id = await conn.fetchval(
        "INSERT INTO documents (source_id, external_id, title) VALUES ($1, $2, $3) "
        "ON CONFLICT (source_id, external_id) DO UPDATE SET title = EXCLUDED.title RETURNING id",
        source_id,
        external_id,
        title,
    )
    version_id = await conn.fetchval(
        "INSERT INTO doc_versions (document_id, version_no, content_hash, valid_from, "
        "diff_from_prev) VALUES ($1, 1, $2, $3, $4::jsonb) RETURNING id",
        document_id,
        f"seed-{uuid.uuid4()}",
        valid_from or datetime(2024, 1, 1, tzinfo=UTC),
        json.dumps(diff) if diff is not None else None,
    )
    for ord_, (path, text) in enumerate(texts):
        chunk_tags = list(tags[ord_]) if tags is not None else []
        await conn.execute(
            "INSERT INTO chunks (version_id, ord, section_path, text, tags) "
            "VALUES ($1, $2, $3, $4, $5)",
            version_id,
            ord_,
            path,
            text,
            chunk_tags,
        )
    return document_id, version_id


@dataclass(frozen=True)
class VersionSeed:
    """One version of a document for `seed_history`. Ids are optional so recorded
    LLM responses (which quote chunk and version ids) can replay against fixed ids."""

    valid_from: datetime
    texts: Sequence[tuple[str, str]]
    version_key: str | None = None
    version_id: UUID | None = None
    chunk_ids: Sequence[UUID] | None = None
    tags: Sequence[Sequence[str]] | None = None


async def seed_history(
    conn: asyncpg.Connection,
    source_id: UUID,
    *,
    external_id: str,
    title: str,
    versions: Sequence[VersionSeed],
    document_id: UUID | None = None,
) -> tuple[UUID, list[UUID], list[list[UUID]]]:
    """A document with consecutive versions: each version's window closes when the next
    one starts, and the last stays open. Returns (document_id, version_ids, chunk_ids)."""
    document_id = await conn.fetchval(
        "INSERT INTO documents (id, source_id, external_id, title) "
        "VALUES (coalesce($1, gen_random_uuid()), $2, $3, $4) RETURNING id",
        document_id,
        source_id,
        external_id,
        title,
    )
    version_ids: list[UUID] = []
    chunk_ids: list[list[UUID]] = []
    for n, seed in enumerate(versions, start=1):
        valid_to = versions[n].valid_from if n < len(versions) else None
        version_id = await conn.fetchval(
            "INSERT INTO doc_versions (id, document_id, version_no, content_hash, valid_from, "
            "valid_to, version_key) VALUES (coalesce($1, gen_random_uuid()), $2, $3, $4, $5, "
            "$6, $7) RETURNING id",
            seed.version_id,
            document_id,
            n,
            f"seed-{uuid.uuid4()}",
            seed.valid_from,
            valid_to,
            seed.version_key,
        )
        ids = []
        for ord_, (path, text) in enumerate(seed.texts):
            ids.append(
                await conn.fetchval(
                    "INSERT INTO chunks (id, version_id, ord, section_path, text, tags) "
                    "VALUES (coalesce($1, gen_random_uuid()), $2, $3, $4, $5, $6) RETURNING id",
                    seed.chunk_ids[ord_] if seed.chunk_ids else None,
                    version_id,
                    ord_,
                    path,
                    text,
                    list(seed.tags[ord_]) if seed.tags else [],
                )
            )
        version_ids.append(version_id)
        chunk_ids.append(ids)
    return document_id, version_ids, chunk_ids


async def embed_all(conn: asyncpg.Connection, embedder_url: str) -> int:
    """Embed every chunk that has no embedding yet with the real TEI embedder."""
    from driftline.clock import ManualClock
    from driftline.ingest.embed import EmbedStage
    from driftline.llm.adapters.tei import TEIEmbeddingAdapter
    from driftline.llm.router import LLMRouter, Route

    router = LLMRouter(
        providers={"tei": TEIEmbeddingAdapter(embedder_url)},
        chains={"embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    stage = EmbedStage(router, model_name=EMBED_MODEL)
    done = 0
    for row in await conn.fetch("SELECT DISTINCT version_id FROM chunks WHERE embedding IS NULL"):
        done += await stage.embed_version(conn, row["version_id"])
    return done


async def seed_watched_answer(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    version_id: UUID,
    chunk_ids: Sequence[UUID],
    claims: Sequence[tuple[str, str]],
    *,
    question: str = "What does the document say?",
    as_of: datetime | None = None,
    confidence: float = 0.9,
) -> UUID:
    """A watched answer whose claim i, given as (text, quote), cites chunk_ids[i] in
    version_id. Writes the answer body (AnswerSchema JSON) and answer_citations."""
    from driftline.agents.schemas import AnswerSchema, Citation, Claim

    if len(chunk_ids) != len(claims):
        raise ValueError("one chunk id per claim")
    as_of = as_of or datetime(2024, 6, 1, tzinfo=UTC)
    claim_models = [
        Claim(
            idx=idx,
            text=text,
            citations=[Citation(chunk_id=chunk_id, version_id=version_id, quote=quote)],
            verified=True,
        )
        for idx, (chunk_id, (text, quote)) in enumerate(zip(chunk_ids, claims, strict=True))
    ]
    body = AnswerSchema(
        status="answered",
        answer=" ".join(c.text for c in claim_models),
        claims=claim_models,
        citations=[c.citations[0] for c in claim_models],
        as_of=as_of,
        confidence=confidence,
    )
    answer_id = await conn.fetchval(
        "INSERT INTO answers (tenant_id, question, as_of, body, confidence, watched, watched_at) "
        "VALUES ($1, $2, $3, $4::jsonb, $5, true, now()) RETURNING id",
        tenant_id,
        question,
        as_of,
        body.model_dump_json(),
        confidence,
    )
    await conn.executemany(
        "INSERT INTO answer_citations (answer_id, claim_idx, chunk_id) VALUES ($1, $2, $3)",
        [(answer_id, idx, chunk_id) for idx, chunk_id in enumerate(chunk_ids)],
    )
    return answer_id
