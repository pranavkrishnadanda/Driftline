"""Seed rows for ingestion tests with plain SQL against a migrated database."""

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg


async def seed_source(
    conn: asyncpg.Connection,
    *,
    kind: str = "upload",
    config: dict[str, Any] | None = None,
    tenant: str | None = None,
) -> tuple[UUID, UUID]:
    """Create a tenant and one source; returns (tenant_id, source_id)."""
    tenant_id = await conn.fetchval(
        "INSERT INTO tenants (name, api_key_hash) VALUES ($1, 'x') RETURNING id",
        tenant or f"t-{uuid.uuid4()}",
    )
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
