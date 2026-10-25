"""`faithfulness_judge` with the real judge tier (Claude Sonnet), replayed from a cassette.

The system under evaluation answers with the in-repo ExtractiveResponder; only the judge
tier is Claude, so the cassette holds exactly the judge calls. Record it once with
`uv run --env-file <backend/.env> pytest <this file> --record-mode=once`; without the
cassette (and with record mode none) the test skips.
"""

import os
from datetime import UTC, date, datetime

import pytest
from conftest_cassettes import scrub_response_headers
from dbseed import EMBED_MODEL, VersionSeed, embed_all, seed_history, seed_source

from driftline.agents.graph import AgentConfig, AgentDeps
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.clock import ManualClock
from driftline.eval.runner import EvalDeps, run
from driftline.eval.types import GoldenCase
from driftline.llm.adapters.anthropic import AnthropicAdapter
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker

API_KEY = os.environ.get("DRIFTLINE_ANTHROPIC_API_KEY", "replay-only")
JUDGE_MODEL = "claude-sonnet-5-5"
T_OLD, T_NEW = datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 4, 15, tzinfo=UTC)
OLD_RULE = "Check ALT every 12 weeks during therapy."
NEW_RULE = "Check ALT monthly during therapy."


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["x-api-key", "authorization"],
        "before_record_response": scrub_response_headers,
        "match_on": ["method", "scheme", "host", "path"],
        "ignore_localhost": True,  # Postgres and TEI stay real and unrecorded
    }


@pytest.mark.vcr
async def test_claude_judge_scores_faithfulness_judge(
    require_cassette, fresh_conn, fresh_pool, embedder_url
):
    tenant, source = await seed_source(fresh_conn, kind="openfda", tenant="pharma")
    _, (old_v, new_v), _ = await seed_history(
        fresh_conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[
            VersionSeed(T_OLD, [("Warnings > Liver", OLD_RULE)]),
            VersionSeed(T_NEW, [("Warnings > Liver", NEW_RULE)]),
        ],
    )
    await embed_all(fresh_conn, embedder_url)
    det = DeterministicAdapter("det", responder=ExtractiveResponder())
    router = LLMRouter(
        providers={
            "det": det,
            "anthropic": AnthropicAdapter(API_KEY),
            "tei": TEIEmbeddingAdapter(embedder_url),
        },
        chains={
            "extract": [Route("det", "det-extract")],
            "answer": [Route("det", "det-answer")],
            "judge": [Route("anthropic", JUDGE_MODEL)],
            "embed": [Route("tei", EMBED_MODEL)],
        },
        clock=ManualClock(),
    )
    agent = AgentDeps(
        pool=fresh_pool,
        llm=AgentLLM(router, ledger=CostLedger(fresh_pool)),
        retriever=HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL),
        reranker=TEIReranker(None),
        clock=ManualClock(datetime(2026, 10, 25, tzinfo=UTC).timestamp()),
        config=AgentConfig(),
    )
    deps = EvalDeps(agent=agent, tenant_id=tenant, git_sha="a1b2c3d", judge_sample=2)
    case = GoldenCase(
        id="pharma-001",
        corpus="pharma",
        kind="point_in_time",
        question="How often should ALT be checked?",
        as_of=date(2023, 6, 1),
        expected_answer="Every 12 weeks during therapy.",
        expected_version_ids=[old_v],
        expected_quotes=[OLD_RULE],
        trap=True,
    )
    report = await run("pharma", "plain_rag", [case], deps)

    # plain_rag cites both versions (no as-of filter); each claim restates its quote, so
    # the judge should find both entailed. Two judge calls, both on the judge tier.
    assert report.metrics["claims_judged"] == 2.0
    assert report.metrics["faithfulness_judge"] == 1.0
    assert "judge=anthropic/claude-sonnet-5-5" in report.llm
    assert det.calls.count("det-judge") == 0
    row = await fresh_conn.fetchrow(
        "SELECT count(*) AS n, sum(cost_usd) AS cost, min(model) AS model "
        "FROM llm_calls WHERE node = 'eval_judge'"
    )
    assert (row["n"], row["model"]) == (2, JUDGE_MODEL)
    assert row["cost"] > 0
    # The judge cost is not the system's: the case's cost was read before judging.
    assert report.cases[0].cost_usd == 0.0
