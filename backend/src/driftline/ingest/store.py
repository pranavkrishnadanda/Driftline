"""Version store: one transaction per new version (close previous window, insert, outbox)."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import asyncpg

from driftline.ingest.chunker import ChunkDraft
from driftline.ingest.hashing import content_hash, diff_sections, section_hashes
from driftline.ingest.types import RawDocument

VERSION_CREATED = "version.created"
# A version whose valid_from is not after its predecessor's starts this much later,
# so validity windows stay half-open, ordered and non-empty.
MIN_WINDOW = timedelta(seconds=1)


@dataclass(frozen=True)
class UpsertResult:
    document_id: UUID
    version_id: UUID
    version_no: int
    created: bool
    valid_from: datetime
    prev_version_id: UUID | None
    outbox_id: int | None


async def upsert_version(
    conn: asyncpg.Connection,
    *,
    source_id: UUID,
    raw: RawDocument,
    chunks: Sequence[ChunkDraft],
) -> UpsertResult:
    """No-op when the content equals the current version's; everything commits or nothing does."""
    hashes = section_hashes(raw.sections)
    digest = content_hash(raw.sections)
    async with conn.transaction():
        document_id = await conn.fetchval(
            "INSERT INTO documents (source_id, external_id, title) VALUES ($1, $2, $3) "
            "ON CONFLICT (source_id, external_id) DO UPDATE SET title = EXCLUDED.title "
            "RETURNING id",
            source_id,
            raw.external_id,
            raw.title,
        )
        # The upsert row-locks the document until commit, so concurrent writers of one
        # document serialise here and the second one sees the first one's version.
        prev = await conn.fetchrow(
            "SELECT id, version_no, valid_from, content_hash, section_hashes FROM doc_versions "
            "WHERE document_id = $1 ORDER BY version_no DESC LIMIT 1",
            document_id,
        )
        # Only the current version's content is a no-op. Content equal to an older,
        # closed version is a revert (A -> B -> A) and gets its own version and window.
        if prev is not None and prev["content_hash"] == digest:
            return UpsertResult(
                document_id, prev["id"], prev["version_no"], False, prev["valid_from"], None, None
            )
        valid_from = raw.valid_from
        diff: dict | None = None
        if prev is not None:
            if valid_from <= prev["valid_from"]:
                valid_from = prev["valid_from"] + MIN_WINDOW
            diff = dict(diff_sections(json.loads(prev["section_hashes"]), hashes))
            if valid_from != raw.valid_from:
                diff["valid_from_adjusted"] = {
                    "requested": raw.valid_from.isoformat(),
                    "applied": valid_from.isoformat(),
                }
            await conn.execute(
                "UPDATE doc_versions SET valid_to = $2 WHERE id = $1", prev["id"], valid_from
            )
        version_no = (prev["version_no"] if prev else 0) + 1
        version_id = await conn.fetchval(
            "INSERT INTO doc_versions (document_id, version_no, content_hash, valid_from, "
            "raw_uri, diff_from_prev, version_key, section_hashes, source_meta) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8::jsonb, $9::jsonb) RETURNING id",
            document_id,
            version_no,
            digest,
            valid_from,
            raw.raw_uri,
            json.dumps(diff) if diff is not None else None,
            raw.version_key,
            json.dumps(hashes),
            json.dumps(raw.source_meta),
        )
        await conn.executemany(
            "INSERT INTO chunks (version_id, ord, section_path, text, tags) "
            "VALUES ($1, $2, $3, $4, $5)",
            [(version_id, c.ord, c.section_path, c.text, list(c.tags)) for c in chunks],
        )
        prev_id = prev["id"] if prev else None
        outbox_id = await conn.fetchval(
            "INSERT INTO outbox (topic, payload) VALUES ($1, $2::jsonb) RETURNING id",
            VERSION_CREATED,
            json.dumps(
                {
                    "type": VERSION_CREATED,
                    "source_id": str(source_id),
                    "document_id": str(document_id),
                    "external_id": raw.external_id,
                    "version_id": str(version_id),
                    "version_no": version_no,
                    "prev_version_id": str(prev_id) if prev_id else None,
                    "valid_from": valid_from.isoformat(),
                    "diff": diff,
                }
            ),
        )
        return UpsertResult(
            document_id, version_id, version_no, True, valid_from, prev_id, outbox_id
        )


async def load_cursor(conn: asyncpg.Connection, source_id: UUID, external_id: str) -> str | None:
    return await conn.fetchval(
        "SELECT cursor FROM source_cursors WHERE source_id = $1 AND external_id = $2",
        source_id,
        external_id,
    )


async def save_cursor(
    conn: asyncpg.Connection, source_id: UUID, external_id: str, cursor: str
) -> None:
    await conn.execute(
        "INSERT INTO source_cursors (source_id, external_id, cursor) VALUES ($1, $2, $3) "
        "ON CONFLICT (source_id, external_id) DO UPDATE "
        "SET cursor = EXCLUDED.cursor, updated_at = now()",
        source_id,
        external_id,
        cursor,
    )
