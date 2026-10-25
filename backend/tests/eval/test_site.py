"""The static report site (`python -m driftline.eval site`).

Builds from the committed, real report files in this repo, and from an empty repo (the
first Pages build, before anything is published). Bench inputs, which are not committed
yet, are written into a temporary repo by the tests themselves and are clearly test data.
"""

import json
import re
import shutil
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from driftline.eval.__main__ import amain
from driftline.eval.site import (
    DEMO_PATH,
    PAGES,
    build_site,
    load_site_data,
    readme_results_table,
)
from driftline.eval.types import EvalReport

REPO = Path(__file__).resolve().parents[3]
CLAUDE_DIR = REPO / "evals" / "reports" / "e0c7cc1faecf51cee1428bd8d7ad76055f3b39b7" / "claude"
GATE_DIR = REPO / "evals" / "reports" / "gate"
README = REPO / "README.md"
ALLOWED_EXTERNAL = ("https://github.com/pranavkrishnadanda/Driftline",)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.srcs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag in ("a", "link") and a.get("href"):
            self.hrefs.append(a["href"])
        if a.get("src"):
            self.srcs.append(a["src"])


def _parse(path: Path) -> _Links:
    p = _Links()
    p.feed(path.read_text())
    return p


def _text(path: Path) -> str:
    """Visible-ish text: tags stripped, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", path.read_text()))


def _copy_real_inputs(dst: Path) -> None:
    for rel in ("evals", "reports/drift-log.md", "reports/drift-latest.json", "docs/screenshots"):
        src = REPO / rel
        if src.is_dir():
            shutil.copytree(src, dst / rel)
        else:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dst / rel)


def _assert_links_valid(out: Path) -> None:
    pages = sorted(out.glob("*.html"))
    assert pages
    ids = {p.name: _parse(p).ids for p in pages}
    for page in pages:
        links = _parse(page)
        for src in links.srcs:
            assert not urlsplit(src).scheme, f"{page.name}: external resource {src}"
            assert (out / src).is_file(), f"{page.name}: missing {src}"
        for href in links.hrefs:
            parts = urlsplit(href)
            if parts.scheme:
                assert href.startswith(ALLOWED_EXTERNAL), f"{page.name}: unexpected link {href}"
                continue
            if href == DEMO_PATH:
                continue  # the recorded demo, added under demo/ by the pages workflow
            target = parts.path or page.name
            assert (out / target).is_file(), f"{page.name}: broken link {href}"
            if parts.fragment and target.endswith(".html"):
                assert parts.fragment in ids[target], f"{page.name}: no #{parts.fragment}"


def _fmt(name: str, value: float) -> str:
    if name == "latency_p95_ms":
        return f"{value:.0f}"
    return f"{value:.4f}"


@pytest.fixture(scope="module")
def real_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("site")
    build_site(REPO, out)
    return out


def test_builds_every_page_from_the_committed_reports(real_site: Path) -> None:
    for page in PAGES:
        assert (real_site / page.file).is_file()
    assert (real_site / ".nojekyll").is_file()
    assert (real_site / "assets" / "style.css").is_file()


def test_every_page_links_to_the_live_demo_and_home_features_it(real_site: Path) -> None:
    for page in PAGES:
        assert DEMO_PATH in _parse(real_site / page.file).hrefs, page.file
    home = (real_site / "index.html").read_text()
    assert f'<a class="button" href="{DEMO_PATH}">Live demo</a>' in home


def test_links_and_assets_are_valid_and_nothing_is_fetched_from_the_network(
    real_site: Path,
) -> None:
    _assert_links_valid(real_site)
    for page in real_site.glob("*.html"):
        html = page.read_text()
        assert '<script src="http' not in html
        assert "@import" not in html
    css = (real_site / "assets" / "style.css").read_text()
    assert "url(http" not in css and "@import" not in css


def test_home_headline_numbers_are_the_report_numbers(real_site: Path) -> None:
    text = _text(real_site / "index.html")
    for corpus in ("pharma", "k8s"):
        for system in ("driftline", "plain_rag"):
            report = EvalReport.model_validate_json(
                (CLAUDE_DIR / f"{corpus}.{system}.json").read_text()
            )
            for name in ("citation_precision", "outdated_citation_rate", "latency_p95_ms"):
                assert _fmt(name, report.metrics[name]) in text, (corpus, system, name)
    # Sample size, model, date and cost are stated next to the numbers.
    assert "40 of 150" in text
    assert "claude-sonnet-5-5" in text and "claude-haiku-5-5" in text
    assert "2026-10-25" in text
    total = sum(
        c.cost_usd
        for f in CLAUDE_DIR.glob("*.json")
        for c in EvalReport.model_validate_json(f.read_text()).cases
    )
    assert f"${total:.6f}" == "$3.061530"
    assert "$3.061530" in text


def test_home_states_the_losses(real_site: Path) -> None:
    text = _text(real_site / "index.html")
    assert "pharma-028" in text and "pharma-099" in text  # Driftline's declined cases
    assert "p95 latency" in text and "cost per answer" in text.lower()
    assert "no_retrieval" in text  # a baseline that was not run


def test_evaluation_page_has_both_runs_and_the_trap_breakdown(real_site: Path) -> None:
    text = _text(real_site / "evaluation.html")
    for f in [*CLAUDE_DIR.glob("*.json"), *GATE_DIR.glob("*.json")]:
        report = EvalReport.model_validate_json(f.read_text())
        assert _fmt("citation_precision", report.metrics["citation_precision"]) in text
        assert _fmt("trap_citation_precision", report.metrics["trap_citation_precision"]) in text
    assert "Offline" in text and "Real Claude" in text
    assert "Trap" in text and "Methodology" in text
    assert "13 traps" in text  # strata of the sample, from evals/snapshot/*.jsonl


def test_charts_are_inline_svg_with_text_alternatives(real_site: Path) -> None:
    html = (real_site / "evaluation.html").read_text()
    assert html.count("<svg") >= 2
    assert 'role="img"' in html and "<title" in html


def test_benchmarks_empty_state_when_bench_results_are_absent(real_site: Path) -> None:
    # bench/results/ is not committed yet (the P7 load test publishes it later).
    if load_site_data(REPO).bench is None:
        assert "Benchmarks not yet published" in _text(real_site / "benchmarks.html")


def test_drift_page_is_rendered_from_the_drift_report(real_site: Path) -> None:
    latest = json.loads((REPO / "reports" / "drift-latest.json").read_text())
    text = _text(real_site / "drift.html")
    assert latest["as_of"] in text
    assert f"{latest['totals']['changes']}" in text
    for doc in latest["documents"]:
        assert doc["external_id"] in text


def test_screenshots_are_copied_and_shown(real_site: Path) -> None:
    shots = sorted((REPO / "docs" / "screenshots").glob("*.webp"))
    assert shots
    html = (real_site / "screenshots.html").read_text()
    for shot in shots:
        assert (real_site / "screenshots" / shot.name).is_file()
        assert f"screenshots/{shot.name}" in html
        assert shot.stat().st_size < 300_000
    assert html.count('alt="') >= len(shots)


def test_empty_repo_builds_with_empty_states(tmp_path: Path) -> None:
    repo, out = tmp_path / "repo", tmp_path / "out"
    repo.mkdir()
    build_site(repo, out)
    assert "Benchmarks not yet published" in _text(out / "benchmarks.html")
    assert "not yet published" in _text(out / "index.html")
    assert "not yet published" in _text(out / "evaluation.html")
    assert "No drift report" in _text(out / "drift.html")
    assert "No screenshots" in _text(out / "screenshots.html")
    _assert_links_valid(out)


def test_unreadable_inputs_are_reported_not_crashed_on(tmp_path: Path) -> None:
    repo, out = tmp_path / "repo", tmp_path / "out"
    (repo / "evals" / "reports" / "x").mkdir(parents=True)
    (repo / "evals" / "reports" / "x" / "broken.json").write_text("{not json")
    (repo / "bench" / "results" / "abc").mkdir(parents=True)
    (repo / "bench" / "results" / "abc" / "workers-1.json").write_text("[1, 2")
    (repo / "reports").mkdir()
    (repo / "reports" / "drift-latest.json").write_text("{}")
    build_site(repo, out)
    assert "broken.json" in _text(out / "evaluation.html")
    assert "workers-1.json" in _text(out / "benchmarks.html")
    _assert_links_valid(out)


def test_bench_results_render_charts_chaos_and_machine(tmp_path: Path) -> None:
    """TEST DATA ONLY: written to a temp repo, never to bench/results."""
    repo, out = tmp_path / "repo", tmp_path / "out"
    _copy_real_inputs(repo)
    run = repo / "bench" / "results" / "0123abc"
    run.mkdir(parents=True)
    machine = {"cpu": "test-cpu", "cores": 2}
    for workers, rps, p95 in ((1, 1.25, 900.5), (4, 4.5, 950.25), (8, 7.75, 1100.0)):
        (run / f"workers-{workers}.json").write_text(
            json.dumps(
                {
                    "workers": workers,
                    "llm": "stub LLM",
                    "throughput_rps": rps,
                    "latency_ms": {"p50": 400.0, "p95": p95},
                    "machine": machine,
                }
            )
        )
    (run / "chaos.json").write_text(
        json.dumps(
            {
                "asks": 50,
                "succeeded": 50,
                "stuck": 0,
                "failed": 0,
                "no_answer": 0,
                "dlq": 0,
                "pending": 0,
                "kills": 3,
            }
        )
    )
    build_site(repo, out)
    html = (out / "benchmarks.html").read_text()
    text = _text(out / "benchmarks.html")
    assert "Benchmarks not yet published" not in text
    assert html.count("<svg") >= 2
    for value in ("1.25", "7.75", "1100", "test-cpu", "stub LLM", "0123abc"):
        assert value in text, value
    assert "zero lost jobs" in text.lower()
    _assert_links_valid(out)


BENCH_DIR = REPO / "bench" / "results" / "cd66852df1d8"


def test_benchmarks_page_shows_industry_standard_metrics_from_the_committed_results(
    real_site: Path,
) -> None:
    html = (real_site / "benchmarks.html").read_text()
    text = unescape(_text(real_site / "benchmarks.html"))
    for heading in (
        "Latency percentiles",
        "LLM-serving metrics",
        "Errors, success rate, Apdex and concurrency",
        "Scaling efficiency",
        "Saturation and queueing",
        "Metric definitions",
    ):
        assert heading in text, heading
    for path in sorted(BENCH_DIR.glob("workers-*.json")):
        s = json.loads(path.read_text())["summary"]
        lat, ttft = s["latency_ms"], s["ttft_ms"]
        for value in (lat["p90"], lat["p99"], lat["stddev"], ttft["p90"], ttft["p99"]):
            assert f"{value:.0f}" in text, (path.name, value)
        assert f"{s['apdex']['score']:.3f}" in text, path.name
    assert "n/a (n<1000)" in text  # p99.9 is not reported on these sample sizes
    assert "not captured" in text and "TPOT" in text
    assert "Stub LLM" in text and "800 ms median" in text
    assert "OOM-killed: RRF fallback" in text and "reranker off" in text
    assert "Apdex T = 10 s" in text
    assert 'aria-labelledby="scaling-efficiency-by-worker-count-t' in html
    for url in (
        "https://sre.google/sre-book/monitoring-distributed-systems/",
        "https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html",
        "grafana.com/docs/k6",
    ):
        assert url in text, url


def test_bench_files_without_the_new_summary_skip_the_metric_sections(tmp_path: Path) -> None:
    repo, out = tmp_path / "repo", tmp_path / "out"
    run = repo / "bench" / "results" / "0123abc"
    run.mkdir(parents=True)
    (run / "workers-1.json").write_text(json.dumps({"workers": 1, "throughput_rps": 1.0}))
    build_site(repo, out)
    html = (out / "benchmarks.html").read_text()
    assert 'id="percentiles"' not in html and 'id="scaling-efficiency"' not in html
    assert 'id="definitions"' in html
    _assert_links_valid(out)


def test_chaos_with_lost_jobs_is_not_reported_as_zero(tmp_path: Path) -> None:
    repo, out = tmp_path / "repo", tmp_path / "out"
    run = repo / "bench" / "results" / "0123abc"
    run.mkdir(parents=True)
    (run / "chaos.json").write_text(
        json.dumps({"asks": 10, "succeeded": 9, "stuck": 1, "failed": 0, "kills": 1})
    )
    build_site(repo, out)
    text = _text(out / "benchmarks.html").lower()
    assert "zero lost jobs" not in text
    assert "lost or stuck" in text


async def test_cli_builds_the_site(tmp_path: Path) -> None:
    out = tmp_path / "site"
    assert await amain(["site", "--out", str(out), "--repo", str(REPO)]) == 0
    assert (out / "index.html").is_file()


# README cross-checks: every headline number in the README comes from the reports.


def _readme_results_block() -> str:
    text = README.read_text()
    m = re.search(r"<!-- results-table:start -->\n(.*?)<!-- results-table:end -->", text, re.DOTALL)
    assert m, "README has no results table markers"
    return m.group(1)


def test_readme_results_table_is_generated_from_the_reports() -> None:
    data = load_site_data(REPO)
    assert data.headline is not None
    assert _readme_results_block() == readme_results_table(data.headline)


def test_readme_results_table_cells_match_the_report_json() -> None:
    columns = {
        "Citation precision": "citation_precision",
        "Outdated-citation rate": "outdated_citation_rate",
        "Trap precision": "trap_citation_precision",
        "Trap outdated rate": "trap_outdated_citation_rate",
        "Faithfulness (verifier)": "faithfulness",
        "Insufficient-evidence acc.": "insufficient_evidence_accuracy",
        "p95 latency (ms)": "latency_p95_ms",
        "Cost / answer (USD)": "cost_per_answer_usd",
    }
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in _readme_results_block().splitlines()
        if line.startswith("|")
    ]
    header, body = rows[0], rows[2:]
    assert len(body) == 4
    for row in body:
        cells = dict(zip(header, row, strict=True))
        corpus, system = cells["Corpus"], cells["System"].strip("`")
        report = EvalReport.model_validate_json(
            (CLAUDE_DIR / f"{corpus}.{system}.json").read_text()
        )
        assert cells["Cases"] == f"{report.metrics['cases']:.0f}"
        for col, name in columns.items():
            assert cells[col] == _fmt(name, report.metrics[name]), (corpus, system, col)


def test_readme_states_sample_model_cost_and_links() -> None:
    text = README.read_text()
    assert "evals/RESULTS.md" in text
    assert "https://pranavkrishnadanda.github.io/Driftline/" in text
    assert "$3.061530" in text and "claude-sonnet-5-5" in text and "40 of 150" in text
    assert "not yet published" not in text.lower()
    assert "will come with the github pages report" not in text.lower()
    for shot in sorted((REPO / "docs" / "screenshots").glob("*.webp")):
        assert f"docs/screenshots/{shot.name}" in text
