"""The bench summariser: k6 NDJSON (`k6 run --out json=...`) -> latency percentiles,
throughput, error and 429 rates, and the results README.

`fixtures/k6-ask-sample.ndjson.gz` is a real recording: bench/k6/ask.js run against the
bench Compose stack (stub LLM), not hand-written."""

import gzip
import json
import shutil
import statistics
from pathlib import Path

import pytest

from driftline.bench.__main__ import main
from driftline.bench.summarize import (
    percentile,
    queueing,
    render_readme,
    saturation,
    scaling_efficiency,
    summarize_k6,
    summarize_k6_file,
)

FIXTURE = Path(__file__).parent / "fixtures" / "k6-ask-sample.ndjson.gz"


def point(metric: str, value: float, t: str, **tags: str) -> str:
    return json.dumps(
        {"type": "Point", "metric": metric, "data": {"time": t, "value": value, "tags": tags}}
    )


def test_percentile_interpolates_linearly():
    assert percentile([10.0], 0.95) == 10.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert percentile([0.0, 100.0], 0.95) == pytest.approx(95.0)
    assert percentile([5.0, 1.0, 3.0], 0.0) == 1.0  # sorts its input
    assert percentile([], 0.5) is None


def test_summary_counts_outcomes_and_rates():
    lines = [
        json.dumps({"type": "Metric", "metric": "ask_latency", "data": {"type": "trend"}}),
        point("http_reqs", 1, "2026-10-25T10:00:00.000000000Z", name="POST /v1/ask"),
        point("ask_latency", 1000, "2026-10-25T10:00:01Z"),
        point("ask_ttft", 400, "2026-10-25T10:00:01Z"),
        point("ask_completed", 1, "2026-10-25T10:00:01Z"),
        point("ask_latency", 3000, "2026-10-25T10:00:05Z"),
        point("ask_completed", 1, "2026-10-25T10:00:05Z"),
        point("ask_rejected", 1, "2026-10-25T10:00:06Z"),
        point("ask_failed", 1, "2026-10-25T10:00:10Z", stage="events"),
        "",
    ]
    s = summarize_k6(lines)
    assert s["window_s"] == pytest.approx(10.0)
    assert (s["completed"], s["rejected_429"], s["failed"], s["attempts"]) == (2, 1, 1, 4)
    assert s["throughput_per_s"] == pytest.approx(0.2)
    assert s["rate_429"] == pytest.approx(0.25) and s["error_rate"] == pytest.approx(0.25)
    assert s["latency_ms"]["p50"] == pytest.approx(2000.0)
    assert s["latency_ms"]["count"] == 2 and s["latency_ms"]["max"] == 3000.0
    assert s["ttft_ms"]["p50"] == 400.0 and s["ttft_ms"]["count"] == 1


def test_summary_of_no_samples_is_empty_not_a_crash():
    s = summarize_k6([])
    assert s["completed"] == 0 and s["throughput_per_s"] == 0.0
    assert s["latency_ms"]["p95"] is None and s["rate_429"] == 0.0


def _real_points(metric: str) -> list[float]:
    with gzip.open(FIXTURE, "rt") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return [r["data"]["value"] for r in rows if r["type"] == "Point" and r["metric"] == metric]


def test_parses_a_real_recorded_k6_run():
    s = summarize_k6_file(FIXTURE)
    latencies = _real_points("ask_latency")
    assert latencies, "the fixture must hold completed asks"
    assert s["completed"] == len(latencies) == int(sum(_real_points("ask_completed")))
    assert s["rejected_429"] == int(sum(_real_points("ask_rejected")))
    assert s["failed"] == int(sum(_real_points("ask_failed")))
    assert s["latency_ms"]["p50"] == pytest.approx(statistics.median(latencies))
    q = statistics.quantiles(latencies, n=100, method="inclusive")
    assert s["latency_ms"]["p95"] == pytest.approx(q[94])
    assert s["latency_ms"]["p99"] == pytest.approx(q[98])
    assert s["ttft_ms"]["count"] == len(_real_points("ask_ttft"))
    assert 0 < s["ttft_ms"]["p50"] <= s["latency_ms"]["p50"]
    assert s["window_s"] > 0
    assert s["throughput_per_s"] == pytest.approx(s["completed"] / s["window_s"])


def _run(workers: int, p95: float, rate_429: float = 0.0) -> dict:
    return {
        "workers": workers,
        "llm": "stub LLM",
        "config": {"vus": 32, "duration_s": 180, "reranker": "on"},
        "summary": {
            "completed": 100 * workers,
            "attempts": 100 * workers,
            "throughput_per_s": 0.5 * workers,
            "rate_429": rate_429,
            "error_rate": 0.0,
            "latency_ms": {"p50": p95 / 2, "p95": p95, "p99": p95 * 1.2},
            "ttft_ms": {"p50": 900.0, "p95": 1500.0},
        },
        "oom_killed": [],
    }


def test_readme_renders_a_row_per_worker_count_labelled_stub_llm():
    md = render_readme(
        sha="abc1234",
        runs=[_run(4, 5000.0), _run(1, 9000.0, rate_429=0.125)],
        machine={"cpu": "Apple M2", "colima": {"cpus": 4, "memory_gib": 6}},
        ingest=None,
        chaos=None,
    )
    assert "stub LLM" in md and "abc1234" in md
    ask_load = md.split("## Ask load", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in ask_load.splitlines() if line.startswith(("| 1 ", "| 4 "))]
    assert [r.split("|")[1].strip() for r in rows] == ["1", "4"]  # sorted by workers
    assert "12.5%" in rows[0] and "9000" in rows[0]
    assert "Apple M2" in md


def test_readme_without_ingest_or_chaos_says_not_run():
    md = render_readme(sha="abc", runs=[], machine={}, ingest=None, chaos=None)
    assert md.count("not run") >= 2


def test_readme_shows_where_the_time_goes_from_stage_timings_and_container_cpu():
    run = _run(1, 30000.0)
    stage_p50 = {
        "wall": 27000.0,
        "queue": 18000.0,
        "worker": 9000.0,
        "plan": 700.0,
        "retrieve": 4400.0,
        "draft": 900.0,
        "verify": 2700.0,
    }
    run["stages"] = {
        "asks": 28,
        "rerank_ran_share": 1.0,
        **{k: {"p50": v, "p95": v * 2, "mean": v, "n": 28} for k, v in stage_p50.items()},
    }
    run["container_stats_mid_run"] = [
        {"Name": "driftline-bench-reranker-1", "CPUPerc": "215.75%", "MemUsage": "2.25GiB"},
        {"Name": "driftline-bench-agent-worker-1", "CPUPerc": "0.95%", "MemUsage": "226MiB"},
    ]
    run["oom_killed"] = ["driftline-bench-reranker-1"]
    md = render_readme(sha="abc", runs=[run], machine={}, ingest=None, chaos=None)
    assert "## Where the time goes" in md
    row = next(line for line in md.splitlines() if line.startswith("| 1 | 28 "))
    assert all(v in row for v in ("18000", "4400", "2700", "9000", "100.0%"))
    assert "reranker-1 215.75%" in md
    assert "OOM-killed: RRF fallback" in md


# ------------------------------------------------------------------ industry-standard metrics
# Percentile set (k6 default p90/p95, SRE tail p99), error breakdown, Apdex, concurrency,
# the LLM-serving view (TTFT, E2E, and what TPOT/ITL would need), saturation, queueing,
# scaling efficiency, and the resummarise path over the committed results.

RESULTS = Path(__file__).resolve().parents[3] / "bench" / "results" / "cd66852df1d8"


def _real_rows() -> list[dict]:
    with gzip.open(FIXTURE, "rt") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    return [r for r in rows if r["type"] == "Point"]


def test_latency_stats_add_p90_min_stddev_and_p99_9_only_when_n_supports_it():
    s = summarize_k6_file(FIXTURE)
    latencies = _real_points("ask_latency")
    lat = s["latency_ms"]
    deciles = statistics.quantiles(latencies, n=10, method="inclusive")
    assert lat["p90"] == pytest.approx(deciles[8])
    assert lat["min"] == min(latencies) and lat["max"] == max(latencies)
    assert lat["stddev"] == pytest.approx(statistics.stdev(latencies))
    assert lat["count"] == len(latencies) < 1000
    assert lat["p99_9"] is None  # fewer than 1000 samples: not reported
    big = [float(i) for i in range(1, 1001)]
    lines = [point("ask_latency", v, "2026-10-25T10:00:00Z") for v in big]
    assert summarize_k6(lines)["latency_ms"]["p99_9"] == pytest.approx(percentile(big, 0.999))


def test_throughput_goodput_and_success_rate_from_the_real_fixture():
    s = summarize_k6_file(FIXTURE)
    http_reqs = sum(r["data"]["value"] for r in _real_rows() if r["metric"] == "http_reqs")
    assert s["requests_per_s"] == pytest.approx(http_reqs / s["window_s"])
    assert s["goodput_per_s"] == pytest.approx(s["completed"] / s["window_s"])
    assert s["success_rate"] == pytest.approx(s["completed"] / s["attempts"])


def test_error_breakdown_counts_asks_cut_off_by_the_end_of_the_test():
    s = summarize_k6_file(FIXTURE)
    posted = sum(
        1
        for r in _real_rows()
        if r["metric"] == "http_reqs"
        and r["data"]["tags"].get("name") == "POST /v1/ask"
        and r["data"]["tags"].get("status") == "202"
    )
    e = s["errors"]
    assert (e["http_5xx"], e["http_429"], e["http_timeout_or_network"]) == (0, 0, 0)
    assert e["failed_sse"] == 0 and e["failed_post"] == 0
    # The short recording stops mid-ask: accepted asks that never reached an outcome.
    assert e["interrupted_at_test_end"] == posted - s["completed"] > 0


def test_error_breakdown_by_kind():
    lines = [
        point("http_reqs", 1, "2026-10-25T10:00:00Z", name="POST /v1/ask", status="503"),
        point("http_reqs", 1, "2026-10-25T10:00:01Z", name="POST /v1/ask", status="429"),
        point("http_reqs", 1, "2026-10-25T10:00:02Z", name="POST /v1/ask", status="0"),
        point("http_reqs", 1, "2026-10-25T10:00:03Z", name="POST /v1/ask", status="404"),
        point("ask_rejected", 1, "2026-10-25T10:00:01Z"),
        point("ask_failed", 1, "2026-10-25T10:00:00Z", stage="post", status="503"),
        point("ask_failed", 1, "2026-10-25T10:00:02Z", stage="post", status="0"),
        point("ask_failed", 1, "2026-10-25T10:00:03Z", stage="post", status="404"),
        point("ask_failed", 1, "2026-10-25T10:00:04Z", stage="events", outcome="stream_ended"),
        point("ask_failed", 1, "2026-10-25T10:00:05Z", stage="events", outcome="error:llm"),
    ]
    e = summarize_k6(lines)["errors"]
    kinds = (e["http_5xx"], e["http_429"], e["http_timeout_or_network"], e["http_4xx_other"])
    assert kinds == (1, 1, 1, 1)
    assert (e["failed_post"], e["failed_sse"]) == (3, 2)
    assert e["failed_by_outcome"] == {"error:llm": 1, "stream_ended": 1}


def test_apdex_counts_satisfied_tolerating_and_failures_as_frustrated():
    t = "2026-10-25T10:00:00Z"
    lines = [
        point("ask_latency", 5_000, t),  # <= T: satisfied
        point("ask_latency", 20_000, t),  # <= 4T: tolerating
        point("ask_latency", 50_000, t),  # > 4T: frustrated
        point("ask_completed", 3, t),
        point("ask_failed", 1, t, stage="events"),  # an error: frustrated
    ]
    a = summarize_k6(lines)["apdex"]
    assert a["t_ms"] == 10_000
    assert (a["satisfied"], a["tolerating"], a["frustrated"], a["samples"]) == (1, 1, 2, 4)
    assert a["score"] == pytest.approx((1 + 0.5) / 4)
    assert summarize_k6([])["apdex"]["score"] is None


def test_concurrency_from_the_real_fixture():
    s = summarize_k6_file(FIXTURE)
    c = s["concurrency"]
    assert c["vus_max"] == max(r["data"]["value"] for r in _real_rows() if r["metric"] == "vus")
    # Little's law over completed asks: mean asks in flight = sum(E2E) / window.
    assert c["in_flight_mean"] == pytest.approx(
        sum(_real_points("ask_latency")) / 1000 / s["window_s"]
    )
    assert 0 < c["in_flight_mean"] <= c["vus_max"]
    # No peak: E2E comes from Date.now() (1 ms steps), so back-to-back asks of one VU can
    # appear to overlap by a millisecond and a sweep would overcount.
    assert "in_flight_peak" not in c


def test_streaming_view_reports_what_was_captured_and_marks_tpot_not_captured():
    s = summarize_k6_file(FIXTURE)
    rows = _real_rows()
    st = s["streaming"]
    finished = {
        r["data"]["tags"]["url"]
        for r in rows
        if r["metric"] == "http_reqs"
        and r["data"]["tags"].get("name") == "GET /v1/jobs/{id}/events"
    }
    per_ask = [
        sum(1 for r in rows if r["metric"] == "sse_event" and r["data"]["tags"]["url"] == u)
        for u in finished
    ]
    assert st["sse_events_per_ask"]["count"] == len(finished) == s["completed"]
    assert st["sse_events_per_ask"]["p50"] == pytest.approx(statistics.median(per_ask))
    total_sse = sum(1 for r in rows if r["metric"] == "sse_event")
    assert st["sse_events_per_s"] == pytest.approx(total_sse / s["window_s"])
    lat, ttft = _real_points("ask_latency"), _real_points("ask_ttft")
    assert st["first_token_to_final_mean_ms"] == pytest.approx(
        statistics.fmean(lat) - statistics.fmean(ttft)
    )
    for key in ("tpot_ms", "itl_ms", "output_tokens_per_s"):
        assert st[key] is None
    assert "not captured in this run" in st["not_captured"]


def test_saturation_parses_the_docker_stats_snapshot():
    stats = [
        {
            "Name": "driftline-bench-reranker-1",
            "CPUPerc": "215.75%",
            "MemUsage": "2.171GiB / 3GiB",
            "MemPerc": "72.38%",
        },
        {
            "Name": "driftline-bench-redis-1",
            "CPUPerc": "0.78%",
            "MemUsage": "11.88MiB / 5.772GiB",
            "MemPerc": "0.20%",
        },
    ]
    sat = saturation(stats, vm_cpus=4)
    rr = sat["containers"][0]
    assert rr["name"] == "reranker-1" and rr["cpu_percent"] == 215.75
    assert rr["mem_mib"] == pytest.approx(2.171 * 1024) and rr["mem_limit_mib"] == 3072
    assert rr["mem_percent"] == 72.38
    assert sat["cpu_percent_sum"] == pytest.approx(216.53)
    assert sat["vm_cpu_utilisation"] == pytest.approx(216.53 / 400)
    assert sat["mem_mib_sum"] == pytest.approx(2.171 * 1024 + 11.88)
    assert saturation([], vm_cpus=4) is None


def test_queueing_share_from_stage_timings():
    q = queueing(
        {
            "asks": 29,
            "queue": {"p50": 20945.6, "p95": 24150.4, "mean": 19762.1, "n": 29},
            "worker": {"p50": 6920.9, "p95": 9043.1, "mean": 7015.3, "n": 29},
            "wall": {"p50": 27745.9, "p95": 31087.3, "mean": 26777.4, "n": 29},
        }
    )
    assert q["queue_p50_ms"] == 20945.6 and q["worker_p95_ms"] == 9043.1
    assert q["queue_share_of_wall"] == pytest.approx(19762.1 / 26777.4)
    assert queueing({}) is None


def test_scaling_efficiency_is_per_reranker_mode_against_its_own_one_worker_run():
    runs = [_run(1, 9000.0), _run(4, 5000.0), _run(8, 4000.0)]
    runs[2]["oom_killed"] = ["driftline-bench-reranker-1"]
    rrf = _run(1, 9000.0)
    rrf["config"]["reranker"] = "off"
    rrf["summary"]["throughput_per_s"] = 0.2
    eff = {(r["reranker"], r["workers"]): r for r in scaling_efficiency([*runs, rrf])}
    assert eff[("on", 1)]["efficiency"] == pytest.approx(1.0)
    assert eff[("on", 4)]["efficiency"] == pytest.approx(2.0 / (4 * 0.5))
    assert eff[("on", 8)]["comparable"] is False  # reranker OOM-killed: RRF fallback
    assert eff[("on", 4)]["comparable"] is True
    assert eff[("off", 1)]["efficiency"] == pytest.approx(1.0)


def test_resummarise_recomputes_from_raw_and_keeps_every_old_field(tmp_path: Path):
    run_dir = tmp_path / RESULTS.name
    shutil.copytree(RESULTS, run_dir)
    before = {p.name: json.loads(p.read_text()) for p in RESULTS.glob("workers-*.json")}
    assert before
    assert main(["resummarize", str(run_dir)]) == 0
    for name, old in before.items():
        new = json.loads((run_dir / name).read_text())
        for key, value in old["summary"].items():
            if isinstance(value, dict):
                for k, v in value.items():
                    assert new["summary"][key][k] == pytest.approx(v), (name, key, k)
            else:
                assert new["summary"][key] == pytest.approx(value), (name, key)
        assert {k for k in old if k != "summary"} <= set(new)
        assert new["summary"]["latency_ms"]["p90"] is not None
        assert "apdex" in new["summary"] and "errors" in new["summary"]
        assert new["saturation"]["containers"] and new["queueing"]["queue_p50_ms"] > 0
    md = (run_dir / "README.md").read_text()
    for heading in (
        "## Latency percentiles",
        "## LLM-serving view",
        "## Errors, success rate and Apdex",
        "## Scaling efficiency",
        "## Saturation",
        "## Metric definitions",
    ):
        assert heading in md, heading
    assert "not captured in this run" in md
    assert "OOM-killed: RRF fallback" in md
    assert "800 ms" in md and "stub" in md.lower()
