"""Smoke tests for the shared P3 test infrastructure (real containers, real server)."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
from dbseed import VersionSeed, embed_all, seed_history, seed_source
from fastapi import FastAPI
from livesrv import serve


async def test_reranker_fixture_serves_rerank(reranker_url):
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{reranker_url}/rerank",
            json={"query": "How often is ALT checked?", "texts": ["kubectl", "Check ALT monthly."]},
        )
    assert r.status_code == 200
    assert r.json()[0]["index"] == 1


async def test_checkpointer_fixture_creates_tables(checkpointer, fresh_conn):
    assert await fresh_conn.fetchval("SELECT to_regclass('checkpoints')") == "checkpoints"


async def test_seed_history_closes_windows_and_embed_all(fresh_conn, embedder_url):
    _, source = await seed_source(fresh_conn)
    t1, t2 = datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)
    _, versions, chunks = await seed_history(
        fresh_conn,
        source,
        external_id="doc",
        title="Doc",
        versions=[
            VersionSeed(t1, [("A", "Old rule.")], version_key="v1"),
            VersionSeed(t2, [("A", "New rule."), ("B", "Extra.")], version_key="v2"),
        ],
    )
    rows = await fresh_conn.fetch(
        "SELECT valid_from, valid_to FROM doc_versions WHERE id = ANY($1) ORDER BY version_no",
        versions,
    )
    assert [(r["valid_from"], r["valid_to"]) for r in rows] == [(t1, t2), (t2, None)]
    assert [len(c) for c in chunks] == [1, 2]
    assert await embed_all(fresh_conn, embedder_url) == 3
    assert await fresh_conn.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0


async def test_live_server_serves_a_real_socket():
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "yes"}

    async with serve(app) as base_url, httpx.AsyncClient() as client:
        assert (await client.get(f"{base_url}/ping")).json() == {"pong": "yes"}


async def test_live_server_startup_failure_raises_instead_of_hanging():
    @asynccontextmanager
    async def broken_lifespan(app):
        raise RuntimeError("startup failed")
        yield

    app = FastAPI(lifespan=broken_lifespan)
    with pytest.raises(RuntimeError, match="did not start"):
        async with asyncio.timeout(15), serve(app):
            pass
