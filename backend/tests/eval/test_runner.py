"""The eval runner on a mini golden set built from real seeded rows: real Postgres, the
real TEI embedder, and the real DeterministicAdapter running the in-repo
ExtractiveResponder for every LLM tier of every system (no reranker: RRF order)."""

import json
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from dbseed import EMBED_MODEL, VersionSeed, embed_all, seed_history, seed_source

from driftline.agents.graph import AgentConfig, AgentDeps
from driftline.agents.llm import AgentLLM
from driftline.agents.offline import ExtractiveResponder
from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.eval.__main__ import amain
from driftline.eval.runner import EvalDeps, render_markdown, report_path, run
from driftline.eval.types import EvalReport, GoldenCase
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.adapters.tei import TEIEmbeddingAdapter
from driftline.llm.router import LLMRouter, Route
from driftline.llm.types import ProviderError
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker

T_OLD, T_NEW = datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 4, 15, tzinfo=UTC)
NOW = datetime(2026, 10, 25, tzinfo=UTC)
OLD_RULE = "Check ALT every 12 weeks during therapy."
NEW_RULE = "Check ALT monthly during therapy."
DOSAGE = "Take 10 mg daily."
SHA = "a1b2c3d"


@pytest.fixture
async def corpus(fresh_conn, embedder_url):
    tenant, source = await seed_source(fresh_conn, kind="openfda", tenant="pharma")
    _, versions, chunks = await seed_history(
        fresh_conn,
        source,
        external_id="lipitor",
        title="Lipitor label",
        versions=[
            VersionSeed(T_OLD, [("Warnings > Liver", OLD_RULE), ("Dosage", DOSAGE)]),
            VersionSeed(T_NEW, [("Warnings > Liver", NEW_RULE), ("Dosage", DOSAGE)]),
        ],
    )
    await embed_all(fresh_conn, embedder_url)
    return {"tenant": tenant, "versions": versions, "chunks": chunks}


def golden_set(versions: list[UUID]) -> list[GoldenCase]:
    """Five cases tied to the seeded versions and their exact text."""
    old_v, new_v = versions

    def case(n: int, **fields) -> GoldenCase:
        base = {"id": f"pharma-{n:03d}", "corpus": "pharma", "kind": "point_in_time"}
        return GoldenCase(**(base | fields))

    return [
        case(
            1,
            question="How often should ALT be checked as of 2023-06-01?",
            as_of=date(2023, 6, 1),
            expected_answer="Every 12 weeks during therapy.",
            expected_version_ids=[old_v],
            expected_quotes=[OLD_RULE],
            trap=True,
        ),
        case(
            2,
            kind="current",
            question="How often should ALT be checked?",
            as_of=date(2024, 6, 1),
            expected_answer="Monthly during therapy.",
            expected_version_ids=[new_v],
            expected_quotes=[NEW_RULE],
            trap=True,
        ),
        case(
            3,
            question="What is the daily dose of Lipitor?",
            as_of=date(2024, 6, 1),
            expected_answer="10 mg daily.",
            expected_version_ids=[new_v],
            expected_quotes=[DOSAGE],
            trap=False,
        ),
        case(
            4,
            kind="not_in_corpus",
            question="What is the maximum aspirin dose for children?",
            as_of=date(2024, 6, 1),
            expected_answer="insufficient evidence",
            expected_version_ids=[],
            expected_quotes=[],
            trap=False,
        ),
        stale_case(5, old_v),
    ]


def stale_case(n: int, real_version: UUID) -> GoldenCase:
    """One of its expected versions is gone (e.g. after a re-ingest)."""
    return GoldenCase(
        id=f"pharma-{n:03d}",
        corpus="pharma",
        kind="point_in_time",
        question="How often should ALT be checked in 2023?",
        as_of=date(2023, 6, 1),
        expected_answer="Every 12 weeks during therapy.",
        expected_version_ids=[real_version, uuid4()],
        expected_quotes=[OLD_RULE],
        trap=True,
    )


@pytest.fixture
def make_deps(fresh_pool, embedder_url):
    def make(corpus, *, script=None, **fields) -> tuple[DeterministicAdapter, EvalDeps]:
        det = DeterministicAdapter("det", script=script, responder=ExtractiveResponder())
        tiers = {t: [Route("det", f"det-{t}")] for t in ("extract", "answer", "judge")}
        router = LLMRouter(
            providers={"det": det, "tei": TEIEmbeddingAdapter(embedder_url)},
            chains={**tiers, "embed": [Route("tei", EMBED_MODEL)]},
            clock=ManualClock(),
        )
        agent = AgentDeps(
            pool=fresh_pool,
            llm=AgentLLM(router, ledger=CostLedger(fresh_pool)),
            retriever=HybridRetriever(fresh_pool, router, embed_model=EMBED_MODEL),
            reranker=TEIReranker(None),
            clock=ManualClock(NOW.timestamp()),
            config=AgentConfig(),
        )
        deps = EvalDeps(
            agent=agent, tenant_id=corpus["tenant"], git_sha=SHA, timer=ManualClock(), **fields
        )
        return det, deps

    return make


def by_id(report: EvalReport) -> dict:
    return {c.case_id: c for c in report.cases}


async def test_driftline_beats_plain_rag_on_outdated_citations_for_trap_questions(
    corpus, make_deps
):
    old_v, new_v = corpus["versions"]
    cases = golden_set(corpus["versions"])
    _, deps = make_deps(corpus)
    driftline = await run("pharma", "driftline", cases, deps)
    _, deps = make_deps(corpus)
    plain = await run("pharma", "plain_rag", cases, deps)

    # Trap 1 (dated before the change): the full graph cites only the old version, the
    # unfiltered baseline also cites the version that came later.
    trap_dl, trap_rag = by_id(driftline)["pharma-001"], by_id(plain)["pharma-001"]
    assert trap_dl.cited_version_ids == [old_v]
    assert trap_dl.scores["outdated_citation_rate"] == 0.0
    assert trap_dl.scores["citation_precision"] == 1.0
    assert new_v in trap_rag.cited_version_ids
    assert trap_rag.scores["outdated_citation_rate"] > 0.0
    assert by_id(driftline)["pharma-002"].cited_version_ids == [new_v]

    assert driftline.metrics["trap_outdated_citation_rate"] == 0.0
    assert plain.metrics["trap_outdated_citation_rate"] > 0.0
    assert driftline.metrics["outdated_citation_rate"] < plain.metrics["outdated_citation_rate"]
    assert driftline.metrics["citation_precision"] == 1.0
    assert driftline.metrics["citation_precision"] > plain.metrics["citation_precision"]
    assert driftline.metrics["faithfulness"] == 1.0
    assert plain.metrics["faithfulness"] < 1.0  # its outdated claims fail the verifier
    # The not_in_corpus case: both abstain; every other case is answered by both.
    for report in (driftline, plain):
        assert by_id(report)["pharma-004"].answer_status == "insufficient_evidence"
        assert report.metrics["insufficient_evidence_accuracy"] == 1.0
        assert report.metrics["cost_per_answer_usd"] == 0.0  # the deterministic models are free
        assert report.metrics["latency_p95_ms"] == 0.0  # a ManualClock timer
        assert (report.corpus, report.git_sha) == ("pharma", SHA)


async def test_stale_case_is_excluded_from_metrics_and_counted(corpus, make_deps):
    cases = golden_set(corpus["versions"])
    det, deps = make_deps(corpus)
    with_stale = await run("pharma", "driftline", cases, deps)
    stale = by_id(with_stale)["pharma-005"]
    assert stale.status == "stale_case" and not stale.scores
    assert "not in the database" in stale.error
    assert with_stale.stale_case_count == 1
    assert with_stale.metrics["stale_case_count"] == 1.0
    assert with_stale.metrics["cases"] == 5.0 and with_stale.metrics["scored"] == 4.0
    calls_with_stale = len(det.calls)

    det, deps = make_deps(corpus)
    without = await run("pharma", "driftline", cases[:4], deps)
    assert len(det.calls) == calls_with_stale  # the stale case never reached a model
    counts = {"cases", "stale_case_count"}
    assert {k: v for k, v in with_stale.metrics.items() if k not in counts} == {
        k: v for k, v in without.metrics.items() if k not in counts
    }
    assert without.metrics["stale_case_count"] == 0.0


async def test_no_retrieval_baseline_uses_the_llm_alone(corpus, make_deps):
    det, deps = make_deps(corpus)
    report = await run("pharma", "no_retrieval", golden_set(corpus["versions"]), deps)
    assert det.calls == ["det-answer"] * 4  # one closed-book call per non-stale case
    assert all(not c.cited_version_ids for c in report.cases)
    assert "citation_precision" not in report.metrics  # nothing was cited
    # The offline responder has no knowledge of its own: it abstains every time, which
    # is only right for the not_in_corpus case.
    assert report.metrics["insufficient_evidence_accuracy"] == 0.25


async def test_judge_sample_scores_faithfulness_with_the_judge_tier(corpus, make_deps):
    det, deps = make_deps(corpus, judge_sample=2)
    report = await run("pharma", "plain_rag", golden_set(corpus["versions"]), deps)
    assert det.calls.count("det-judge") == 2
    assert report.metrics["faithfulness_judge"] == 1.0  # the offline judge: word overlap
    assert report.metrics["claims_judged"] == 2.0


async def test_writes_eval_runs_and_json_and_markdown_reports(
    corpus, make_deps, fresh_conn, tmp_path
):
    _, deps = make_deps(corpus, reports_dir=tmp_path)
    report = await run("pharma", "driftline", golden_set(corpus["versions"]), deps)

    path = report_path(tmp_path, SHA, "pharma", "driftline")
    assert path == tmp_path / SHA / "pharma.driftline.json"
    assert EvalReport.model_validate_json(path.read_text()) == report
    markdown = path.with_suffix(".md").read_text()
    assert markdown == render_markdown(report)
    assert "citation_precision" in markdown and "pharma-005" in markdown
    assert "stale_case" in markdown

    row = await fresh_conn.fetchrow("SELECT git_sha, corpus, metrics FROM eval_runs")
    assert (row["git_sha"], row["corpus"]) == (SHA, "pharma")
    assert json.loads(row["metrics"]) == {"system": "driftline", "metrics": report.metrics}
    jobs = await fresh_conn.fetch("SELECT kind, status FROM jobs")
    assert {(j["kind"], j["status"]) for j in jobs} == {("eval", "succeeded")}


async def test_a_system_failure_is_an_error_case_never_a_score(corpus, make_deps, fresh_conn):
    outage = ProviderError("bad gateway", retryable=False, status=400)
    _, deps = make_deps(corpus, script=[outage])
    report = await run("pharma", "no_retrieval", golden_set(corpus["versions"])[:2], deps)
    failed, answered = report.cases
    assert failed.status == "error" and failed.error and not failed.scores
    assert answered.status == "scored"
    assert report.metrics["error_count"] == 1.0 and report.metrics["scored"] == 1.0
    jobs = await fresh_conn.fetch("SELECT status, error FROM jobs ORDER BY created_at")
    assert sorted(j["status"] for j in jobs) == ["failed", "succeeded"]


async def test_rejects_cases_of_another_corpus_and_unknown_systems(corpus, make_deps):
    _, deps = make_deps(corpus)
    cases = golden_set(corpus["versions"])
    with pytest.raises(ValueError, match="corpus"):
        await run("k8s", "driftline", cases, deps)
    with pytest.raises(ValueError, match="system"):
        await run("pharma", "gpt_only", cases, deps)


async def test_cli_run_evaluates_a_cases_file_offline(
    corpus, fresh_dsn, redis_url, embedder_url, tmp_path
):
    cases_file = tmp_path / "pharma.jsonl"
    cases_file.write_text(
        "\n".join(c.model_dump_json() for c in golden_set(corpus["versions"])) + "\n"
    )
    settings = Settings(
        _env_file=None,
        database_url=fresh_dsn,
        redis_url=redis_url,
        embed_url=embedder_url,
        rerank_url=None,
        llm_offline=True,
        semantic_cache_enabled=False,
    )
    reports = tmp_path / "reports"
    code = await amain(
        [
            "run",
            "--corpus",
            "pharma",
            "--system",
            "plain_rag",
            "--cases",
            str(cases_file),
            "--reports-dir",
            str(reports),
            "--git-sha",
            SHA,
        ],
        settings,
    )
    assert code == 0
    report = EvalReport.model_validate_json((reports / SHA / "pharma.plain_rag.json").read_text())
    assert report.stale_case_count == 1 and report.metrics["scored"] == 4.0
