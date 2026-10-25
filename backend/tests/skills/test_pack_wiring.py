"""Skill packs wired into real retrieval and the real agent worker: Postgres, Redis, TEI
embedder, LangGraph checkpointer and the DeterministicAdapter (no mocks)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from dbseed import EMBED_MODEL, VersionSeed, embed_all, seed_history, seed_source

from driftline.agents.eventlog import AskEventLog
from driftline.agents.graph import AgentDeps, build_answer_graph
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.agents.schemas import AGENT_STREAM, AskJob
from driftline.agents.worker import AgentWorker
from driftline.clock import ManualClock
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker
from driftline.retrieval.types import RetrievalQuery
from driftline.skills import PackError, resolve_pack, use_pack
from driftline.streams.bus import StreamBus

SKILLS_ROOT = Path(__file__).resolve().parents[3] / "skills"
NOW = datetime(2026, 10, 25, tzinfo=UTC)
RULES = [
    ("Boxed Warning", "Serious liver injury has been reported; check ALT monthly."),
    ("Contraindications", "Do not use in patients with active liver disease."),
    ("Adverse Reactions", "The most common adverse reaction is muscle pain."),
    ("Dosage and Administration", "Take 10 mg once daily with or without food."),
]


@pytest.fixture
async def corpus(fresh_conn, embedder_url):
    tenant, source = await seed_source(fresh_conn, kind="openfda")
    await seed_history(
        fresh_conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[VersionSeed(datetime(2024, 4, 15, tzinfo=UTC), RULES)],
    )
    await embed_all(fresh_conn, embedder_url)
    return tenant


def embed_router(embedder_url, **providers) -> LLMRouter:
    tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
    return LLMRouter(
        providers={"tei": TEIEmbeddingAdapter(embedder_url), **providers},
        chains={**(tiers if providers else {}), "embed": [Route("tei", EMBED_MODEL)]},
        clock=ManualClock(),
    )


async def test_hybrid_retrieval_uses_the_pack_candidates_and_rrf_k(
    fresh_pool, corpus, embedder_url
):
    retriever = HybridRetriever(fresh_pool, embed_router(embedder_url), embed_model=EMBED_MODEL)
    query = RetrievalQuery(tenant_id=corpus, text="liver ALT injury", as_of=NOW)
    assert len(await retriever.retrieve(query)) == 4

    base = resolve_pack(SKILLS_ROOT, "generic@1.0.0")
    pack = base.model_copy(
        update={"retrieval": base.retrieval.model_copy(update={"candidates": 1, "rrf_k": 1})}
    )
    with use_pack(pack):
        found = await retriever.retrieve(query)
    assert 1 <= len(found) <= 2  # one candidate from each search
    assert found[0].score in (pytest.approx(1 / 2), pytest.approx(1 / 2 + 1 / 2))
    # An explicit argument wins over the active pack.
    explicit = await retriever.retrieve(query, params=pack.retrieval)
    assert [e.chunk_id for e in explicit] == [e.chunk_id for e in found]


async def worker_for(fresh_pool, redis_client, checkpointer, embedder_url, skills_root):
    det = DeterministicAdapter("det", responder=ExtractiveResponder())
    router = embed_router(embedder_url, det=det)
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
        consumer="w1",
        clock=ManualClock(NOW.timestamp()),
        skills_root=skills_root,
    )
    await worker.setup()
    return det, worker


async def ask(fresh_conn, redis_client, tenant, question) -> AskJob:
    job_id = await fresh_conn.fetchval(
        "INSERT INTO jobs (tenant_id, kind, status) VALUES ($1, 'ask', 'queued') RETURNING id",
        tenant,
    )
    job = AskJob(job_id=job_id, tenant_id=tenant, question=question)
    await StreamBus(redis_client).publish(AGENT_STREAM, job.model_dump(mode="json"))
    return job


@pytest.mark.parametrize(
    ("skill_pack", "expected_notes"),
    [("pharma@1.0.0", "REMS"), ("nosuch@1.0.0", "<domain_notes>"), (None, "<domain_notes>")],
)
async def test_worker_runs_each_job_with_its_tenant_pack(
    fresh_pool,
    fresh_conn,
    redis_client,
    checkpointer,
    embedder_url,
    corpus,
    skill_pack,
    expected_notes,
):
    await fresh_conn.execute("UPDATE tenants SET skill_pack = $2 WHERE id = $1", corpus, skill_pack)
    det, worker = await worker_for(
        fresh_pool, redis_client, checkpointer, embedder_url, SKILLS_ROOT
    )
    job = await ask(fresh_conn, redis_client, corpus, "What does the boxed warning say?")
    assert await worker.run_once() == 1
    status = await fresh_conn.fetchval("SELECT status FROM jobs WHERE id = $1", job.job_id)
    assert status == "succeeded"
    users = [
        r.messages[-1].content for r in det.requests if r.schema_name in ("plan", "draft_answer")
    ]
    assert users and all(expected_notes in u for u in users)
    if skill_pack != "pharma@1.0.0":
        assert all("REMS" not in u for u in users)  # the generic pack, not pharma


async def test_worker_without_skills_root_keeps_prompts_unchanged(
    fresh_pool, fresh_conn, redis_client, checkpointer, embedder_url, corpus
):
    await fresh_conn.execute("UPDATE tenants SET skill_pack = 'pharma@1.0.0' WHERE id = $1", corpus)
    det, worker = await worker_for(fresh_pool, redis_client, checkpointer, embedder_url, None)
    await ask(fresh_conn, redis_client, corpus, "What does the boxed warning say?")
    assert await worker.run_once() == 1
    assert det.requests and all(
        "<domain_notes>" not in r.messages[-1].content for r in det.requests
    )


async def test_worker_setup_fails_on_a_malformed_pack(
    fresh_pool, redis_client, checkpointer, embedder_url, tmp_path
):
    bad = tmp_path / "skills" / "broken@1.0.0"
    bad.mkdir(parents=True)
    (bad / "config.yaml").write_text("name: broken\nversion: 1.0.0\nretrieval: [\n")
    with pytest.raises(PackError, match=r"broken@1\.0\.0/config\.yaml"):
        await worker_for(fresh_pool, redis_client, checkpointer, embedder_url, tmp_path / "skills")
