"""P3 end to end: two versions of an upload go through the real P2 pipeline (ingest
worker, outbox relay, embed stage with the TEI embedder), then as-of questions go through
the real gateway (uvicorn, `POST /v1/ask` and SSE) and the real answer graph (TEI
reranker, Postgres checkpointer, DeterministicAdapter running the offline
ExtractiveResponder for every LLM tier). No mocks.

Jobs are run by the real `AgentWorker` (one `run_once` per ask), which writes the
graph's events and the final answer to the per-ask event log and persists the answer.
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from dbseed import EMBED_MODEL
from livesrv import serve

from driftline.agents.eventlog import AskEventLog
from driftline.agents.graph import AgentDeps, build_answer_graph
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.agents.worker import AgentWorker
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.gateway.app import create_app
from driftline.ingest.connectors.upload import UploadConnector
from driftline.ingest.embed import EmbedStage
from driftline.ingest.outbox import OutboxRelay
from driftline.ingest.worker import IngestWorker, enqueue_ingest, ensure_source
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.streams.bus import StreamBus

DOC = "pharma/liver.md"
V1 = "# Liver safety\n\n## Monitoring\n\nCheck ALT every 12 weeks during therapy.\n"
V2 = "# Liver safety\n\n## Monitoring\n\nCheck ALT monthly during therapy.\n"
T1, T2 = 1_700_000_000, 1_750_000_000  # 2023-11-14, 2025-06-15
QUESTION = "How often should ALT be checked?"
READ_TIMEOUT_S = 60
DISCONNECT_AFTER = 3  # events read live before the client drops the connection

IN_FORCE = (
    "SELECT v.id FROM doc_versions v JOIN documents d ON d.id = v.document_id "
    "WHERE d.external_id = $1 AND v.valid_from <= $2 AND ($2 < v.valid_to OR v.valid_to IS NULL)"
)


def write(root: Path, text: str, mtime: int) -> None:
    path = root / DOC
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))


async def read_events(
    client: httpx.AsyncClient,
    url: str,
    *,
    last_event_id: int | None = None,
    limit: int | None = None,
    opened: asyncio.Event | None = None,
) -> list[dict[str, Any]]:
    """Read SSE frames until the server ends the stream, or until `limit` events, then
    drop the connection. Heartbeat comments are skipped; `opened` is set on the first
    line received (the stream body has started). Bounded by READ_TIMEOUT_S."""
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}

    async def read() -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        frame: dict[str, str] = {}
        async with client.stream("GET", url, headers=headers) as response:
            assert response.status_code == 200, response.status_code
            async for line in response.aiter_lines():
                if opened is not None:
                    opened.set()
                if line.startswith(":"):
                    continue
                if line:
                    key, _, value = line.partition(": ")
                    frame[key] = value
                    continue
                if "event" in frame:
                    events.append(
                        {
                            "id": int(frame["id"]) if "id" in frame else None,
                            "event": frame["event"],
                            "data": json.loads(frame["data"]),
                        }
                    )
                    if limit is not None and len(events) >= limit:
                        break
                frame = {}
        return events

    return await asyncio.wait_for(read(), READ_TIMEOUT_S)


@pytest.mark.slow
async def test_ask_as_of_each_version_with_sse_replay(
    fresh_dsn,
    fresh_pool,
    redis_url,
    redis_client,
    checkpointer,
    embedder_url,
    reranker_url,
    tmp_path,
):
    tei = TEIEmbeddingAdapter(embedder_url)
    det = DeterministicAdapter("det", responder=ExtractiveResponder())
    tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
    router = LLMRouter(
        providers={"tei": tei, "det": det},
        chains={**tiers, "embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    bus = StreamBus(redis_client)

    # 1. Two versions of one document through the real P2 pipeline.
    ingest = IngestWorker(
        pool=fresh_pool,
        bus=bus,
        redis=redis_client,
        connector_factory=lambda kind, config: UploadConnector(config["root"]),
        embed_stage=EmbedStage(router, model_name=EMBED_MODEL),
        extractor=None,
        consumer="e2e",
        clock=ManualClock(),
    )
    await ingest.setup()
    async with fresh_pool.acquire() as conn:
        source = await ensure_source(
            conn, tenant="e2e", kind="upload", config={"root": str(tmp_path)}
        )
    relay = OutboxRelay(fresh_pool, bus)
    for text, mtime in ((V1, T1), (V2, T2)):
        write(tmp_path, text, mtime)
        await enqueue_ingest(fresh_pool, bus, source_id=source, external_id=DOC)
        while await ingest.run_once():
            pass
        await relay.relay_once()
        while await ingest.run_once():
            pass
    async with fresh_pool.acquire() as conn:
        versions = {
            r["version_no"]: r["id"]
            for r in await conn.fetch("SELECT id, version_no FROM doc_versions")
        }
        assert sorted(versions) == [1, 2]
        assert await conn.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0
        chunk_version = {
            str(r["id"]): r["version_id"]
            for r in await conn.fetch("SELECT id, version_id FROM chunks")
        }

    # 2. The real answer graph, run by the real agent worker.
    deps = AgentDeps(
        pool=fresh_pool,
        llm=AgentLLM(router, ledger=CostLedger(fresh_pool)),
        retriever=HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL),
        reranker=TEIReranker(reranker_url),
    )
    graph = build_answer_graph(deps).compile(checkpointer=checkpointer)
    agent = AgentWorker(
        pool=fresh_pool,
        redis=redis_client,
        bus=bus,
        events=AskEventLog(redis_client),
        graph=graph,
        consumer="agent-e2e",
    )
    await agent.setup()

    async def drive_one_ask() -> None:
        assert await agent.run_once(block_ms=5000) == 1

    # 3. As-of asks through the real gateway: before the change, exactly at it, after it.
    settings = Settings(
        _env_file=None, database_url=fresh_dsn, redis_url=redis_url, sse_heartbeat_s=0.2
    )
    change = datetime.fromtimestamp(T2, UTC)
    expected = {
        "2024-06-01T00:00:00+00:00": (versions[1], "12 weeks"),
        change.isoformat(): (versions[2], "monthly"),
        "2025-07-01T00:00:00+00:00": (versions[2], "monthly"),
    }
    async with (
        serve(create_app(settings)) as base,
        httpx.AsyncClient(base_url=base, timeout=30) as client,
    ):
        for as_of, (version_id, phrase) in expected.items():
            r = await client.post(
                "/v1/ask", json={"question": QUESTION, "tenant": "e2e", "as_of": as_of}
            )
            assert r.status_code == 202, r.text
            job_id = r.json()["job_id"]
            url = f"/v1/jobs/{job_id}/events"

            # A client opens the live stream (first heartbeat received), the graph runs,
            # and the client drops after a few live events.
            opened = asyncio.Event()
            reader = asyncio.create_task(
                read_events(client, url, limit=DISCONNECT_AFTER, opened=opened)
            )
            await asyncio.wait_for(opened.wait(), READ_TIMEOUT_S)
            driver = asyncio.create_task(drive_one_ask())
            seen = await reader
            await asyncio.wait_for(driver, READ_TIMEOUT_S)
            assert [e["id"] for e in seen] == list(range(1, DISCONNECT_AFTER + 1)), seen

            # It reconnects with Last-Event-ID and gets exactly what it missed.
            rest = await read_events(client, url, last_event_id=seen[-1]["id"])
            full = await read_events(client, url)
            ids = [e["id"] for e in full]
            assert ids == list(range(1, len(ids) + 1))
            assert len(ids) > DISCONNECT_AFTER + 1
            assert [e["id"] for e in rest] == ids[DISCONNECT_AFTER:]
            assert seen + rest == full  # same events, in order, nothing repeated or lost

            # The final answer cites only the version in force on `as_of`.
            final = full[-1]
            assert final["event"] == "final"
            assert [e["event"] for e in full].count("final") == 1
            answer = final["data"]["answer"]
            assert answer["status"] == "answered", answer
            assert phrase in answer["answer"]
            assert datetime.fromisoformat(answer["as_of"]) == datetime.fromisoformat(as_of)
            cited = {c["version_id"] for c in answer["citations"]}
            assert cited == {str(version_id)}, (as_of, cited)
            for c in answer["citations"]:
                assert str(chunk_version[c["chunk_id"]]) == c["version_id"]
            # Out-of-window text never reaches the draft: the verifier's own in-force
            # check would drop such a claim, which would hide a broken retrieval filter.
            assert answer["dropped_claims"] == [], answer["dropped_claims"]
            claims = [e["data"] for e in full if e["event"] == "claim"]
            assert claims and all(c["verified"] for c in claims), claims

            # ... and that matches the validity windows stored in the database.
            async with fresh_pool.acquire() as conn:
                in_force = {
                    str(row["id"])
                    for row in await conn.fetch(IN_FORCE, DOC, datetime.fromisoformat(as_of))
                }
            assert cited == in_force

            # The worker persisted the same answer, and the job reports it.
            status = (await client.get(f"/v1/jobs/{job_id}")).json()
            assert status["status"] == "succeeded", status
            assert status["answer"]["answer"] == answer["answer"]
            assert {c["version_id"] for c in status["answer"]["citations"]} == cited
