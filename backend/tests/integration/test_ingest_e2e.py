"""P2 end to end: an upload corpus through the ingest worker, the outbox relay and the
embed worker, against real Postgres, Redis and the TEI embedder (no mocks, no stubs)."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from driftline.clock import ManualClock
from driftline.ingest.chunker import count_tokens
from driftline.ingest.connectors.upload import UploadConnector
from driftline.ingest.embed import EmbedStage
from driftline.ingest.outbox import OutboxRelay
from driftline.ingest.supersession import SupersessionExtractor
from driftline.ingest.worker import EMBED_STREAM, IngestWorker, enqueue_ingest, ensure_source
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.streams.bus import StreamBus

EMBED_MODEL = "BAAI/bge-base-en-v1.5"
LIVER = "pharma/liver-safety.md"
RUNBOOK = "k8s/rollout-runbook.md"
CORPUS = {
    LIVER: "# Liver safety notes\n\n## Boxed warning\n\nSevere hepatotoxicity has been "
    "reported.\n\n## Monitoring\n\nCheck ALT before starting therapy.\n",
    RUNBOOK: "# Rollout runbook\n\n## Undo\n\nRun kubectl rollout undo deployment/web.\n",
}
T1, T2 = 1_700_000_000, 1_750_000_000

IN_FORCE = (
    "SELECT d.external_id, v.version_no FROM doc_versions v "
    "JOIN documents d ON d.id = v.document_id "
    "WHERE v.valid_from <= $1 AND ($1 < v.valid_to OR v.valid_to IS NULL) ORDER BY 1"
)


def write(root: Path, rel: str, text: str, mtime: int) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))


@pytest.fixture
async def stack(fresh_pool, redis_client, embedder_url, tmp_path):
    det = DeterministicAdapter("det")
    router = LLMRouter(
        providers={"tei": TEIEmbeddingAdapter(embedder_url), "det": det},
        chains={"embed": [Route("tei", EMBED_MODEL)], "extract": [Route("det", "det-extract")]},
        clock=ManualClock(),
    )
    bus = StreamBus(redis_client)
    worker = IngestWorker(
        pool=fresh_pool,
        bus=bus,
        redis=redis_client,
        connector_factory=lambda kind, config: UploadConnector(config["root"]),
        embed_stage=EmbedStage(router, model_name=EMBED_MODEL),
        extractor=SupersessionExtractor(router),
        consumer="e2e",
        clock=ManualClock(),
    )
    await worker.setup()
    async with fresh_pool.acquire() as conn:
        source = await ensure_source(
            conn, tenant="e2e", kind="upload", config={"root": str(tmp_path)}
        )
    return {
        "worker": worker,
        "relay": OutboxRelay(fresh_pool, bus),
        "bus": bus,
        "source": source,
        "root": tmp_path,
        "det": det,
        "pool": fresh_pool,
    }


async def ingest(stack, names) -> int:
    """Queue every name, drain the ingest stream, relay the outbox, drain the embed stream."""
    for name in names:
        await enqueue_ingest(
            stack["pool"], stack["bus"], source_id=stack["source"], external_id=name
        )
    while await stack["worker"].run_once():
        pass
    relayed = await stack["relay"].relay_once()
    while await stack["worker"].run_once():
        pass
    return relayed


@pytest.mark.slow
async def test_fixture_corpus_end_to_end(stack, redis_client):
    pool = stack["pool"]
    for rel, text in CORPUS.items():
        write(stack["root"], rel, text, T1)

    # 1. First ingest: one version per document, every chunk embedded by the real model.
    assert await ingest(stack, sorted(CORPUS)) == 2
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM doc_versions") == 2
        assert await conn.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0
        assert await conn.fetchval("SELECT DISTINCT embed_model FROM chunks") == EMBED_MODEL
        assert await conn.fetchval("SELECT max(vector_dims(embedding)) FROM chunks") == 768
    assert stack["det"].calls == []  # titles share no words: no candidates, no LLM call

    # 2. Re-ingesting identical content is a no-op: no version, no outbox row, no event.
    assert await ingest(stack, sorted(CORPUS)) == 0
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM doc_versions") == 2
        assert await conn.fetchval("SELECT count(*) FROM outbox") == 2

    # 3. A changed file closes the old validity window and publishes one event.
    changed = CORPUS[LIVER].replace("Check ALT before starting", "Check ALT monthly during")
    write(stack["root"], LIVER, changed, T2)
    assert await ingest(stack, [LIVER]) == 1
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT v.version_no, v.valid_from, v.valid_to, v.diff_from_prev "
            "FROM doc_versions v JOIN documents d ON d.id = v.document_id "
            "WHERE d.external_id = $1 ORDER BY v.version_no",
            LIVER,
        )
        assert [r["version_no"] for r in rows] == [1, 2]
        assert rows[0]["valid_to"] == rows[1]["valid_from"] == datetime.fromtimestamp(T2, tz=UTC)
        assert rows[1]["valid_to"] is None
        diff = json.loads(rows[1]["diff_from_prev"])
        assert diff["changed"] == ["Liver safety notes > Monitoring"]
        assert "Liver safety notes > Boxed warning" in diff["unchanged"]
        before = [tuple(r) for r in await conn.fetch(IN_FORCE, datetime.fromtimestamp(T1 + 1, UTC))]
        after = [tuple(r) for r in await conn.fetch(IN_FORCE, datetime.fromtimestamp(T2, UTC))]
        assert before == [(RUNBOOK, 1), (LIVER, 1)]
        assert after == [(RUNBOOK, 1), (LIVER, 2)]
        assert await conn.fetchval("SELECT count(*) FROM outbox WHERE published_at IS NULL") == 0
        assert await conn.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0
    events = [json.loads(f["data"]) for _, f in await redis_client.xrange(EMBED_STREAM)]
    assert sorted(e["version_no"] for e in events) == [1, 1, 2]
    assert len({e["event_id"] for e in events}) == 3
    assert {e["topic"] for e in events} == {"version.created"}


@pytest.mark.slow
async def test_huge_section_chunks_fit_embedder_limit(stack):
    rows = " ".join(
        f"Row {i}: 12.5 mg/kg ALT>3xULN in {i} patients; lot dd011a82-7356-4b83-86c4-b21cd9138fc6."
        for i in range(400)
    )
    assert count_tokens(rows) > 10_000
    write(stack["root"], "pharma/lab-table.md", f"# Lab table\n\n## Results\n\n{rows}\n", T1)
    assert await ingest(stack, ["pharma/lab-table.md"]) == 1
    async with stack["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM chunks") > 30
        assert await conn.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0
