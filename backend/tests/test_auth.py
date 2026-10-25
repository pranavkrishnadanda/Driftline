"""Tenant API-key auth (P6 T0), against a real server, Postgres and Redis.

Dev mode (`auth_required=False`, the default) keeps the `tenant` name working; a bearer
key, when sent, must be valid and must match the named tenant. With `auth_required=True`
the bearer key is mandatory. A wrong or missing key is 401, a key for another tenant than
the named one is 403, and another tenant's resource is 404 (ids never leak).
"""

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
import httpx
import pytest
from dbseed import VersionSeed, seed_history, seed_source, seed_tenant, seed_watched_answer
from livesrv import serve

from driftline.agents.schemas import AnswerSchema
from driftline.auth import TenantRow, Unauthorized, hash_api_key, resolve_tenant
from driftline.config import Settings
from driftline.gateway.app import create_app

KEY_A = "key-for-tenant-a"
KEY_B = "key-for-tenant-b"
READ_TIMEOUT_S = 10.0
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def settings_for(fresh_dsn, redis_url, **overrides) -> Settings:
    values = {"database_url": fresh_dsn, "redis_url": redis_url, "sse_heartbeat_s": 0.2}
    return Settings(_env_file=None, **(values | overrides))


@asynccontextmanager
async def live_client(settings: Settings):
    """A real uvicorn server on a socket, so SSE responses stream for real."""
    async with (
        serve(create_app(settings)) as base,
        httpx.AsyncClient(base_url=base, timeout=READ_TIMEOUT_S) as client,
    ):
        yield client


@pytest.fixture(autouse=True)
async def _empty_redis(redis_client):
    """Each test starts with an empty Redis, so earlier asks add no backlog."""
    yield


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def status_of(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> int:
    """Status of a request without reading the body (an SSE body never ends)."""
    async with client.stream(method, url, **kwargs) as r:
        return r.status_code


async def seed_world(conn: asyncpg.Connection) -> dict:
    """Tenants a and b, each with a key, a document, a watched answer and an ask job."""
    world: dict = {}
    for name, key in (("tenant-a", KEY_A), ("tenant-b", KEY_B)):
        tenant_id = await seed_tenant(conn, name, api_key=key)
        source_id = await conn.fetchval(
            "INSERT INTO sources (tenant_id, kind, config) VALUES ($1, 'upload', '{}') "
            "RETURNING id",
            tenant_id,
        )
        document_id, version_ids, chunk_ids = await seed_history(
            conn,
            source_id,
            external_id=f"{name}-doc",
            title=f"{name} runbook",
            versions=[VersionSeed(valid_from=T0, texts=[("Dosing", "Check ALT monthly.")])],
        )
        answer_id = await seed_watched_answer(
            conn,
            tenant_id,
            version_ids[0],
            [chunk_ids[0][0]],
            [("ALT is checked monthly.", "Check ALT monthly.")],
        )
        job_id = await conn.fetchval(
            "INSERT INTO jobs (tenant_id, kind, status) VALUES ($1, 'ask', 'succeeded') "
            "RETURNING id",
            tenant_id,
        )
        world[name] = {
            "tenant_id": tenant_id,
            "document_id": document_id,
            "answer_id": answer_id,
            "job_id": job_id,
        }
    return world


def scoped_routes(world: dict, name: str) -> list[tuple[str, str, dict]]:
    """Every tenant-scoped route, addressed at tenant `name`'s own resources."""
    w = world[name]
    return [
        ("POST", "/v1/ask", {"json": {"question": "How often is ALT checked?"}}),
        ("GET", f"/v1/jobs/{w['job_id']}", {}),
        ("GET", f"/v1/jobs/{w['job_id']}/events", {}),
        ("GET", f"/v1/ask/{w['job_id']}/events", {}),
        ("POST", f"/v1/answers/{w['answer_id']}/watch", {}),
        ("DELETE", f"/v1/answers/{w['answer_id']}/watch", {}),
        ("GET", "/v1/alerts/stream", {}),
        ("GET", "/v1/drift/events", {}),
        ("GET", f"/v1/documents/{w['document_id']}/timeline", {}),
    ]


# --- driftline.auth -------------------------------------------------------------------


def test_hash_api_key_is_sha256_hex():
    assert hash_api_key("abc") == hashlib.sha256(b"abc").hexdigest()
    assert len(hash_api_key("k")) == 64


async def test_seed_tenant_stores_the_hash_of_its_key(fresh_conn):
    tenant_id = await seed_tenant(fresh_conn, "pharma")
    stored = await fresh_conn.fetchval("SELECT api_key_hash FROM tenants WHERE id = $1", tenant_id)
    assert stored == hash_api_key("test-key")


async def test_resolve_tenant_accepts_the_right_key_and_rejects_others(fresh_dsn, fresh_conn):
    tenant_id = await seed_tenant(fresh_conn, "pharma", api_key=KEY_A)
    # Tenants without a usable key (seeded with a non-hash placeholder) never match.
    await seed_source(fresh_conn, tenant="legacy")
    pool = await asyncpg.create_pool(fresh_dsn, min_size=1, max_size=2)
    try:
        assert await resolve_tenant(pool, KEY_A) == TenantRow(id=tenant_id, name="pharma")
        for bad in ("wrong-key", "", None, "x", hash_api_key(KEY_A)):
            with pytest.raises(Unauthorized):
                await resolve_tenant(pool, bad)
    finally:
        await pool.close()


# --- dev mode (auth_required=False) ---------------------------------------------------


async def test_dev_mode_keeps_tenant_names_working(fresh_dsn, redis_url, fresh_conn):
    world = await seed_world(fresh_conn)
    async with live_client(settings_for(fresh_dsn, redis_url)) as client:
        for method, url, kw in scoped_routes(world, "tenant-a"):
            if method == "POST" and url == "/v1/ask":
                kw = {"json": {**kw["json"], "tenant": "tenant-a"}}
            else:
                kw = {"params": {"tenant": "tenant-a"}}
            assert await status_of(client, method, url, **kw) in (200, 202), (method, url)


async def test_dev_mode_accepts_a_bearer_key_without_a_tenant_name(
    fresh_dsn, redis_url, fresh_conn
):
    world = await seed_world(fresh_conn)
    async with live_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.post(
            "/v1/ask", json={"question": "How often is ALT checked?"}, headers=bearer(KEY_A)
        )
        assert r.status_code == 202
        job = await fresh_conn.fetchrow(
            "SELECT tenant_id FROM jobs WHERE id = $1", UUID(r.json()["job_id"])
        )
        assert job["tenant_id"] == world["tenant-a"]["tenant_id"]
        r = await client.get("/v1/drift/events", headers=bearer(KEY_A))
        assert r.status_code == 200 and len(r.json()["events"]) == 0


async def test_dev_mode_rejects_a_wrong_key_even_with_a_valid_tenant_name(
    fresh_dsn, redis_url, fresh_conn
):
    world = await seed_world(fresh_conn)
    async with live_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.get(
            "/v1/drift/events", params={"tenant": "tenant-a"}, headers=bearer("wrong")
        )
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == "Bearer"
        assert r.json()["detail"] == {"code": "unauthorized"}
        # A malformed Authorization header is not silently ignored either.
        basic = {"Authorization": "Basic dXNlcjpwYXNz"}
        r = await client.get("/v1/drift/events", params={"tenant": "tenant-a"}, headers=basic)
        assert r.status_code == 401
        job = world["tenant-a"]["job_id"]
        assert await status_of(client, "GET", f"/v1/jobs/{job}", headers=bearer("wrong")) == 401


async def test_a_key_for_another_tenant_than_the_named_one_is_403(fresh_dsn, redis_url, fresh_conn):
    world = await seed_world(fresh_conn)
    for auth_required in (False, True):
        settings = settings_for(fresh_dsn, redis_url, auth_required=auth_required)
        async with live_client(settings) as client:
            r = await client.get(
                "/v1/drift/events", params={"tenant": "tenant-b"}, headers=bearer(KEY_A)
            )
            assert r.status_code == 403
            assert r.json()["detail"] == {"code": "tenant_mismatch"}
            r = await client.post(
                "/v1/ask", json={"question": "q", "tenant": "tenant-b"}, headers=bearer(KEY_A)
            )
            assert r.status_code == 403
            url = f"/v1/documents/{world['tenant-b']['document_id']}/timeline"
            assert (
                await status_of(
                    client, "GET", url, params={"tenant": "tenant-b"}, headers=bearer(KEY_A)
                )
                == 403
            )
    assert await fresh_conn.fetchval("SELECT count(*) FROM jobs") == 2  # no ask was queued


async def test_dev_mode_without_any_identification_is_401(fresh_dsn, redis_url, fresh_conn):
    await seed_world(fresh_conn)
    async with live_client(settings_for(fresh_dsn, redis_url)) as client:
        assert await status_of(client, "GET", "/v1/alerts/stream") == 401
        assert (await client.get("/v1/drift/events")).status_code == 401
        assert (await client.post("/v1/ask", json={"question": "q"})).status_code == 401


# --- auth_required=True ---------------------------------------------------------------


async def test_auth_required_makes_the_bearer_key_mandatory_on_every_scoped_route(
    fresh_dsn, redis_url, fresh_conn
):
    world = await seed_world(fresh_conn)
    settings = settings_for(fresh_dsn, redis_url, auth_required=True)
    async with live_client(settings) as client:
        for method, url, kw in scoped_routes(world, "tenant-a"):
            named = (
                {"json": {**kw["json"], "tenant": "tenant-a"}}
                if "json" in kw
                else {"params": {"tenant": "tenant-a"}}
            )
            # A tenant name alone is no longer enough, and a wrong key never is.
            assert await status_of(client, method, url, **named) == 401, (method, url)
            missing = await status_of(client, method, url, **kw, headers=bearer("nope"))
            assert missing == 401, (method, url)
            # The right key works, with or without the (matching) tenant name.
            ok = await status_of(client, method, url, **kw, headers=bearer(KEY_A))
            assert ok in (200, 202), (method, url, ok)
            ok = await status_of(client, method, url, **named, headers=bearer(KEY_A))
            assert ok in (200, 202), (method, url, ok)
        # Health checks stay open.
        assert (await client.get("/healthz")).status_code == 200


async def test_api_keys_in_the_query_string_are_not_accepted(fresh_dsn, redis_url, fresh_conn):
    await seed_world(fresh_conn)
    settings = settings_for(fresh_dsn, redis_url, auth_required=True)
    async with live_client(settings) as client:
        for param in ("api_key", "key", "token", "access_token", "authorization"):
            r = await client.get("/v1/drift/events", params={param: KEY_A})
            assert r.status_code == 401, param


async def test_one_tenants_key_never_reads_another_tenants_resources(
    fresh_dsn, redis_url, fresh_conn
):
    world = await seed_world(fresh_conn)
    for auth_required in (False, True):
        settings = settings_for(fresh_dsn, redis_url, auth_required=auth_required)
        async with live_client(settings) as client:
            # Tenant a's key addressing tenant b's ids: unknown (404), never forbidden.
            for method, url, kw in scoped_routes(world, "tenant-b"):
                if url in ("/v1/ask", "/v1/alerts/stream", "/v1/drift/events"):
                    continue  # not addressed by id
                status = await status_of(client, method, url, **kw, headers=bearer(KEY_A))
                assert status == 404, (auth_required, method, url, status)
    assert await fresh_conn.fetchval(
        "SELECT watched FROM answers WHERE id = $1", world["tenant-b"]["answer_id"]
    )


async def test_job_status_is_scoped_to_the_named_tenant_in_dev_mode(
    fresh_dsn, redis_url, fresh_conn
):
    world = await seed_world(fresh_conn)
    job_b = world["tenant-b"]["job_id"]
    async with live_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.get(f"/v1/jobs/{job_b}", params={"tenant": "tenant-a"})
        assert r.status_code == 404 and r.json()["detail"] == {"code": "unknown_job"}
        url = f"/v1/jobs/{job_b}/events"
        assert await status_of(client, "GET", url, params={"tenant": "tenant-a"}) == 404
        assert (
            await client.get(f"/v1/jobs/{job_b}", params={"tenant": "tenant-b"})
        ).status_code == 200


async def test_alert_stream_accepts_the_key_in_the_authorization_header(
    fresh_dsn, redis_url, fresh_conn
):
    """The frontend reads SSE with fetch, so a header works for streams too."""
    await seed_world(fresh_conn)
    settings = settings_for(fresh_dsn, redis_url, auth_required=True, sse_heartbeat_s=0.1)
    async with (
        live_client(settings) as client,
        client.stream("GET", "/v1/alerts/stream", headers=bearer(KEY_A)) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        first = await asyncio.wait_for(anext(r.aiter_text()), READ_TIMEOUT_S)
        assert first.startswith(":")  # a heartbeat comment


async def test_job_cost_counts_only_the_callers_tenant(fresh_dsn, redis_url, fresh_conn):
    world = await seed_world(fresh_conn)
    a, b = world["tenant-a"], world["tenant-b"]
    answer = AnswerSchema(status="answered", answer="Check ALT.", as_of=T0, confidence=1.0)
    await fresh_conn.execute(
        "INSERT INTO answers (tenant_id, question, as_of, body, job_id) "
        "VALUES ($1, 'q', now(), $2::jsonb, $3)",
        a["tenant_id"],
        answer.model_dump_json(),
        a["job_id"],
    )
    insert_call = (
        "INSERT INTO llm_calls (job_id, tenant_id, node, tier, provider, model, input_tokens, "
        "output_tokens, cost_usd, latency_ms) VALUES ($1, $2, 'draft', 'answer', 'anthropic', "
        "'claude-sonnet-5-5', 10, 5, $3, 9)"
    )
    await fresh_conn.execute(insert_call, a["job_id"], a["tenant_id"], 0.25)
    # A call recorded against a's job id but for tenant b must not be billed to a.
    await fresh_conn.execute(insert_call, a["job_id"], b["tenant_id"], 100.0)
    async with live_client(settings_for(fresh_dsn, redis_url, auth_required=True)) as client:
        r = await client.get(f"/v1/jobs/{a['job_id']}", headers=bearer(KEY_A))
    assert r.status_code == 200
    assert r.json()["cost_usd"] == pytest.approx(0.25)


async def test_openapi_declares_the_bearer_scheme(fresh_dsn, redis_url):
    async with live_client(settings_for(fresh_dsn, redis_url)) as client:
        doc = (await client.get("/openapi.json")).json()
    schemes = doc["components"]["securitySchemes"]
    assert any(s.get("scheme", "").lower() == "bearer" for s in schemes.values())
    assert doc["paths"]["/v1/drift/events"]["get"].get("security")


async def test_cors_preflight_allows_the_authorization_header(fresh_dsn, redis_url):
    async with live_client(settings_for(fresh_dsn, redis_url)) as client:
        r = await client.options(
            "/v1/drift/events",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    assert r.status_code == 200
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
