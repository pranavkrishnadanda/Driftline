"""Drift engine: re-check watched answers against the latest version of a changed
document. Real Postgres (fresh database per test), the real version store, and
DeterministicAdapter with the offline ExtractiveResponder as the judge."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from dbseed import seed_source, seed_watched_answer

from driftline.agents.events import AlertEvent
from driftline.agents.offline import ExtractiveResponder
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.drift.engine import DriftEngine
from driftline.ingest.chunker import chunk_sections
from driftline.ingest.store import upsert_version
from driftline.ingest.types import RawDocument, Section
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.router import LLMRouter, Route

DOSAGE = ("Dosage", "Take 10 mg once daily with water.")
LIVER = ("Liver", "Check ALT monthly during therapy.")
WARNINGS = ("Warnings", "Avoid grapefruit juice.")
CLAIM = ("Check ALT monthly during therapy.", "Check ALT monthly during therapy.")


@pytest.fixture
def judge():
    return DeterministicAdapter("det", responder=ExtractiveResponder())


@pytest.fixture
def engine(fresh_pool, judge):
    router = LLMRouter(
        providers={"det": judge},
        chains={"judge": [Route("det", "judge-model")]},
        clock=ManualClock(),
    )
    return DriftEngine(fresh_pool, router, ManualClock(1_750_000_000), Settings(_env_file=None))


async def store(conn, source_id, sections, *, day: int, external_id: str = "lipitor"):
    raw = RawDocument(
        external_id=external_id,
        title="Lipitor label",
        version_key=f"v{day}",
        valid_from=datetime(2024, 1, day, tzinfo=UTC),
        content="",
        sections=tuple(Section(p, t) for p, t in sections),
        raw_uri=f"file:///{external_id}",
    )
    return await upsert_version(
        conn, source_id=source_id, raw=raw, chunks=chunk_sections(raw.sections)
    )


async def event_for(conn, result) -> dict:
    """The version.created message exactly as the outbox relay publishes it."""
    row = await conn.fetchrow(
        "SELECT id, topic, payload FROM outbox WHERE id = $1", result.outbox_id
    )
    return {**json.loads(row["payload"]), "event_id": row["id"], "topic": row["topic"]}


async def chunk_of(conn, version_id, section_path):
    return await conn.fetchval(
        "SELECT id FROM chunks WHERE version_id = $1 AND section_path = $2 ORDER BY ord LIMIT 1",
        version_id,
        section_path,
    )


async def cited_chunk(conn, answer_id, claim_idx=0):
    return await conn.fetchval(
        "SELECT chunk_id FROM answer_citations WHERE answer_id = $1 AND claim_idx = $2",
        answer_id,
        claim_idx,
    )


async def drift_rows(conn):
    return await conn.fetch(
        "SELECT answer_id, tenant_id, claim_idx, old_version_id, new_version_id, verdict, detail "
        "FROM drift_events ORDER BY created_at, claim_idx"
    )


async def alert_payloads(conn) -> list[dict]:
    rows = await conn.fetch("SELECT payload FROM outbox WHERE topic = 'drift.alert' ORDER BY id")
    return [json.loads(r["payload"]) for r in rows]


async def watched_on_liver(conn, tenant, v1):
    liver = await chunk_of(conn, v1.version_id, "Liver")
    return await seed_watched_answer(conn, tenant, v1.version_id, [liver], [CLAIM])


async def test_unchanged_section_repoints_silently(engine, judge, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER, WARNINGS], day=1)
    answer = await watched_on_liver(fresh_conn, tenant, v1)
    v2 = await store(fresh_conn, source, [DOSAGE, LIVER, ("Warnings", "Avoid alcohol.")], day=2)

    verdicts = await engine.handle_version_created(await event_for(fresh_conn, v2))

    assert [(v.answer_id, v.claim_idx, v.verdict) for v in verdicts] == [(answer, 0, "still_valid")]
    assert verdicts[0].old_version_id == v1.version_id
    assert verdicts[0].new_version_id == v2.version_id
    new_liver = await chunk_of(fresh_conn, v2.version_id, "Liver")
    assert await cited_chunk(fresh_conn, answer) == new_liver
    body = json.loads(await fresh_conn.fetchval("SELECT body FROM answers WHERE id = $1", answer))
    assert body["claims"][0]["citations"][0]["chunk_id"] == str(new_liver)
    assert body["claims"][0]["citations"][0]["version_id"] == str(v2.version_id)
    # The stored body started without metadata (a pre-T11 body); the re-point writes
    # the new version's metadata, in the claim and in the top-level citation list.
    for cited in (body["claims"][0]["citations"][0], body["citations"][0]):
        assert cited["chunk_id"] == str(new_liver)
        assert cited["document_id"] == str(v2.document_id)
        assert (cited["title"], cited["external_id"]) == ("Lipitor label", "lipitor")
        assert (cited["version_no"], cited["section_path"]) == (2, "Liver")
        assert datetime.fromisoformat(cited["valid_from"]) == datetime(2024, 1, 2, tzinfo=UTC)
        assert cited["valid_to"] is None
    rows = await drift_rows(fresh_conn)
    assert [(r["verdict"], r["tenant_id"]) for r in rows] == [("still_valid", tenant)]
    assert await alert_payloads(fresh_conn) == []  # silent: no alert
    assert judge.calls == []  # an unchanged section never needs the judge


async def test_changed_section_still_supported_is_still_valid(engine, judge, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER], day=1)
    answer = await watched_on_liver(fresh_conn, tenant, v1)
    v2 = await store(
        fresh_conn,
        source,
        [DOSAGE, ("Liver", "Check ALT monthly during therapy. Also check AST at baseline.")],
        day=2,
    )

    verdicts = await engine.handle_version_created(await event_for(fresh_conn, v2))

    assert [v.verdict for v in verdicts] == ["still_valid"]
    assert judge.calls == ["judge-model"]
    body = json.loads(await fresh_conn.fetchval("SELECT body FROM answers WHERE id = $1", answer))
    cited = body["claims"][0]["citations"][0]
    assert (cited["version_id"], cited["version_no"]) == (str(v2.version_id), 2)
    assert (cited["title"], cited["section_path"]) == ("Lipitor label", "Liver")
    assert await cited_chunk(fresh_conn, answer) == await chunk_of(
        fresh_conn, v2.version_id, "Liver"
    )
    assert [r["verdict"] for r in await drift_rows(fresh_conn)] == ["still_valid"]
    assert await alert_payloads(fresh_conn) == []


async def test_changed_section_unsupported_is_changed_with_diff(engine, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER], day=1)
    answer = await watched_on_liver(fresh_conn, tenant, v1)
    old_liver = await cited_chunk(fresh_conn, answer)
    v2 = await store(
        fresh_conn, source, [DOSAGE, ("Liver", "Check ALT every three months.")], day=2
    )

    verdicts = await engine.handle_version_created(await event_for(fresh_conn, v2))

    assert [v.verdict for v in verdicts] == ["changed"]
    v = verdicts[0]
    assert v.before == "Check ALT monthly during therapy."
    assert v.after == "Check ALT every three months."
    assert "-Check ALT monthly during therapy." in v.diff
    assert "+Check ALT every three months." in v.diff
    assert await cited_chunk(fresh_conn, answer) == old_liver  # not re-pointed
    [row] = await drift_rows(fresh_conn)
    assert row["verdict"] == "changed" and row["old_version_id"] == v1.version_id
    detail = json.loads(row["detail"])
    assert detail["section_path"] == "Liver" and detail["diff"] == v.diff
    [payload] = await alert_payloads(fresh_conn)
    assert payload["tenant_id"] == str(tenant)
    alert = AlertEvent.model_validate(payload)
    assert alert.verdict == "changed" and alert.answer_id == answer
    assert alert.document_title == "Lipitor label"
    assert alert.new_version_id == v2.version_id and alert.old_version_id == v1.version_id
    assert alert.before == v.before and alert.after == v.after
    drift_id = await fresh_conn.fetchval("SELECT id FROM drift_events")
    assert alert.drift_event_id == drift_id


async def test_removed_section_is_broken_and_queued_for_review(engine, judge, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER], day=1)
    answer = await watched_on_liver(fresh_conn, tenant, v1)
    v2 = await store(fresh_conn, source, [DOSAGE], day=2)

    verdicts = await engine.handle_version_created(await event_for(fresh_conn, v2))

    assert [v.verdict for v in verdicts] == ["broken"]
    assert verdicts[0].before == "Check ALT monthly during therapy."
    assert verdicts[0].after is None
    assert judge.calls == []
    [item] = await fresh_conn.fetch(
        "SELECT kind, ref_id, tenant_id, status, payload FROM review_items"
    )
    assert item["kind"] == "broken_answer"
    assert (item["ref_id"], item["tenant_id"], item["status"]) == (answer, tenant, "open")
    assert json.loads(item["payload"])["reason"] == "broken"
    [payload] = await alert_payloads(fresh_conn)
    assert payload["verdict"] == "broken" and payload["after"] is None


async def test_unwatched_answers_are_ignored(engine, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER], day=1)
    answer = await watched_on_liver(fresh_conn, tenant, v1)
    await fresh_conn.execute("UPDATE answers SET watched = false WHERE id = $1", answer)
    old_liver = await cited_chunk(fresh_conn, answer)
    v2 = await store(fresh_conn, source, [DOSAGE], day=2)

    assert await engine.handle_version_created(await event_for(fresh_conn, v2)) == []

    assert await cited_chunk(fresh_conn, answer) == old_liver
    assert await drift_rows(fresh_conn) == []
    assert await alert_payloads(fresh_conn) == []
    assert await fresh_conn.fetchval("SELECT count(*) FROM review_items") == 0


async def test_redelivered_event_creates_one_drift_event(engine, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER], day=1)
    await watched_on_liver(fresh_conn, tenant, v1)
    v2 = await store(
        fresh_conn, source, [DOSAGE, ("Liver", "Check ALT every three months.")], day=2
    )
    event = await event_for(fresh_conn, v2)

    first = await engine.handle_version_created(event)
    second = await engine.handle_version_created(event)
    concurrent = await asyncio.gather(
        engine.handle_version_created(event), engine.handle_version_created(event)
    )

    assert [v.verdict for v in first] == ["changed"]
    assert second == [] and concurrent == [[], []]
    assert len(await drift_rows(fresh_conn)) == 1
    assert len(await alert_payloads(fresh_conn)) == 1


async def test_redelivered_event_racing_first_delivery_creates_one_drift_event(engine, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER], day=1)
    await watched_on_liver(fresh_conn, tenant, v1)
    v2 = await store(fresh_conn, source, [DOSAGE], day=2)
    event = await event_for(fresh_conn, v2)

    results = await asyncio.gather(*(engine.handle_version_created(event) for _ in range(3)))

    assert sorted(len(r) for r in results) == [0, 0, 1]
    assert len(await drift_rows(fresh_conn)) == 1
    assert len(await alert_payloads(fresh_conn)) == 1
    assert await fresh_conn.fetchval("SELECT count(*) FROM review_items") == 1


async def test_skipped_intermediate_version_evaluates_against_latest(engine, judge, fresh_conn):
    tenant, source = await seed_source(fresh_conn)
    v1 = await store(fresh_conn, source, [DOSAGE, LIVER], day=1)
    answer = await watched_on_liver(fresh_conn, tenant, v1)
    # v2 changes the cited section; v3 restores it (and changes another section).
    v2 = await store(fresh_conn, source, [DOSAGE, ("Liver", "Check ALT weekly.")], day=2)
    v3 = await store(fresh_conn, source, [("Dosage", "Take 20 mg once daily."), LIVER], day=3)

    late = await engine.handle_version_created(await event_for(fresh_conn, v2))
    latest = await engine.handle_version_created(await event_for(fresh_conn, v3))

    assert [(v.verdict, v.old_version_id, v.new_version_id) for v in late] == [
        ("still_valid", v1.version_id, v3.version_id)
    ]
    assert latest == []
    assert await cited_chunk(fresh_conn, answer) == await chunk_of(
        fresh_conn, v3.version_id, "Liver"
    )
    rows = await drift_rows(fresh_conn)
    assert [(r["new_version_id"], r["verdict"]) for r in rows] == [(v3.version_id, "still_valid")]
    assert judge.calls == []


async def test_other_tenants_answers_untouched(engine, fresh_conn):
    tenant_a, source_a = await seed_source(fresh_conn)
    tenant_b, source_b = await seed_source(fresh_conn)
    a1 = await store(fresh_conn, source_a, [DOSAGE, LIVER], day=1)
    b1 = await store(fresh_conn, source_b, [DOSAGE, LIVER], day=1)
    answer_a = await watched_on_liver(fresh_conn, tenant_a, a1)
    answer_b = await watched_on_liver(fresh_conn, tenant_b, b1)
    # A malformed cross-tenant citation: tenant B's answer citing tenant A's chunk.
    stray = await watched_on_liver(fresh_conn, tenant_b, a1)
    stray_chunk = await cited_chunk(fresh_conn, stray)
    b_chunk = await cited_chunk(fresh_conn, answer_b)
    a2 = await store(fresh_conn, source_a, [DOSAGE], day=2)

    verdicts = await engine.handle_version_created(await event_for(fresh_conn, a2))

    assert [(v.answer_id, v.verdict) for v in verdicts] == [(answer_a, "broken")]
    rows = await drift_rows(fresh_conn)
    assert [(r["answer_id"], r["tenant_id"]) for r in rows] == [(answer_a, tenant_a)]
    assert await cited_chunk(fresh_conn, stray) == stray_chunk
    assert await cited_chunk(fresh_conn, answer_b) == b_chunk
    assert [p["tenant_id"] for p in await alert_payloads(fresh_conn)] == [str(tenant_a)]
    refs = await fresh_conn.fetch("SELECT ref_id, tenant_id FROM review_items")
    assert [(r["ref_id"], r["tenant_id"]) for r in refs] == [(answer_a, tenant_a)]
