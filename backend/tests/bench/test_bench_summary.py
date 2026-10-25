"""The bench summariser: k6 NDJSON (`k6 run --out json=...`) -> latency percentiles,
throughput, error and 429 rates, and the results README.

`fixtures/k6-ask-sample.ndjson.gz` is a real recording: bench/k6/ask.js run against the
bench Compose stack (stub LLM), not hand-written."""

import gzip
import json
import statistics
from pathlib import Path

import pytest

from driftline.bench.summarize import (
    percentile,
    render_readme,
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
    rows = [line for line in md.splitlines() if line.startswith(("| 1 ", "| 4 "))]
    assert [r.split("|")[1].strip() for r in rows] == ["1", "4"]  # sorted by workers
    assert "12.5%" in rows[0] and "9000" in rows[0]
    assert "Apple M2" in md


def test_readme_without_ingest_or_chaos_says_not_run():
    md = render_readme(sha="abc", runs=[], machine={}, ingest=None, chaos=None)
    assert md.count("not run") >= 2
