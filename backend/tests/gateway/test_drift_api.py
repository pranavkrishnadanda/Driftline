"""Watch / alerts / drift-events / timeline API (P4 T4), against a real server, Redis and
Postgres. The alert stream reuses the ask SSE machinery, so it is held to the same rules:
Last-Event-ID replay, heartbeats, the stream-slot limit, and per-tenant isolation."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dbseed import VersionSeed, seed_history, seed_source, seed_watched_answer
from livesrv import serve
from test_ask_api import READ_TIMEOUT_S, FrameReader, asgi_client, frames, get, settings_for

from driftline.agents.events import ALERT_EVENT_ADAPTER, AlertEvent
from driftline.drift.alerts import AlertLog
from driftline.gateway.app import create_app
from driftline.gateway.contract import ALERT_CONTRACT_PATH, build_alert_contract
from driftline.ingest.outbox import OutboxRelay
from driftline.streams.bus import StreamBus

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def make_alert(title: str = "Runbook", verdict: str = "changed") -> AlertEvent:
    return AlertEvent(
        drift_event_id=uuid4(),
        answer_id=uuid4(),
        verdict=verdict,
        document_title=title,
        old_version_id=uuid4(),
        new_version_id=uuid4(),
        before="old text",
        after="new text",
        t=datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
    )


async def seed_tenant(conn, name: str):
    """A tenant with one document (two versions) and a watched answer citing v1."""
    tenant_id, source_id = await seed_source(conn, tenant=name)
    document_id, version_ids, chunk_ids = await seed_history(
        conn,
        source_id,
        external_id=f"{name}-doc",
        title=f"{name} runbook",
        versions=[
            VersionSeed(valid_from=T0, texts=[("Dosing", "Check ALT monthly.")]),
            VersionSeed(valid_from=T0 + timedelta(days=30), texts=[("Dosing", "Check ALT.")]),
        ],
    )
    answer_id = await seed_watched_answer(
        conn,
        tenant_id,
        version_ids[0],
        [chunk_ids[0][0]],
        [("ALT is checked monthly.", "Check ALT monthly.")],
    )
    return tenant_id, document_id, version_ids, answer_id


async def watched(conn, answer_id: UUID):
    return await conn.fetchrow("SELECT watched, watched_at FROM answers WHERE id = $1", answer_id)


# --- watch / unwatch -------------------------------------------------------------------


async def test_watch_and_unwatch_an_answer(fresh_dsn, redis_url, fresh_conn):
    _, _, _, answer_id = await seed_tenant(fresh_conn, "pharma")
    await fresh_conn.execute(
        "UPDATE answers SET watched = false, watched_at = NULL WHERE id = $1", answer_id
    )
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.post(f"/v1/answers/{answer_id}/watch", params={"tenant": "pharma"})
        assert r.status_code == 200
        assert r.json() == {"answer_id": str(answer_id), "watched": True}
        first = await watched(fresh_conn, answer_id)
        assert first["watched"] is True and first["watched_at"] is not None
        # Watching again is idempotent: the original watch time is kept.
        again = await client.post(f"/v1/answers/{answer_id}/watch", params={"tenant": "pharma"})
        assert again.status_code == 200
        assert (await watched(fresh_conn, answer_id))["watched_at"] == first["watched_at"]

        r = await client.delete(f"/v1/answers/{answer_id}/watch", params={"tenant": "pharma"})
        assert r.status_code == 200
        assert r.json() == {"answer_id": str(answer_id), "watched": False}
    row = await watched(fresh_conn, answer_id)
    assert row["watched"] is False and row["watched_at"] is None


async def test_watch_is_404_across_tenants_and_for_unknown_answers(
    fresh_dsn, redis_url, fresh_conn
):
    _, _, _, answer_a = await seed_tenant(fresh_conn, "tenant-a")
    await seed_tenant(fresh_conn, "tenant-b")
    await fresh_conn.execute("UPDATE answers SET watched = false WHERE id = $1", answer_a)
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        for method in ("POST", "DELETE"):
            other = await client.request(
                method, f"/v1/answers/{answer_a}/watch", params={"tenant": "tenant-b"}
            )
            assert other.status_code == 404
            assert other.json()["detail"] == {"code": "unknown_answer"}
            missing = await client.request(
                method, f"/v1/answers/{uuid4()}/watch", params={"tenant": "tenant-a"}
            )
            assert missing.status_code == 404
            nobody = await client.request(
                method, f"/v1/answers/{answer_a}/watch", params={"tenant": "nobody"}
            )
            assert nobody.status_code == 404
            assert nobody.json()["detail"] == {"code": "unknown_tenant"}
    assert (await watched(fresh_conn, answer_a))["watched"] is False  # tenant B changed nothing


# --- alert stream ----------------------------------------------------------------------


async def test_alert_published_after_connecting_arrives_live(
    fresh_dsn, fresh_pool, redis_url, redis_client, fresh_conn
):
    tenant_id, *_ = await seed_tenant(fresh_conn, "pharma")
    alert = make_alert()
    app = create_app(settings_for(fresh_dsn, redis_url, sse_heartbeat_s=0.1))
    async with (
        serve(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10) as client,
        client.stream("GET", "/v1/alerts/stream", params={"tenant": "pharma"}) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        reader = FrameReader(r)
        pings = await reader.until(lambda fs: len(fs) >= 1)
        assert pings == [{"comment": "ping"}]  # connected and idle
        # The real path: a drift.alert outbox row, relayed to the tenant's alert log.
        await fresh_conn.execute(
            "INSERT INTO outbox (topic, payload) VALUES ('drift.alert', $1::jsonb)",
            json.dumps({**alert.model_dump(mode="json"), "tenant_id": str(tenant_id)}),
        )
        await OutboxRelay(fresh_pool, StreamBus(redis_client)).relay_once()
        got = await reader.until(lambda fs: any(f.get("event") == "alert" for f in fs))
    [frame] = [f for f in got if "event" in f]
    assert frame["id"] == 1
    assert ALERT_EVENT_ADAPTER.validate_python(frame["data"]) == alert


async def test_reconnect_with_last_event_id_replays_only_missed_alerts(
    fresh_dsn, redis_url, redis_client, fresh_conn
):
    tenant_id, *_ = await seed_tenant(fresh_conn, "pharma")
    log = AlertLog(redis_client)
    sent = [make_alert(title=f"doc {n}") for n in range(5)]
    for alert in sent[:3]:
        await log.append(tenant_id, alert)
    app = create_app(settings_for(fresh_dsn, redis_url, sse_heartbeat_s=0.1))
    url = "/v1/alerts/stream?tenant=pharma"
    async with serve(app) as base, httpx.AsyncClient(base_url=base, timeout=10) as client:
        async with client.stream("GET", url) as r:
            first = await FrameReader(r).until(lambda fs: sum("id" in f for f in fs) == 2)
        # The client dropped after id 2; alerts kept coming meanwhile.
        await log.append(tenant_id, sent[3])
        async with client.stream("GET", url, headers={"Last-Event-ID": "2"}) as r:
            reader = FrameReader(r)
            replayed = await reader.until(lambda fs: sum("id" in f for f in fs) == 2)
            await log.append(tenant_id, sent[4])  # then live ones follow
            live = await reader.until(lambda fs: any("id" in f for f in fs))
        async with client.stream("GET", url + "&last_event_id=4") as r:
            by_query = await FrameReader(r).until(lambda fs: any("id" in f for f in fs))
    assert [f["id"] for f in first if "id" in f] == [1, 2]
    assert [f["id"] for f in replayed if "id" in f] == [3, 4]
    assert [f["data"]["document_title"] for f in replayed if "id" in f] == ["doc 2", "doc 3"]
    assert [f["id"] for f in live if "id" in f] == [5]
    assert [f["id"] for f in by_query if "id" in f] == [5]


async def test_tenant_b_client_never_sees_tenant_a_alerts(
    fresh_dsn, redis_url, redis_client, fresh_conn
):
    tenant_a, *_ = await seed_tenant(fresh_conn, "tenant-a")
    tenant_b, *_ = await seed_tenant(fresh_conn, "tenant-b")
    log = AlertLog(redis_client)
    await log.append(tenant_a, make_alert(title="A before"))
    app = create_app(settings_for(fresh_dsn, redis_url, sse_heartbeat_s=0.1))
    async with (
        serve(app) as base,
        httpx.AsyncClient(base_url=base, timeout=10) as client,
        client.stream("GET", "/v1/alerts/stream?tenant=tenant-b") as rb,
        client.stream("GET", "/v1/alerts/stream?tenant=tenant-a") as ra,
    ):
        b, a = FrameReader(rb), FrameReader(ra)
        await a.until(lambda fs: any("id" in f for f in fs))  # A's replay is on A's stream
        await log.append(tenant_a, make_alert(title="A live"))
        await a.until(lambda fs: any("id" in f for f in fs))
        await log.append(tenant_b, make_alert(title="B live"))
        seen_by_b = await b.until(lambda fs: any("id" in f for f in fs))
    titles = [f["data"]["document_title"] for f in seen_by_b if "id" in f]
    assert titles == ["B live"]
    assert all("event" not in f or f["event"] == "alert" for f in seen_by_b)


async def test_alert_stream_limit_is_shared_with_ask_streams_and_unknown_tenant_404(
    fresh_dsn, redis_url, fresh_conn
):
    await seed_tenant(fresh_conn, "pharma")
    app = create_app(settings_for(fresh_dsn, redis_url, sse_max_connections=1, sse_heartbeat_s=0.1))
    url = "/v1/alerts/stream?tenant=pharma"
    async with serve(app) as base, httpx.AsyncClient(base_url=base, timeout=10) as client:
        assert (await get(client, "/v1/alerts/stream?tenant=nobody")).status_code == 404
        assert (await get(client, "/v1/alerts/stream")).status_code == 422
        async with client.stream("GET", url) as r:
            reader = FrameReader(r)
            await reader.until(lambda fs: len(fs) >= 1)
            second = await get(client, url)
            assert second.status_code == 503 and second.headers["retry-after"] == "5"
            assert second.json()["detail"] == {"code": "too_many_streams"}
        deadline = asyncio.get_running_loop().time() + READ_TIMEOUT_S
        while True:  # the server notices the disconnect and frees the slot
            async with client.stream("GET", url) as r:
                if r.status_code == 200:
                    break
            assert asyncio.get_running_loop().time() < deadline, "slot never released"
            await asyncio.sleep(0.05)


async def test_alert_client_too_far_behind_gets_events_expired(
    fresh_dsn, redis_url, redis_client, fresh_conn
):
    tenant_id, *_ = await seed_tenant(fresh_conn, "pharma")
    log = AlertLog(redis_client, maxlen=2)
    for n in range(5):
        await log.append(tenant_id, make_alert(title=str(n)))
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await get(client, "/v1/alerts/stream?tenant=pharma", headers={"Last-Event-ID": "1"})
    [frame] = frames(r.text)
    assert frame["event"] == "error" and "id" not in frame
    assert frame["data"]["code"] == "events_expired" and frame["data"]["retryable"] is False
    assert "/v1/drift/events" in frame["data"]["message"]


# --- drift events ----------------------------------------------------------------------


async def add_drift_event(conn, tenant_id, answer_id, old_v, new_v, verdict, at, claim_idx=0):
    return await conn.fetchval(
        "INSERT INTO drift_events (answer_id, tenant_id, claim_idx, old_version_id, "
        "new_version_id, verdict, detail, created_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8) RETURNING id",
        answer_id,
        tenant_id,
        claim_idx,
        old_v,
        new_v,
        verdict,
        json.dumps({"section_path": "Dosing", "before": "b", "after": "a", "diff": "-b\n+a"}),
        at,
    )


async def test_drift_events_are_latest_first_limited_and_tenant_scoped(
    fresh_dsn, redis_url, fresh_conn
):
    tenant_a, doc_a, (v1, v2), answer_a = await seed_tenant(fresh_conn, "tenant-a")
    tenant_b, _, (w1, w2), answer_b = await seed_tenant(fresh_conn, "tenant-b")
    ids = [
        await add_drift_event(
            fresh_conn, tenant_a, answer_a, v1, v2, verdict, T0 + timedelta(hours=n), claim_idx=n
        )
        for n, verdict in enumerate(["still_valid", "changed", "broken"])
    ]
    await add_drift_event(fresh_conn, tenant_b, answer_b, w1, w2, "broken", T0)
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.get("/v1/drift/events", params={"tenant": "tenant-a"})
        limited = await client.get("/v1/drift/events", params={"tenant": "tenant-a", "limit": 2})
        assert (await client.get("/v1/drift/events?tenant=nobody")).status_code == 404
        assert (await client.get("/v1/drift/events?tenant=tenant-a&limit=0")).status_code == 422
    assert r.status_code == 200
    events = r.json()["events"]
    assert [e["id"] for e in events] == [str(i) for i in reversed(ids)]
    latest = events[0]
    assert latest["verdict"] == "broken" and latest["claim_idx"] == 2
    assert latest["answer_id"] == str(answer_a)
    assert (latest["old_version_id"], latest["new_version_id"]) == (str(v1), str(v2))
    assert (latest["document_id"], latest["document_title"]) == (str(doc_a), "tenant-a runbook")
    assert latest["section_path"] == "Dosing" and latest["diff"] == "-b\n+a"
    assert (latest["before"], latest["after"]) == ("b", "a")
    assert [e["id"] for e in limited.json()["events"]] == [str(ids[2]), str(ids[1])]


# --- document timeline -----------------------------------------------------------------


async def test_timeline_lists_versions_in_order_with_contiguous_windows_and_relations(
    fresh_dsn, redis_url, fresh_conn
):
    _, source_id = await seed_source(fresh_conn, tenant="pharma")
    days = [T0 + timedelta(days=30 * n) for n in range(3)]
    document_id, version_ids, _ = await seed_history(
        fresh_conn,
        source_id,
        external_id="label-1",
        title="Label 1",
        versions=[
            VersionSeed(valid_from=d, texts=[("A", f"text {n}")]) for n, d in enumerate(days)
        ],
    )
    diff = {"added": [], "removed": [], "changed": ["A"]}
    await fresh_conn.execute(
        "UPDATE doc_versions SET diff_from_prev = $2::jsonb WHERE id = $1",
        version_ids[2],
        json.dumps(diff),
    )
    old_doc, _, _ = await seed_history(
        fresh_conn,
        source_id,
        external_id="old-label",
        title="Old label",
        versions=[VersionSeed(valid_from=T0, texts=[("A", "old")])],
    )
    newer_doc, (newer_v,), _ = await seed_history(
        fresh_conn,
        source_id,
        external_id="new-label",
        title="New label",
        versions=[VersionSeed(valid_from=T0, texts=[("A", "new")])],
    )
    out_id = await fresh_conn.fetchval(
        "INSERT INTO relations (src_version_id, dst_document_id, kind, confidence) "
        "VALUES ($1, $2, 'supersedes', 0.9) RETURNING id",
        version_ids[1],
        old_doc,
    )
    in_id = await fresh_conn.fetchval(
        "INSERT INTO relations (src_version_id, dst_document_id, kind, confidence, status) "
        "VALUES ($1, $2, 'amends', 0.5, 'pending_review') RETURNING id",
        newer_v,
        document_id,
    )
    other_tenant, *_ = await seed_tenant(fresh_conn, "other")
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.get(f"/v1/documents/{document_id}/timeline", params={"tenant": "pharma"})
        hidden = await client.get(
            f"/v1/documents/{document_id}/timeline", params={"tenant": "other"}
        )
        missing = await client.get(f"/v1/documents/{uuid4()}/timeline", params={"tenant": "pharma"})
    assert hidden.status_code == 404 and missing.status_code == 404
    assert hidden.json()["detail"] == {"code": "unknown_document"}
    assert r.status_code == 200
    body = r.json()
    assert (body["document_id"], body["title"], body["external_id"]) == (
        str(document_id),
        "Label 1",
        "label-1",
    )
    versions = body["versions"]
    assert [v["version_id"] for v in versions] == [str(v) for v in version_ids]
    assert [v["version_no"] for v in versions] == [1, 2, 3]
    for prev, nxt in pairwise(versions):
        assert prev["valid_to"] == nxt["valid_from"]  # contiguous windows
    assert versions[-1]["valid_to"] is None
    assert datetime.fromisoformat(versions[0]["valid_from"]) == days[0]
    assert versions[0]["diff_from_prev"] is None and versions[2]["diff_from_prev"] == diff
    [out] = body["relations"]["outgoing"]
    assert out["id"] == str(out_id) and out["kind"] == "supersedes"
    assert (out["src_version_id"], out["document_id"], out["document_title"]) == (
        str(version_ids[1]),
        str(old_doc),
        "Old label",
    )
    [inc] = body["relations"]["incoming"]
    assert inc["id"] == str(in_id) and inc["status"] == "pending_review"
    assert (inc["src_version_id"], inc["document_id"], inc["document_title"]) == (
        str(newer_v),
        str(newer_doc),
        "New label",
    )
    assert other_tenant  # the other tenant exists, it just cannot see this document


# --- contract --------------------------------------------------------------------------


def test_committed_alert_contract_fixture_matches_the_code():
    assert (
        ALERT_CONTRACT_PATH
        == Path(__file__).resolve().parents[3] / "contracts" / "sse" / "alert-events.v1.json"
    )
    committed = json.loads(ALERT_CONTRACT_PATH.read_text())
    assert committed == json.loads(json.dumps(build_alert_contract()))  # regenerate: --write
    ids = [e["id"] for e in committed["examples"] if e["id"] is not None]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for example in committed["examples"]:
        assert ALERT_EVENT_ADAPTER.validate_python(example["data"]).type == example["event"]


async def test_openapi_documents_the_alert_stream(fresh_dsn, redis_url):
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        spec = (await get(client, "/openapi.json")).json()
    content = spec["paths"]["/v1/alerts/stream"]["get"]["responses"]["200"]["content"]
    assert content["text/event-stream"]["schema"] == {"$ref": "#/components/schemas/AlertEvents"}
    schemas = spec["components"]["schemas"]
    assert {"AlertEvents", "AlertEvent", "ErrorEvent", "AskEvent"} <= set(schemas)
    assert schemas["AlertEvents"]["discriminator"]["propertyName"] == "type"
    assert {
        "/v1/answers/{answer_id}/watch",
        "/v1/drift/events",
        "/v1/documents/{document_id}/timeline",
    } <= set(spec["paths"])
