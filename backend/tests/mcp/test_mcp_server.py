"""The MCP server (P6) through the real MCP SDK client over Streamable HTTP.

The gateway runs on a real socket (uvicorn via `livesrv.serve`), the client is the SDK's
`Client` over `streamable_http_client`, and asks are answered by a real `AgentWorker`
running in-process (real Postgres + checkpointer, Redis, TEI embedder, and the
DeterministicAdapter running the in-repo ExtractiveResponder). No mocks, no stubs.
"""

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import httpx2
import pytest
from dbseed import EMBED_MODEL, VersionSeed, embed_all, seed_history, seed_source
from livesrv import serve
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError

from driftline.agents.eventlog import AskEventLog
from driftline.agents.graph import AgentDeps, build_answer_graph
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.agents.worker import AgentWorker
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.gateway.app import create_app
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.streams.bus import StreamBus

NOW = datetime(2026, 10, 25, tzinfo=UTC)
QUESTION = "How often should ALT be checked?"
OLD_RULE = "Check ALT every 12 weeks during therapy."
NEW_RULE = "Check ALT monthly during therapy."
ACME_KEY, OTHER_KEY = "acme-key", "other-key"
STEP_TIMEOUT_S = 90


@pytest.fixture
async def corpus(fresh_conn, embedder_url):
    """Tenant `acme`: one label with two versions (release-1.27 from 2023, release-1.28
    from 2025). Tenant `other`: an unrelated document of its own."""
    acme, acme_source = await seed_source(
        fresh_conn, kind="upload", tenant="acme", api_key=ACME_KEY
    )
    _, versions, _ = await seed_history(
        fresh_conn,
        acme_source,
        external_id="liver.md",
        title="Liver safety",
        versions=[
            VersionSeed(
                datetime(2023, 1, 1, tzinfo=UTC), [("Monitoring", OLD_RULE)], "release-1.27"
            ),
            VersionSeed(
                datetime(2025, 1, 1, tzinfo=UTC), [("Monitoring", NEW_RULE)], "release-1.28"
            ),
        ],
    )
    other, other_source = await seed_source(
        fresh_conn, kind="git_docs", tenant="other", api_key=OTHER_KEY
    )
    await seed_history(
        fresh_conn,
        other_source,
        external_id="keys.md",
        title="Key rotation",
        versions=[VersionSeed(datetime(2023, 1, 1, tzinfo=UTC), [("Keys", "Rotate keys yearly.")])],
    )
    await embed_all(fresh_conn, embedder_url)
    return {
        "acme": acme,
        "acme_source": acme_source,
        "other": other,
        "other_source": other_source,
        "old": versions[0],
        "new": versions[1],
    }


@pytest.fixture
async def gateway(fresh_dsn, redis_url, corpus):
    settings = Settings(
        _env_file=None, database_url=fresh_dsn, redis_url=redis_url, sse_heartbeat_s=0.2
    )
    async with serve(create_app(settings)) as base:
        yield base


@asynccontextmanager
async def running_worker(fresh_pool, redis_client, checkpointer, embedder_url):
    """A real agent worker consuming the `agent` stream in the background."""
    det = DeterministicAdapter("det", responder=ExtractiveResponder())
    tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
    router = LLMRouter(
        providers={"det": det, "tei": TEIEmbeddingAdapter(embedder_url)},
        chains={**tiers, "embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    deps = AgentDeps(
        pool=fresh_pool,
        llm=AgentLLM(router, ledger=CostLedger(fresh_pool)),
        retriever=HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL),
        reranker=TEIReranker(None),
        clock=ManualClock(NOW.timestamp()),
    )
    worker = AgentWorker(
        pool=fresh_pool,
        redis=redis_client,
        bus=StreamBus(redis_client),
        events=AskEventLog(redis_client),
        graph=build_answer_graph(deps).compile(checkpointer=checkpointer),
        consumer="mcp-test",
    )
    await worker.setup()
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    try:
        yield worker
    finally:
        stop.set()
        await asyncio.wait_for(task, 10)


@pytest.fixture
async def worker(fresh_pool, redis_client, checkpointer, embedder_url, corpus):
    async with running_worker(fresh_pool, redis_client, checkpointer, embedder_url) as w:
        yield w


@asynccontextmanager
async def mcp_client(base: str, key: str | None):
    headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
    async with httpx2.AsyncClient(
        headers=headers, timeout=httpx2.Timeout(30.0, read=STEP_TIMEOUT_S)
    ) as http_client:
        transport = streamable_http_client(f"{base}/mcp", http_client=http_client)
        async with Client(transport) as client:
            yield client


async def call(client, name: str, arguments: dict | None = None) -> dict:
    result = await asyncio.wait_for(client.call_tool(name, arguments or {}), STEP_TIMEOUT_S)
    assert not result.is_error, result.content
    assert result.structured_content is not None, result
    return result.structured_content


def cited_versions(answer: dict) -> set[str]:
    return {c["version_id"] for c in answer["citations"]}


async def test_list_tools_shows_ask_and_list_sources_with_schemas(gateway):
    async with mcp_client(gateway, ACME_KEY) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert {"ask", "list_sources"} <= tools.keys()
    ask = tools["ask"].input_schema
    assert ask["required"] == ["question"]
    assert {"question", "as_of", "source_kinds", "timeout_s"} <= ask["properties"].keys()
    assert tools["ask"].description and tools["list_sources"].description
    assert tools["list_sources"].input_schema.get("required", []) == []


async def test_ask_returns_a_cited_in_force_answer(gateway, worker, corpus):
    async with mcp_client(gateway, ACME_KEY) as client:
        answer = await call(client, "ask", {"question": QUESTION, "timeout_s": 60})
    assert answer["status"] == "answered", answer
    assert "monthly" in answer["answer"]
    assert cited_versions(answer) == {str(corpus["new"])}
    assert answer["answer_id"] is not None
    assert datetime.fromisoformat(answer["as_of"]) == NOW


async def test_ask_past_its_timeout_returns_running_with_the_job_id(gateway, corpus, fresh_conn):
    # No worker is running, so the job cannot finish within the tool's timeout.
    async with mcp_client(gateway, ACME_KEY) as client:
        started = time.monotonic()
        result = await call(client, "ask", {"question": QUESTION, "timeout_s": 1})
        elapsed = time.monotonic() - started
    assert result["status"] == "running" and set(result) == {"status", "job_id"}
    assert elapsed < 10
    row = await fresh_conn.fetchrow(
        "SELECT tenant_id, kind, status FROM jobs WHERE id = $1::uuid", result["job_id"]
    )
    assert (row["tenant_id"], row["kind"], row["status"]) == (corpus["acme"], "ask", "queued")


async def test_bad_or_missing_key_is_an_auth_error(gateway):
    for key in ("wrong-key", None):
        # The client fails to initialize; its transport task group may wrap the error.
        with pytest.raises((MCPError, ExceptionGroup)) as info:
            async with mcp_client(gateway, key) as client:
                await client.list_tools()
        if isinstance(info.value, ExceptionGroup):
            assert info.group_contains(MCPError), info.value
    # On the wire it is a 401 Bearer challenge, before any MCP message is handled.
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"},
        },
    }
    async with httpx.AsyncClient(base_url=gateway, timeout=10) as http:
        r = await http.post(
            "/mcp",
            json=init,
            headers={
                "Authorization": "Bearer wrong-key",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")


async def test_a_tenant_key_never_reads_another_tenants_data(gateway, worker, corpus):
    async with mcp_client(gateway, OTHER_KEY) as client:
        sources = (await call(client, "list_sources"))["sources"]
        answer = await call(client, "ask", {"question": QUESTION, "timeout_s": 60})
    assert [s["id"] for s in sources] == [str(corpus["other_source"])]
    assert not cited_versions(answer) & {str(corpus["old"]), str(corpus["new"])}
    assert "ALT" not in answer["answer"]


async def test_list_sources_lists_the_callers_sources(gateway, corpus):
    async with mcp_client(gateway, ACME_KEY) as client:
        sources = (await call(client, "list_sources"))["sources"]
    assert sources == [
        {
            "id": str(corpus["acme_source"]),
            "kind": "upload",
            "status": "active",
            "schedule": None,
            "last_polled_at": None,
            "documents": 1,
        }
    ]


async def rest_answer(base: str, question: str) -> dict:
    """The REST path: POST /v1/ask, then the job's answer once the worker is done."""
    async with httpx.AsyncClient(base_url=base, timeout=10) as http:
        r = await http.post(
            "/v1/ask",
            json={"question": question},
            headers={"Authorization": f"Bearer {ACME_KEY}"},
        )
        assert r.status_code == 202, r.text
        status_url = r.json()["status_url"]
        deadline = time.monotonic() + STEP_TIMEOUT_S
        while time.monotonic() < deadline:
            status = (
                await http.get(status_url, headers={"Authorization": f"Bearer {ACME_KEY}"})
            ).json()
            if status["status"] in ("succeeded", "failed"):
                assert status["status"] == "succeeded", status
                return status["answer"]
            await asyncio.sleep(0.1)
    raise AssertionError("REST ask did not finish")


@pytest.mark.parametrize(
    ("as_of", "version", "phrase"),
    [("2023", "old", "12 weeks"), ("v1.27", "old", "12 weeks"), ("v1.28", "new", "monthly")],
)
async def test_free_form_as_of_matches_the_rest_result(
    gateway, worker, corpus, as_of, version, phrase
):
    # REST resolves the time hint from the question text (P3 extract_as_of_hint path).
    rest = await rest_answer(gateway, f"{QUESTION} (as of {as_of})")
    async with mcp_client(gateway, ACME_KEY) as client:
        mcp = await call(client, "ask", {"question": QUESTION, "as_of": as_of, "timeout_s": 60})
    assert mcp["status"] == rest["status"] == "answered", (mcp, rest)
    assert mcp["as_of"] == rest["as_of"]
    assert cited_versions(mcp) == cited_versions(rest) == {str(corpus[version])}
    assert phrase in mcp["answer"]


async def test_unparseable_as_of_is_a_tool_error(gateway, corpus):
    async with mcp_client(gateway, ACME_KEY) as client:
        result = await client.call_tool("ask", {"question": QUESTION, "as_of": "someday"})
    assert result.is_error
    assert "as_of" in json.dumps([c.model_dump() for c in result.content])
