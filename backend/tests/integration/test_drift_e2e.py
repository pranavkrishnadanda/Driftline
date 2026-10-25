"""P4 end to end: a watched answer drifts as its source document changes.

Everything is real: the P2 pipeline (ingest worker, outbox relay, embed stage with the
TEI embedder), the P3 answer graph run by the `AgentWorker` (TEI reranker, Postgres
checkpointer, DeterministicAdapter with the offline ExtractiveResponder for every LLM
tier), the drift engine run by the `DriftWorker`, and the gateway under uvicorn
(`POST /v1/ask`, the watch, alerts SSE, drift events and review APIs). No mocks.

The story:
1. v1 of a document is ingested; two questions are asked and both answers watched.
2. v2 changes the cited "Monitoring" section: the ALT answer drifts (`changed`, a live
   alert with before/after text), the storage answer is re-pointed silently.
3. v3 removes "Monitoring": the ALT answer is `broken` and goes to review.
4. Resolving it regenerates the answer, which pauses for review again (a regenerated
   watched answer is always reviewed); resolving that one replaces the answer, which
   then cites v3. Each resolve writes its follow-up agent job to the outbox in the
   resolve transaction, so the outbox relay runs before the agent worker picks it up.
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

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
from driftline.drift.alerts import AlertLog
from driftline.drift.engine import DriftEngine
from driftline.drift.worker import DriftWorker
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

TENANT = "drift-e2e"
DOC = "pharma/liver.md"
STORAGE = "## Storage\n\nStore tablets below 25 C in the original pack.\n"
V1 = "# Liver safety\n\n## Monitoring\n\nCheck ALT every 12 weeks during therapy.\n\n" + STORAGE
V2 = "# Liver safety\n\n## Monitoring\n\nCheck ALT monthly during therapy.\n\n" + STORAGE
V3 = "# Liver safety\n\n## Liver tests\n\nCheck ALT every two weeks during therapy.\n\n" + STORAGE
T1, T2, T3 = 1_700_000_000, 1_730_000_000, 1_760_000_000  # all in the past
ALT_Q = "How often should ALT be checked?"
STORAGE_Q = "How should tablets be stored?"
TIMEOUT_S = 60


def write(root: Path, text: str, mtime: int) -> None:
    path = root / DOC
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))


def parse_frames(lines: list[str]) -> dict[str, Any] | None:
    frame: dict[str, str] = {}
    for line in lines:
        key, _, value = line.partition(": ")
        frame[key] = value
    if "event" not in frame:
        return None
    return {
        "id": int(frame["id"]) if "id" in frame else None,
        "event": frame["event"],
        "data": json.loads(frame["data"]),
    }


class SSEFeed:
    """Reads an SSE stream in the background and collects its events."""

    def __init__(self, client: httpx.AsyncClient, url: str) -> None:
        self.events: list[dict[str, Any]] = []
        self.opened = asyncio.Event()
        self._changed = asyncio.Condition()
        self._task = asyncio.create_task(self._read(client, url))

    async def _read(self, client: httpx.AsyncClient, url: str) -> None:
        lines: list[str] = []
        async with client.stream("GET", url) as response:
            assert response.status_code == 200, response.status_code
            async for line in response.aiter_lines():
                self.opened.set()
                if line.startswith(":"):
                    continue
                if line:
                    lines.append(line)
                    continue
                event = parse_frames(lines)
                lines = []
                if event is not None:
                    async with self._changed:
                        self.events.append(event)
                        self._changed.notify_all()
                    if event["event"] in ("final", "error") and "/jobs/" in url:
                        return

    async def wait_for(self, predicate) -> dict[str, Any]:
        async def wait() -> dict[str, Any]:
            async with self._changed:
                while True:
                    for event in self.events:
                        if predicate(event):
                            return event
                    if self._task.done():
                        self._task.result()
                        raise AssertionError(f"stream ended without a match: {self.events}")
                    await self._changed.wait()

        return await asyncio.wait_for(wait(), TIMEOUT_S)

    async def close(self) -> None:
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, httpx.HTTPError):
            pass


@pytest.mark.slow
async def test_watched_answer_drifts_breaks_and_is_regenerated(
    fresh_dsn,
    fresh_pool,
    redis_url,
    redis_client,
    checkpointer,
    embedder_url,
    reranker_url,
    tmp_path,
):
    clock = ManualClock(T3 + 1000)
    tei = TEIEmbeddingAdapter(embedder_url)
    det = DeterministicAdapter("det", responder=ExtractiveResponder())
    tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
    router = LLMRouter(
        providers={"tei": tei, "det": det},
        chains={**tiers, "embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )
    bus = StreamBus(redis_client)
    settings = Settings(
        _env_file=None, database_url=fresh_dsn, redis_url=redis_url, sse_heartbeat_s=0.2
    )

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
    relay = OutboxRelay(fresh_pool, bus, alerts=AlertLog(redis_client))
    drift = DriftWorker(
        bus,
        DriftEngine(fresh_pool, router, clock, settings),
        clock,
        redis=redis_client,
        consumer="drift-e2e",
    )
    await drift.setup()
    deps = AgentDeps(
        pool=fresh_pool,
        llm=AgentLLM(router, ledger=CostLedger(fresh_pool)),
        retriever=HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL),
        reranker=TEIReranker(reranker_url),
    )
    agent = AgentWorker(
        pool=fresh_pool,
        redis=redis_client,
        bus=bus,
        events=AskEventLog(redis_client),
        graph=build_answer_graph(deps).compile(checkpointer=checkpointer),
        consumer="agent-e2e",
    )
    await agent.setup()

    async with fresh_pool.acquire() as conn:
        source = await ensure_source(
            conn, tenant=TENANT, kind="upload", config={"root": str(tmp_path)}
        )

    async def ingest_version(text: str, mtime: int) -> UUID:
        """One version through the real pipeline, then the drift worker on its event."""
        write(tmp_path, text, mtime)
        await enqueue_ingest(fresh_pool, bus, source_id=source, external_id=DOC)
        while await ingest.run_once():
            pass
        assert await relay.relay_once() >= 1  # version.created -> embed + drift
        while await ingest.run_once():
            pass
        clock.advance(60)
        assert await drift.run_once(block_ms=2000) == 1
        await relay.relay_once()  # drift.alert rows -> the tenant's alert stream
        async with fresh_pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT v.id FROM doc_versions v JOIN documents d ON d.id = v.document_id "
                "WHERE d.external_id = $1 ORDER BY v.version_no DESC LIMIT 1",
                DOC,
            )

    async def cited_versions(answer_id: UUID) -> set[UUID]:
        async with fresh_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT c.version_id FROM answer_citations ac JOIN chunks c ON c.id = ac.chunk_id "
                "WHERE ac.answer_id = $1",
                answer_id,
            )
        return {r["version_id"] for r in rows}

    async def body(answer_id: UUID) -> dict:
        async with fresh_pool.acquire() as conn:
            return json.loads(
                await conn.fetchval("SELECT body FROM answers WHERE id = $1", answer_id)
            )

    q = f"tenant={TENANT}"
    async with (
        serve(create_app(settings)) as base,
        httpx.AsyncClient(base_url=base, timeout=30) as client,
    ):

        def ended(e: dict[str, Any]) -> bool:
            return e["event"] in ("final", "error")

        def ended_or_paused(e: dict[str, Any]) -> bool:
            return ended(e) or (e["event"] == "step" and e["data"].get("status") == "waiting")

        async def run_job(job_id: str, until=ended_or_paused) -> dict[str, Any]:
            """Follow the job's SSE while the agent worker runs it; returns the first event
            matching `until` (the stream replays from the start of the job)."""
            feed = SSEFeed(client, f"/v1/jobs/{job_id}/events")
            await asyncio.wait_for(feed.opened.wait(), TIMEOUT_S)
            assert await agent.run_once(block_ms=5000) == 1
            last = await feed.wait_for(until)
            await feed.close()
            return last

        async def ask_and_watch(question: str) -> UUID:
            r = await client.post("/v1/ask", json={"question": question, "tenant": TENANT})
            assert r.status_code == 202, r.text
            final = await run_job(r.json()["job_id"])
            assert final["event"] == "final", final
            answer = final["data"]["answer"]
            assert answer["status"] == "answered", answer
            status = (await client.get(r.json()["status_url"])).json()
            answer_id = UUID(status["answer"]["answer_id"])
            w = await client.post(f"/v1/answers/{answer_id}/watch?{q}")
            assert w.status_code == 200 and w.json()["watched"] is True, w.text
            return answer_id

        # 1. v1 through the real pipeline; two asks, both watched.
        v1 = await ingest_version(V1, T1)
        alt = await ask_and_watch(ALT_Q)
        storage = await ask_and_watch(STORAGE_Q)
        assert await cited_versions(alt) == {v1}
        assert await cited_versions(storage) == {v1}
        assert "12 weeks" in (await body(alt))["answer"]

        # 2. The alert stream is open before anything drifts.
        alerts = SSEFeed(client, f"/v1/alerts/stream?{q}")
        await asyncio.wait_for(alerts.opened.wait(), TIMEOUT_S)

        # 3. v2 changes the cited section: a live `changed` alert with before/after.
        v2 = await ingest_version(V2, T2)
        changed = await alerts.wait_for(lambda e: e["event"] == "alert")
        data = changed["data"]
        assert data["verdict"] == "changed", data
        assert UUID(data["answer_id"]) == alt
        assert UUID(data["old_version_id"]) == v1 and UUID(data["new_version_id"]) == v2
        assert "12 weeks" in data["before"] and "monthly" in data["after"], data
        assert data["document_title"] == "Liver safety"

        listed = (await client.get(f"/v1/drift/events?{q}")).json()["events"]
        by_answer = {UUID(e["answer_id"]): e for e in listed}
        assert by_answer[alt]["verdict"] == "changed"
        assert by_answer[alt]["id"] == data["drift_event_id"]
        assert "12 weeks" in by_answer[alt]["before"] and "monthly" in by_answer[alt]["after"]
        assert by_answer[alt]["diff"]
        # A changed section is not re-pointed: the answer still cites v1.
        assert await cited_versions(alt) == {v1}

        # 4. The unchanged section's answer is re-pointed silently: still_valid, no alert.
        assert by_answer[storage]["verdict"] == "still_valid"
        assert await cited_versions(storage) == {v2}
        assert {c["version_id"] for c in (await body(storage))["citations"]} == {str(v2)}

        # 5. v3 removes the cited section: `broken`, and a broken_answer review item.
        v3 = await ingest_version(V3, T3)
        broken = await alerts.wait_for(
            lambda e: e["event"] == "alert" and e["data"]["verdict"] == "broken"
        )
        assert UUID(broken["data"]["answer_id"]) == alt
        assert UUID(broken["data"]["new_version_id"]) == v3
        assert broken["data"]["after"] is None
        assert all(
            UUID(e["data"]["answer_id"]) == alt for e in alerts.events if e["event"] == "alert"
        )
        assert [e["data"]["verdict"] for e in alerts.events if e["event"] == "alert"] == [
            "changed",
            "broken",
        ]
        await alerts.close()
        assert await cited_versions(storage) == {v3}  # re-pointed silently again

        items = (await client.get(f"/v1/review?{q}&kind=broken_answer")).json()["items"]
        assert [(i["kind"], UUID(i["ref_id"])) for i in items] == [("broken_answer", alt)]

        # 6. Two resolves: the regenerated watched answer pauses for review once more.
        r = await client.post(
            f"/v1/review/{items[0]['id']}/resolve?{q}", json={"action": "approve", "by": "qa"}
        )
        assert r.status_code == 200, r.text
        regen_job = r.json()["resolution"]["job_id"]
        # The regeneration job reaches the `agent` stream only through the outbox.
        assert await relay.relay_once() == 1  # ask.regenerate -> agent
        paused = await run_job(regen_job)
        assert paused["event"] == "step" and paused["data"]["status"] == "waiting", paused
        assert await cited_versions(alt) == {v1}  # not replaced before the review

        pending = (await client.get(f"/v1/review?{q}&kind=low_confidence_answer")).json()["items"]
        assert [i["ref_id"] for i in pending] == [regen_job]
        r = await client.post(
            f"/v1/review/{pending[0]['id']}/resolve?{q}", json={"action": "approve", "by": "qa"}
        )
        assert r.status_code == 200, r.text
        assert await relay.relay_once() == 1  # ask.resume -> agent
        final = await run_job(regen_job, until=ended)
        assert final["event"] == "final", final

        # The regeneration moved the answer's job link: the regen job's status shows it.
        status = await client.get(f"/v1/jobs/{regen_job}?{q}")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "succeeded", status.json()
        job_answer = status.json()["answer"]
        assert UUID(job_answer["answer_id"]) == alt, job_answer
        assert "two weeks" in job_answer["answer"], job_answer

        # The watched answer now cites v3, with v3's citation metadata.
        assert await cited_versions(alt) == {v3}
        regenerated = await body(alt)
        assert "two weeks" in regenerated["answer"], regenerated
        assert regenerated["citations"]
        for c in regenerated["citations"] + [
            cit for claim in regenerated["claims"] for cit in claim["citations"]
        ]:
            assert c["version_id"] == str(v3)
            assert c["version_no"] == 3
            assert c["external_id"] == DOC
            assert c["section_path"].endswith("Liver tests")
            assert datetime.fromisoformat(c["valid_from"]) == datetime.fromtimestamp(T3, UTC)
            assert c["valid_to"] is None
        async with fresh_pool.acquire() as conn:
            assert await conn.fetchval("SELECT watched FROM answers WHERE id = $1", alt)
        assert (await client.get(f"/v1/review?{q}")).json()["items"] == []
