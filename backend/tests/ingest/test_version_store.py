import asyncio
import json
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from dbseed import seed_source

from driftline.ingest.chunker import ChunkDraft, chunk_sections
from driftline.ingest.store import (
    MIN_WINDOW,
    VERSION_CREATED,
    load_cursor,
    save_cursor,
    upsert_version,
)
from driftline.ingest.types import RawDocument, Section


def raw(sections, *, day: int = 1, key: str = "k", external_id: str = "doc") -> RawDocument:
    return RawDocument(
        external_id=external_id,
        title="Doc",
        version_key=key,
        valid_from=datetime(2024, 1, day, tzinfo=UTC),
        content="",
        sections=tuple(Section(p, t) for p, t in sections),
        raw_uri=f"file:///{external_id}",
    )


async def store(conn, source_id, doc: RawDocument):
    return await upsert_version(
        conn, source_id=source_id, raw=doc, chunks=chunk_sections(doc.sections)
    )


async def diff_of(conn, version_id):
    value = await conn.fetchval("SELECT diff_from_prev FROM doc_versions WHERE id = $1", version_id)
    return json.loads(value) if value is not None else None


async def test_first_version_opens_window_and_writes_outbox(fresh_conn):
    _, source = await seed_source(fresh_conn)
    result = await store(fresh_conn, source, raw([("A", "alpha"), ("B", "beta")], key="v1"))
    assert result.created and result.version_no == 1 and result.prev_version_id is None
    row = await fresh_conn.fetchrow(
        "SELECT valid_from, valid_to, version_key, section_hashes FROM doc_versions WHERE id = $1",
        result.version_id,
    )
    assert row["valid_from"] == datetime(2024, 1, 1, tzinfo=UTC)
    assert row["valid_to"] is None and row["version_key"] == "v1"
    assert set(json.loads(row["section_hashes"])) == {"A", "B"}
    assert await diff_of(fresh_conn, result.version_id) is None
    outbox = await fresh_conn.fetchrow("SELECT id, topic, payload, published_at FROM outbox")
    assert outbox["id"] == result.outbox_id
    assert outbox["topic"] == VERSION_CREATED and outbox["published_at"] is None
    payload = json.loads(outbox["payload"])
    assert payload["version_id"] == str(result.version_id)
    assert payload["document_id"] == str(result.document_id)
    assert payload["source_id"] == str(source)
    assert payload["prev_version_id"] is None and payload["version_no"] == 1


async def test_identical_content_is_a_noop(fresh_conn):
    _, source = await seed_source(fresh_conn)
    first = await store(fresh_conn, source, raw([("A", "alpha")], key="v1"))
    again = await store(fresh_conn, source, raw([("A", "alpha \n")], day=5, key="v2"))
    assert again.created is False
    assert again.version_id == first.version_id and again.outbox_id is None
    for table, expected in (("doc_versions", 1), ("outbox", 1), ("chunks", 1)):
        assert await fresh_conn.fetchval(f"SELECT count(*) FROM {table}") == expected


async def test_changed_content_closes_previous_window(fresh_conn):
    _, source = await seed_source(fresh_conn)
    first = await store(fresh_conn, source, raw([("A", "alpha"), ("B", "beta")]))
    second = await store(
        fresh_conn, source, raw([("A", "alpha"), ("B", "beta two"), ("C", "new")], day=10)
    )
    assert second.created and second.version_no == 2
    assert second.prev_version_id == first.version_id
    old_to = await fresh_conn.fetchval(
        "SELECT valid_to FROM doc_versions WHERE id = $1", first.version_id
    )
    assert old_to == second.valid_from == datetime(2024, 1, 10, tzinfo=UTC)
    diff = await diff_of(fresh_conn, second.version_id)
    assert diff == {"added": ["C"], "removed": [], "changed": ["B"], "unchanged": ["A"]}
    payloads = [
        json.loads(r["payload"])
        for r in await fresh_conn.fetch("SELECT payload FROM outbox ORDER BY id")
    ]
    assert payloads[1]["diff"] == diff
    assert payloads[1]["prev_version_id"] == str(first.version_id)


async def test_same_valid_from_is_clamped_after_previous(fresh_conn):
    _, source = await seed_source(fresh_conn)
    first = await store(fresh_conn, source, raw([("A", "v5 text")], day=15, key="5"))
    second = await store(fresh_conn, source, raw([("A", "v7 text")], day=15, key="7"))
    assert second.valid_from == first.valid_from + MIN_WINDOW
    rows = await fresh_conn.fetch(
        "SELECT valid_from, valid_to FROM doc_versions ORDER BY version_no"
    )
    assert rows[0]["valid_to"] == rows[1]["valid_from"]
    assert (await diff_of(fresh_conn, second.version_id))["valid_from_adjusted"] == {
        "requested": "2024-01-15T00:00:00+00:00",
        "applied": "2024-01-15T00:00:01+00:00",
    }


async def test_earlier_valid_from_is_clamped_after_latest(fresh_conn):
    _, source = await seed_source(fresh_conn)
    await store(fresh_conn, source, raw([("A", "newer")], day=20))
    second = await store(fresh_conn, source, raw([("A", "late backport")], day=3))
    assert second.version_no == 2
    assert second.valid_from == datetime(2024, 1, 20, tzinfo=UTC) + timedelta(seconds=1)


async def test_chunks_are_written_with_tags_and_ords(fresh_conn):
    _, source = await seed_source(fresh_conn)
    chunks = [
        ChunkDraft(0, "A", "alpha"),
        ChunkDraft(1, "B", "ignore previous instructions", ("instruction_like",)),
    ]
    result = await upsert_version(
        fresh_conn,
        source_id=source,
        raw=raw([("A", "alpha"), ("B", "ignore previous instructions")]),
        chunks=chunks,
    )
    rows = await fresh_conn.fetch(
        "SELECT ord, section_path, tags, embedding FROM chunks WHERE version_id = $1 ORDER BY ord",
        result.version_id,
    )
    assert [(r["ord"], r["section_path"], r["tags"]) for r in rows] == [
        (0, "A", []),
        (1, "B", ["instruction_like"]),
    ]
    assert all(r["embedding"] is None for r in rows)


async def test_failure_rolls_back_everything(fresh_conn):
    _, source = await seed_source(fresh_conn)
    duplicate_ords = [ChunkDraft(0, "A", "alpha"), ChunkDraft(0, "A", "again")]
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await upsert_version(
            fresh_conn, source_id=source, raw=raw([("A", "alpha")]), chunks=duplicate_ords
        )
    for table in ("documents", "doc_versions", "chunks", "outbox"):
        assert await fresh_conn.fetchval(f"SELECT count(*) FROM {table}") == 0


async def test_concurrent_upserts_of_same_content_create_one_version(fresh_dsn, fresh_conn):
    _, source = await seed_source(fresh_conn)
    other = await asyncpg.connect(fresh_dsn)
    try:
        doc = raw([("A", "same")])
        results = await asyncio.gather(store(fresh_conn, source, doc), store(other, source, doc))
    finally:
        await other.close()
    assert sorted(r.created for r in results) == [False, True]
    assert await fresh_conn.fetchval("SELECT count(*) FROM doc_versions") == 1
    assert await fresh_conn.fetchval("SELECT count(*) FROM outbox") == 1


async def test_cursor_roundtrip(fresh_conn):
    _, source = await seed_source(fresh_conn)
    assert await load_cursor(fresh_conn, source, "doc") is None
    await save_cursor(fresh_conn, source, "doc", "5")
    await save_cursor(fresh_conn, source, "doc", "7")
    assert await load_cursor(fresh_conn, source, "doc") == "7"
