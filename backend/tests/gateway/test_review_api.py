"""GET /v1/review and POST /v1/review/{id}/resolve (P4 T5) through the real app, with real
Postgres and Redis: tenant scoping (404, never 403), 409 on a second or concurrent
resolve, 422 on an edit the item kind cannot take."""

import asyncio
import json
from contextlib import AsyncExitStack
from datetime import UTC, datetime

from agentkit import AgentKit
from dbseed import VersionSeed, embed_all, seed_history, seed_source, seed_watched_answer
from test_ask_api import asgi_client, settings_for

from driftline.agents.schemas import AGENT_STREAM
from driftline.drift.alerts import AlertLog
from driftline.ingest.outbox import OutboxRelay
from driftline.streams.bus import StreamBus


async def seed_items(conn, name: str):
    """A tenant with one pending relation and one broken watched answer under review.
    The tenant's API key is `key-<name>`."""
    tenant, source = await seed_source(conn, tenant=name, api_key=f"key-{name}")
    lipitor, _, _ = await seed_history(
        conn,
        source,
        external_id=f"{name}-label",
        title="Lipitor label",
        versions=[VersionSeed(datetime(2023, 1, 1, tzinfo=UTC), [("Liver", "Old rule.")])],
    )
    _, [guide_v], _ = await seed_history(
        conn,
        source,
        external_id=f"{name}-guide",
        title="Hepatic guide",
        versions=[VersionSeed(datetime(2024, 1, 1, tzinfo=UTC), [("Liver", "New rule.")])],
    )
    relation = await conn.fetchval(
        "INSERT INTO relations (src_version_id, dst_document_id, kind, confidence, status) "
        "VALUES ($1, $2, 'supersedes', 0.7, 'pending_review') RETURNING id",
        guide_v,
        lipitor,
    )
    rel_item = await conn.fetchval(
        "INSERT INTO review_items (kind, ref_id, tenant_id, payload) "
        "VALUES ('relation', $1, $2, '{\"reason\": \"low_confidence\"}') RETURNING id",
        relation,
        tenant,
    )
    answer = await conn.fetchval(
        "INSERT INTO answers (tenant_id, question, as_of, body, watched) "
        "VALUES ($1, 'How often?', now(), '{}', true) RETURNING id",
        tenant,
    )
    broken_item = await conn.fetchval(
        "INSERT INTO review_items (kind, ref_id, tenant_id, payload) "
        "VALUES ('broken_answer', $1, $2, '{\"reason\": \"broken\"}') RETURNING id",
        answer,
        tenant,
    )
    return {"tenant": tenant, "relation": relation, "rel_item": rel_item, "broken": broken_item}


def resolve_body(action="approve", edit=None, by="alice"):
    return {"action": action, "edit": edit, "by": by}


async def test_list_review_items_is_tenant_scoped_and_filters_by_kind(
    fresh_dsn, redis_url, fresh_conn
):
    a = await seed_items(fresh_conn, "pharma")
    await seed_items(fresh_conn, "infra")
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.get("/v1/review", params={"tenant": "pharma"})
        assert r.status_code == 200
        items = r.json()["items"]
        assert {i["id"] for i in items} == {str(a["rel_item"]), str(a["broken"])}
        assert all(i["status"] == "open" for i in items)

        r = await client.get("/v1/review", params={"tenant": "pharma", "kind": "relation"})
        [item] = r.json()["items"]
        assert item["id"] == str(a["rel_item"]) and item["ref_id"] == str(a["relation"])
        assert item["payload"] == {"reason": "low_confidence"}

        r = await client.get("/v1/review", params={"tenant": "pharma", "kind": "bogus"})
        assert r.status_code == 422
        r = await client.get("/v1/review", params={"tenant": "nobody"})
        assert r.status_code == 404


async def test_resolve_then_resolve_again_is_409(fresh_dsn, redis_url, fresh_conn):
    a = await seed_items(fresh_conn, "pharma")
    url = f"/v1/review/{a['rel_item']}/resolve"
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.post(url, params={"tenant": "pharma"}, json=resolve_body())
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "resolved" and body["resolved_by"] == "alice"
        assert body["resolution"]["action"] == "approve"
        again = await client.post(url, params={"tenant": "pharma"}, json=resolve_body("reject"))
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "already_resolved"
    assert await fresh_conn.fetchval("SELECT status FROM relations") == "applied"


async def test_concurrent_resolves_one_200_one_409(
    fresh_dsn, redis_url, fresh_conn, fresh_pool, redis_client
):
    a = await seed_items(fresh_conn, "pharma")
    url = f"/v1/review/{a['broken']}/resolve"
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        first, second = await asyncio.gather(
            client.post(url, params={"tenant": "pharma"}, json=resolve_body(by="a")),
            client.post(url, params={"tenant": "pharma"}, json=resolve_body(by="b")),
        )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    # The approved broken answer is regenerated exactly once (through the outbox).
    await OutboxRelay(
        fresh_pool, StreamBus(redis_client), alerts=AlertLog(redis_client)
    ).relay_once()
    entries = await redis_client.xrange(AGENT_STREAM)
    jobs = [json.loads(f["data"]) for _, f in entries]
    assert len(jobs) == 1 and jobs[0]["tenant_id"] == str(a["tenant"])


async def test_resolve_is_404_for_another_tenant_or_unknown_item(fresh_dsn, redis_url, fresh_conn):
    a = await seed_items(fresh_conn, "pharma")
    await seed_items(fresh_conn, "infra")
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.post(
            f"/v1/review/{a['rel_item']}/resolve", params={"tenant": "infra"}, json=resolve_body()
        )
        assert r.status_code == 404
        r = await client.post(
            f"/v1/review/{a['relation']}/resolve", params={"tenant": "pharma"}, json=resolve_body()
        )
        assert r.status_code == 404
        r = await client.post(
            f"/v1/review/{a['rel_item']}/resolve", params={"tenant": "nobody"}, json=resolve_body()
        )
        assert r.status_code == 404
    status = await fresh_conn.fetchval("SELECT status FROM relations WHERE id = $1", a["relation"])
    assert status == "pending_review"


async def test_invalid_resolution_is_422_and_leaves_the_item_open(fresh_dsn, redis_url, fresh_conn):
    a = await seed_items(fresh_conn, "pharma")
    url = f"/v1/review/{a['rel_item']}/resolve"
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.post(url, params={"tenant": "pharma"}, json=resolve_body("edit"))
        assert r.status_code == 422
        r = await client.post(
            url, params={"tenant": "pharma"}, json=resolve_body("edit", {"kind": "nope"})
        )
        assert r.status_code == 422
        r = await client.post(url, params={"tenant": "pharma"}, json=resolve_body("maybe"))
        assert r.status_code == 422
        r = await client.post(url, params={"tenant": "pharma"}, json=resolve_body(by=""))
        assert r.status_code == 422
    status = await fresh_conn.fetchval(
        "SELECT status FROM review_items WHERE id = $1", a["rel_item"]
    )
    assert status == "open"


async def test_review_routes_use_the_callers_api_key(fresh_dsn, redis_url, fresh_conn):
    a = await seed_items(fresh_conn, "pharma")
    await seed_items(fresh_conn, "infra")
    settings = settings_for(fresh_dsn, redis_url, auth_required=True)
    url = f"/v1/review/{a['rel_item']}/resolve"
    async with asgi_client(settings) as client:
        assert (await client.get("/v1/review", params={"tenant": "pharma"})).status_code == 401
        pharma = {"Authorization": "Bearer key-pharma"}
        infra = {"Authorization": "Bearer key-infra"}
        r = await client.get("/v1/review", headers=pharma)
        assert {i["id"] for i in r.json()["items"]} == {str(a["rel_item"]), str(a["broken"])}
        r = await client.get("/v1/review", params={"tenant": "pharma"}, headers=infra)
        assert r.status_code == 403
        assert (await client.post(url, headers=infra, json=resolve_body())).status_code == 404
        assert (await client.post(url, headers=pharma, json=resolve_body())).status_code == 200


async def test_an_edit_records_an_eval_case(fresh_dsn, redis_url, fresh_conn):
    a = await seed_items(fresh_conn, "pharma")
    async with asgi_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.post(
            f"/v1/review/{a['rel_item']}/resolve",
            params={"tenant": "pharma"},
            json=resolve_body("edit", {"kind": "amends"}),
        )
        assert r.status_code == 200
    case = await fresh_conn.fetchrow("SELECT tenant_id, source_review_id FROM eval_cases")
    assert (case["tenant_id"], case["source_review_id"]) == (a["tenant"], a["rel_item"])


async def test_a_regeneration_jobs_status_shows_the_regenerated_answer(
    fresh_dsn, redis_url, fresh_conn, fresh_pool, redis_client, embedder_url
):
    """Approve a broken watched answer, let the regeneration pause for review, approve
    that too: GET /v1/jobs/{regeneration job} then shows the regenerated answer."""
    tenant, source = await seed_source(fresh_conn, tenant="pharma", api_key="key-pharma")
    _, versions, chunks = await seed_history(
        fresh_conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[
            VersionSeed(datetime(2023, 1, 1, tzinfo=UTC), [("Liver", "Check ALT yearly.")]),
            VersionSeed(datetime(2024, 4, 15, tzinfo=UTC), [("Hepatic", "Check ALT monthly.")]),
        ],
    )
    await embed_all(fresh_conn, embedder_url)
    answer = await seed_watched_answer(
        fresh_conn,
        tenant,
        versions[0],
        [chunks[0][0]],
        [("Check ALT yearly.", "Check ALT yearly.")],
        question="How often should ALT be checked?",
    )
    broken = await fresh_conn.fetchval(
        "INSERT INTO review_items (kind, ref_id, tenant_id, payload) "
        "VALUES ('broken_answer', $1, $2, '{}') RETURNING id",
        answer,
        tenant,
    )
    async with (
        AsyncExitStack() as stack,
        asgi_client(settings_for(fresh_dsn, redis_url)) as client,
    ):
        kit = AgentKit(fresh_pool, redis_client, fresh_dsn, embedder_url, stack)
        await kit.restart()
        r = await client.post(
            f"/v1/review/{broken}/resolve", params={"tenant": "pharma"}, json=resolve_body()
        )
        assert r.status_code == 200
        regen_job = r.json()["resolution"]["job_id"]
        await kit.drain()  # relays the regeneration, which pauses for review
        paused = await fresh_conn.fetchval(
            "SELECT id FROM review_items WHERE kind = 'low_confidence_answer'"
        )
        r = await client.post(
            f"/v1/review/{paused}/resolve", params={"tenant": "pharma"}, json=resolve_body()
        )
        assert r.status_code == 200
        await kit.drain()

        r = await client.get(f"/v1/jobs/{regen_job}", params={"tenant": "pharma"})
    assert r.status_code == 200
    status = r.json()
    assert status["status"] == "succeeded"
    assert status["answer"] is not None
    assert status["answer"]["answer_id"] == str(answer)
    assert status["answer"]["answer"] == "Check ALT monthly."
