"""The MCP version tools (P6 T3) and the configurable allowed hosts (T2b), through the real
MCP SDK client over Streamable HTTP against the gateway on a real socket. Real Postgres
and Redis; no mocks, no stubs."""

from datetime import UTC, datetime

import httpx
import httpx2
import pytest
from dbseed import VersionSeed, seed_history, seed_source, seed_watched_answer
from livesrv import serve
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from test_mcp_server import STEP_TIMEOUT_S, call, mcp_client

from driftline.config import Settings
from driftline.drift.diff import TRUNCATED
from driftline.gateway.app import create_app
from driftline.mcp.server import DIFF_VERSIONS_CAP_BYTES

ACME_KEY, OTHER_KEY = "acme-key", "other-key"
V1 = [("Dosage", "Take 10 mg daily."), ("Monitoring", "Check ALT every 12 weeks.")]
V2 = [
    ("Dosage", "Take 10 mg daily."),
    ("Monitoring", "Check ALT every 8 weeks."),
    ("Storage", "Store below 25 C."),
]
V3 = [("Dosage", "Take 10 mg daily."), ("Monitoring", "Check ALT monthly.")]


def at(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


@pytest.fixture
async def corpus(fresh_conn):
    """Tenant `acme`: a label with three versions and a watched-then-unwatched answer.
    Tenant `other`: a document and an answer of its own."""
    acme, acme_source = await seed_source(
        fresh_conn, kind="upload", tenant="acme", api_key=ACME_KEY
    )
    doc, versions, chunks = await seed_history(
        fresh_conn,
        acme_source,
        external_id="liver.md",
        title="Liver safety",
        versions=[
            VersionSeed(at(2023), V1, "release-1.27"),
            VersionSeed(at(2024), V2, "release-1.28"),
            VersionSeed(at(2025), V3, "release-1.29"),
        ],
    )
    answer = await seed_watched_answer(
        fresh_conn, acme, versions[2], [chunks[2][1]], [("ALT monthly.", "Check ALT monthly.")]
    )
    await fresh_conn.execute(
        "UPDATE answers SET watched = false, watched_at = NULL WHERE id = $1", answer
    )
    other, other_source = await seed_source(
        fresh_conn, kind="git_docs", tenant="other", api_key=OTHER_KEY
    )
    other_doc, other_versions, other_chunks = await seed_history(
        fresh_conn,
        other_source,
        external_id="keys.md",
        title="Key rotation",
        versions=[VersionSeed(at(2023), [("Keys", "Rotate keys yearly.")])],
    )
    other_answer = await seed_watched_answer(
        fresh_conn, other, other_versions[0], [other_chunks[0][0]], [("Yearly.", "yearly")]
    )
    await fresh_conn.execute("UPDATE answers SET watched = false WHERE id = $1", other_answer)
    return {
        "acme": acme,
        "doc": doc,
        "versions": versions,
        "answer": answer,
        "other_doc": other_doc,
        "other_answer": other_answer,
    }


def settings_for(fresh_dsn: str, redis_url: str, **overrides) -> Settings:
    return Settings(_env_file=None, database_url=fresh_dsn, redis_url=redis_url, **overrides)


@pytest.fixture
async def gateway(fresh_dsn, redis_url, corpus):
    async with serve(create_app(settings_for(fresh_dsn, redis_url))) as base:
        yield base


async def tool_error(client, name: str, arguments: dict) -> str:
    result = await client.call_tool(name, arguments)
    assert result.is_error, result
    return " ".join(getattr(c, "text", "") for c in result.content)


async def test_list_tools_shows_the_version_tools_with_schemas(gateway):
    async with mcp_client(gateway, ACME_KEY) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"diff_versions", "get_timeline", "watch_answer"} <= tools.keys()
    diff = tools["diff_versions"].input_schema
    assert diff["required"] == ["document_id"]
    assert {"document_id", "from_version", "to_version"} <= diff["properties"].keys()
    assert tools["get_timeline"].input_schema["required"] == ["document_id"]
    assert tools["watch_answer"].input_schema["required"] == ["answer_id"]
    assert all(tools[n].description for n in ("diff_versions", "get_timeline", "watch_answer"))


async def test_diff_versions_defaults_to_previous_vs_latest(gateway, corpus):
    async with mcp_client(gateway, ACME_KEY) as client:
        diff = await call(client, "diff_versions", {"document_id": str(corpus["doc"])})
    assert (diff["from_version"], diff["to_version"]) == (2, 3)
    assert diff["document_id"] == str(corpus["doc"])
    assert diff["from_version_id"] == str(corpus["versions"][1])
    assert diff["to_version_id"] == str(corpus["versions"][2])
    assert diff["sections"] == [
        {"section_path": "Dosage", "status": "unchanged"},
        {"section_path": "Monitoring", "status": "changed"},
        {"section_path": "Storage", "status": "removed"},
    ]
    assert "-Check ALT every 8 weeks." in diff["diff"]
    assert "+Check ALT monthly." in diff["diff"]
    assert "-Store below 25 C." in diff["diff"]
    assert "Take 10 mg daily." not in diff["diff"]  # unchanged sections are not diffed
    assert diff["truncated"] is False


async def test_diff_versions_between_explicit_versions(gateway, corpus):
    async with mcp_client(gateway, ACME_KEY) as client:
        diff = await call(
            client,
            "diff_versions",
            {"document_id": str(corpus["doc"]), "from_version": 1, "to_version": 2},
        )
        only_to = await call(
            client, "diff_versions", {"document_id": str(corpus["doc"]), "to_version": 2}
        )
    assert diff["sections"] == [
        {"section_path": "Dosage", "status": "unchanged"},
        {"section_path": "Monitoring", "status": "changed"},
        {"section_path": "Storage", "status": "added"},
    ]
    assert "-Check ALT every 12 weeks." in diff["diff"]
    assert "+Store below 25 C." in diff["diff"]
    assert only_to == diff


async def test_diff_versions_rejects_unknown_or_missing_versions(gateway, corpus, fresh_conn):
    doc = str(corpus["doc"])
    _, single, _ = await seed_history(
        fresh_conn,
        await fresh_conn.fetchval("SELECT source_id FROM documents WHERE id = $1", corpus["doc"]),
        external_id="single.md",
        title="Single",
        versions=[VersionSeed(at(2023), [("A", "a")])],
    )
    single_doc = await fresh_conn.fetchval(
        "SELECT document_id FROM doc_versions WHERE id = $1", single[0]
    )
    async with mcp_client(gateway, ACME_KEY) as client:
        unknown = await tool_error(client, "diff_versions", {"document_id": doc, "to_version": 9})
        same = await tool_error(
            client, "diff_versions", {"document_id": doc, "from_version": 2, "to_version": 2}
        )
        only_one = await tool_error(client, "diff_versions", {"document_id": str(single_doc)})
    assert "version 9" in unknown and "not found" in unknown
    assert "differ" in same
    assert "only one version" in only_one


async def test_a_large_diff_is_capped_with_a_truncation_marker(gateway, corpus, fresh_conn):
    source = await fresh_conn.fetchval(
        "SELECT source_id FROM documents WHERE id = $1", corpus["doc"]
    )
    big_old = "\n".join(f"old line {i} " + "x" * 60 for i in range(400))
    big_new = "\n".join(f"new line {i} " + "y" * 60 for i in range(400))
    big_doc, _, _ = await seed_history(
        fresh_conn,
        source,
        external_id="big.md",
        title="Big",
        versions=[
            VersionSeed(at(2023), [("A", big_old), ("B", big_old)]),
            VersionSeed(at(2024), [("A", big_new), ("B", big_new)]),
        ],
    )
    async with mcp_client(gateway, ACME_KEY) as client:
        diff = await call(client, "diff_versions", {"document_id": str(big_doc)})
    assert diff["truncated"] is True
    assert len(diff["diff"].encode("utf-8")) <= DIFF_VERSIONS_CAP_BYTES == 16 * 1024
    assert diff["diff"].endswith(TRUNCATED)
    # Every section still gets its status, even when its diff did not fit.
    assert diff["sections"] == [
        {"section_path": "A", "status": "changed"},
        {"section_path": "B", "status": "changed"},
    ]


async def test_get_timeline_matches_the_rest_timeline(gateway, corpus):
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as http:
        r = await http.get(
            f"/v1/documents/{corpus['doc']}/timeline",
            headers={"Authorization": f"Bearer {ACME_KEY}"},
        )
    assert r.status_code == 200, r.text
    async with mcp_client(gateway, ACME_KEY) as client:
        timeline = await call(client, "get_timeline", {"document_id": str(corpus["doc"])})
    assert timeline == r.json()
    assert [v["version_key"] for v in timeline["versions"]] == [
        "release-1.27",
        "release-1.28",
        "release-1.29",
    ]


async def test_watch_answer_watches_the_callers_answer(gateway, corpus, fresh_conn):
    async with mcp_client(gateway, ACME_KEY) as client:
        result = await call(client, "watch_answer", {"answer_id": str(corpus["answer"])})
    assert result == {"answer_id": str(corpus["answer"]), "watched": True}
    row = await fresh_conn.fetchrow(
        "SELECT watched, watched_at FROM answers WHERE id = $1", corpus["answer"]
    )
    assert row["watched"] and row["watched_at"] is not None


async def test_another_tenants_ids_are_not_found(gateway, corpus, fresh_conn):
    async with mcp_client(gateway, ACME_KEY) as client:
        errors = [
            await tool_error(client, "diff_versions", {"document_id": str(corpus["other_doc"])}),
            await tool_error(client, "get_timeline", {"document_id": str(corpus["other_doc"])}),
            await tool_error(client, "watch_answer", {"answer_id": str(corpus["other_answer"])}),
        ]
    for error in errors:
        assert "not found" in error, error
    assert str(corpus["other_doc"]) in errors[0]
    watched = await fresh_conn.fetchval(
        "SELECT watched FROM answers WHERE id = $1", corpus["other_answer"]
    )
    assert watched is False


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"},
    },
}


async def post_init(base: str, host: str) -> int:
    async with httpx.AsyncClient(base_url=base, timeout=10) as http:
        r = await http.post(
            "/mcp",
            json=INIT,
            headers={
                "Host": host,
                "Authorization": f"Bearer {ACME_KEY}",
                "Accept": "application/json, text/event-stream",
            },
        )
    return r.status_code


async def test_default_allowed_hosts_are_localhost_only(gateway):
    port = gateway.rsplit(":", 1)[1]
    assert await post_init(gateway, f"localhost:{port}") == 200
    assert await post_init(gateway, f"127.0.0.1:{port}") == 200
    assert await post_init(gateway, "gateway:8000") == 421
    assert await post_init(gateway, "evil.example") == 421


async def test_configured_allowed_hosts_are_accepted(fresh_dsn, redis_url, corpus):
    settings = settings_for(fresh_dsn, redis_url, mcp_allowed_hosts=["gateway:*"])
    async with serve(create_app(settings)) as base:
        assert await post_init(base, "evil.example") == 421
        assert await post_init(base, "gateway:8000") == 200
        # The real SDK client works through the configured host name.
        headers = {"Authorization": f"Bearer {ACME_KEY}", "Host": "gateway:8000"}
        async with httpx2.AsyncClient(
            headers=headers, timeout=httpx2.Timeout(30.0, read=STEP_TIMEOUT_S)
        ) as http_client:
            transport = streamable_http_client(f"{base}/mcp", http_client=http_client)
            async with Client(transport) as client:
                timeline = await call(client, "get_timeline", {"document_id": str(corpus["doc"])})
    assert len(timeline["versions"]) == 3


def test_allowed_hosts_default_to_localhost_on_any_port():
    assert Settings(_env_file=None).mcp_allowed_hosts == ["localhost:*", "127.0.0.1:*", "[::1]:*"]
