"""Summarise k6 bench runs and render `bench/results/<sha>/README.md`.

Input is k6's NDJSON output (`k6 run --out json=raw.ndjson`, optionally gzipped): one
`Point` line per sample. `bench/k6/ask.js` emits the samples read here:

- `ask_latency` (ms, POST sent -> `final` received) and `ask_ttft` (ms, -> first token);
- the counters `ask_completed`, `ask_rejected` (HTTP 429 backpressure) and `ask_failed`
  (tagged `stage` = post | events, and `status` / `outcome`);
- k6's built-ins: `http_reqs` (tagged `name` and `status`), `http_req_failed`, `vus`, and
  xk6-sse's `sse_event` (one point per SSE event received, tagged with the stream `url`,
  but **not** with the event's name, so token events cannot be told apart from step,
  claim and final events).

The warm-up is a separate, discarded k6 run (`bench/run.sh`), so every sample in the file
is in the measured window. Percentiles are computed from every raw sample (linear
interpolation, the same as `statistics.quantiles(method="inclusive")` and numpy's default),
not taken from k6's own summary. Throughput is completed asks over the sample window (first
to last sample). Nothing is dropped: 429s and failures are counted in `attempts` and
reported as rates.

Metric definitions, with sources, are in `METRIC_DEFINITIONS` (rendered into the README).
"""

import gzip
import json
import math
import re
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

STUB_LLM = "stub LLM"
QUANTILES = {"p50": 0.50, "p90": 0.90, "p95": 0.95, "p99": 0.99}
# p99.9 is reported only with at least this many samples (fewer, and no sample lies above it).
P99_9_MIN_N = 1000
# Apdex threshold T on end-to-end ask latency. An unloaded ask on this stack takes about
# 4.5 to 7 s inside a worker (stages `worker` p50; the stub LLM's 800 ms median calls plus
# retrieval), so T = 10 s means "answered within about 1.5x to 2x an unloaded ask";
# tolerating is up to 4T = 40 s. Chosen from the service time, not tuned to the results.
APDEX_T_MS = 10_000.0
ASK_POST = "POST /v1/ask"
ASK_EVENTS = "GET /v1/jobs/{id}/events"
NOT_CAPTURED = (
    "TPOT / ITL and output tokens per second: not captured in this run. k6's `sse_event` "
    "samples carry the stream URL but not the event name, so token events cannot be told "
    "apart from step, claim and final events, and no output-token count was recorded. "
    "Needed: in bench/k6/ask.js, timestamp every `token` event (a Trend of gaps between "
    "consecutive tokens = ITL; (last token - first token) / (tokens - 1) per ask = TPOT) "
    "and count tokens per ask (a Counter, for output tokens/s). With the stub LLM these "
    "would measure the stub's sleeps (800 ms median per call, 70% of it spread evenly over "
    "the words of the reply), not Claude."
)

Summary = dict[str, Any]


def percentile(values: Sequence[float], q: float) -> float | None:
    """The q-quantile (0..1) by linear interpolation between closest ranks; None if empty."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
    out: dict[str, float | int | None] = {k: percentile(values, q) for k, q in QUANTILES.items()}
    out["p99_9"] = percentile(values, 0.999) if len(values) >= P99_9_MIN_N else None
    out["min"] = min(values) if values else None
    out["mean"] = sum(values) / len(values) if values else None
    out["max"] = max(values) if values else None
    out["stddev"] = statistics.stdev(values) if len(values) >= 2 else None
    out["count"] = len(values)
    return out


def _rate(n: float, d: float) -> float:
    return n / d if d else 0.0


def _apdex(latencies: Sequence[float], errors: int) -> dict[str, Any]:
    satisfied = sum(1 for v in latencies if v <= APDEX_T_MS)
    tolerating = sum(1 for v in latencies if APDEX_T_MS < v <= 4 * APDEX_T_MS)
    frustrated = len(latencies) - satisfied - tolerating + errors
    samples = len(latencies) + errors
    return {
        "t_ms": APDEX_T_MS,
        "satisfied": satisfied,
        "tolerating": tolerating,
        "frustrated": frustrated,
        "samples": samples,
        "score": (satisfied + tolerating / 2) / samples if samples else None,
    }


def summarize_k6(lines: Iterable[str]) -> Summary:
    samples: dict[str, list[float]] = {}
    first: datetime | None = None
    last: datetime | None = None
    http_status: Counter[tuple[str, str]] = Counter()
    failed_by_stage: Counter[str] = Counter()
    failed_by_outcome: Counter[str] = Counter()
    sse_by_url: Counter[str] = Counter()
    finished_streams: set[str] = set()
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") != "Point":
            continue
        data, metric = row["data"], row["metric"]
        tags = data.get("tags") or {}
        t = datetime.fromisoformat(data["time"])
        first = t if first is None or t < first else first
        last = t if last is None or t > last else last
        value = float(data["value"])
        samples.setdefault(metric, []).append(value)
        if metric == "http_reqs":
            http_status[(tags.get("name", ""), str(tags.get("status", "")))] += int(value)
            if tags.get("name") == ASK_EVENTS and "url" in tags:
                finished_streams.add(tags["url"])
        elif metric == "ask_failed":
            failed_by_stage[tags.get("stage", "unknown")] += int(value)
            if "outcome" in tags:
                failed_by_outcome[tags["outcome"]] += int(value)
        elif metric == "sse_event":
            sse_by_url[tags.get("url", "")] += int(value)

    completed = int(sum(samples.get("ask_completed", [])))
    rejected = int(sum(samples.get("ask_rejected", [])))
    failed = int(sum(samples.get("ask_failed", [])))
    attempts = completed + rejected + failed
    window_s = (last - first).total_seconds() if first and last else 0.0
    latencies = samples.get("ask_latency", [])
    ttfts = samples.get("ask_ttft", [])

    post_status = Counter({s: n for (name, s), n in http_status.items() if name == ASK_POST})
    errors = {
        "http_5xx": sum(n for s, n in post_status.items() if s.startswith("5")),
        "http_429": post_status.get("429", 0),
        "http_4xx_other": sum(
            n for s, n in post_status.items() if s.startswith("4") and s != "429"
        ),
        "http_timeout_or_network": post_status.get("0", 0),
        "failed_post": failed_by_stage.get("post", 0),
        "failed_sse": failed_by_stage.get("events", 0),
        "failed_by_outcome": dict(sorted(failed_by_outcome.items())),
        # Accepted (202) asks with no outcome: k6 stopped the iteration at the end of the
        # test (gracefulStop). Not failures, and not in `attempts`.
        "interrupted_at_test_end": max(
            0, post_status.get("202", 0) - completed - failed_by_stage.get("events", 0)
        ),
    }
    per_ask_events = [float(sse_by_url[u]) for u in finished_streams]
    return {
        "window_s": window_s,
        "attempts": attempts,
        "completed": completed,
        "rejected_429": rejected,
        "failed": failed,
        "throughput_per_s": _rate(completed, window_s),
        "rate_429": _rate(rejected, attempts),
        "error_rate": _rate(failed, attempts),
        "latency_ms": _stats(latencies),
        "ttft_ms": _stats(ttfts),
        "http_reqs": int(sum(samples.get("http_reqs", []))),
        # Added: industry-standard views of the same samples.
        "requests_per_s": _rate(sum(samples.get("http_reqs", [])), window_s),
        "attempts_per_s": _rate(attempts, window_s),
        "goodput_per_s": _rate(completed, window_s),
        "success_rate": _rate(completed, attempts) if attempts else None,
        "http_req_failed_rate": (
            statistics.fmean(samples["http_req_failed"]) if samples.get("http_req_failed") else None
        ),
        "errors": errors,
        "apdex": _apdex(latencies, failed + rejected),
        "concurrency": {
            "vus_max": int(max(samples.get("vus", [0]))),
            "in_flight_mean": _rate(sum(latencies) / 1000, window_s),
        },
        "streaming": {
            "sse_events_per_ask": _stats(per_ask_events),
            "sse_events_per_s": _rate(sum(sse_by_url.values()), window_s),
            "first_token_to_final_mean_ms": (
                statistics.fmean(latencies) - statistics.fmean(ttfts)
                if latencies and ttfts
                else None
            ),
            "tpot_ms": None,
            "itl_ms": None,
            "output_tokens_per_s": None,
            "not_captured": NOT_CAPTURED,
        },
    }


def summarize_k6_file(path: Path | str) -> Summary:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return summarize_k6(fh)


# ------------------------------------------------------------------ per-run derived metrics

_UNITS = {"b": 1 / 2**20, "kib": 1 / 1024, "kb": 1 / 1024, "mib": 1.0, "mb": 1.0}
_UNITS |= {"gib": 1024.0, "gb": 1024.0}


def _mib(text: str) -> float | None:
    m = re.match(r"\s*([0-9.]+)\s*([a-zA-Z]+)", text)
    if not m or m.group(2).lower() not in _UNITS:
        return None
    return float(m.group(1)) * _UNITS[m.group(2).lower()]


def _percent(text: Any) -> float | None:
    try:
        return float(str(text).strip().rstrip("%"))
    except ValueError:
        return None


def saturation(stats: Sequence[dict[str, Any]], vm_cpus: int | None) -> dict[str, Any] | None:
    """CPU and memory per container from one mid-run `docker stats` snapshot."""
    if not stats:
        return None
    containers = []
    for e in stats:
        used, _, limit = str(e.get("MemUsage", "")).partition("/")
        containers.append(
            {
                "name": str(e.get("Name", "")).removeprefix("driftline-bench-"),
                "cpu_percent": _percent(e.get("CPUPerc")),
                "mem_mib": _mib(used),
                "mem_limit_mib": _mib(limit),
                "mem_percent": _percent(e.get("MemPerc")),
            }
        )
    cpu_sum = sum(c["cpu_percent"] or 0.0 for c in containers)
    return {
        "source": "one `docker stats --no-stream` snapshot at the middle of the run",
        "containers": containers,
        "cpu_percent_sum": cpu_sum,
        "vm_cpus": vm_cpus,
        "vm_cpu_utilisation": cpu_sum / (100 * vm_cpus) if vm_cpus else None,
        "mem_mib_sum": sum(c["mem_mib"] or 0.0 for c in containers),
    }


def queueing(stages: dict[str, Any]) -> dict[str, Any] | None:
    """Time waiting for a worker vs time in the worker (bench/stages.py, server side)."""
    if not stages.get("asks") or not all(k in stages for k in ("queue", "worker", "wall")):
        return None
    q, w, wall = stages["queue"], stages["worker"], stages["wall"]
    return {
        "asks": stages["asks"],
        "queue_p50_ms": q.get("p50"),
        "queue_p95_ms": q.get("p95"),
        "worker_p50_ms": w.get("p50"),
        "worker_p95_ms": w.get("p95"),
        "queue_share_of_wall": (
            q["mean"] / wall["mean"] if q.get("mean") is not None and wall.get("mean") else None
        ),
    }


def _reranker_oom(run: dict[str, Any]) -> bool:
    return any("reranker" in name for name in run.get("oom_killed") or [])


def scaling_efficiency(runs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """throughput(N) / (N x throughput(1)), per reranker mode, against that mode's own
    1-worker run. A run whose reranker was OOM-killed is not comparable (RRF fallback)."""
    base = {
        r.get("config", {}).get("reranker", "on"): r
        for r in runs
        if r["workers"] == 1 and not _reranker_oom(r)
    }
    out = []
    for r in sorted(runs, key=_run_key):
        mode = r.get("config", {}).get("reranker", "on")
        one = base.get(mode)
        thr = r["summary"]["throughput_per_s"]
        thr1 = one["summary"]["throughput_per_s"] if one else None
        out.append(
            {
                "workers": r["workers"],
                "reranker": mode,
                "throughput_per_s": thr,
                "speedup": thr / thr1 if thr1 else None,
                "efficiency": thr / (r["workers"] * thr1) if thr1 else None,
                "comparable": one is not None and not _reranker_oom(r),
            }
        )
    return out


# ------------------------------------------------------------------ README

METRIC_DEFINITIONS = (
    (
        "Latency percentiles (p50, p90, p95, p99, p99.9), min, mean, max, stddev",
        (
            "Linear interpolation between closest ranks over every raw k6 sample. p90 and p95 "
            "are k6's default summary stats (`avg,min,med,max,p(90),p(95)`); p99 is the tail "
            "vLLM reports by default. p99.9 is shown only with at least 1000 samples; with "
            "fewer than 100 samples p99 is an interpolation between the two largest. stddev "
            "is the sample standard deviation."
        ),
        "https://grafana.com/docs/k6/latest/using-k6/k6-options/reference/#summary-trend-stats",
    ),
    (
        "Golden signals: latency, traffic, errors, saturation",
        (
            "Latency of successful and failed requests kept apart; traffic as requests per "
            "second; errors as the rate of failed requests; saturation as how full the service "
            "is (here CPU and memory per container)."
        ),
        "https://sre.google/sre-book/monitoring-distributed-systems/",
    ),
    (
        "Throughput, requests/s, goodput",
        (
            "Asks/s = completed asks / window (first to last k6 sample), as GenAI-Perf/AIPerf "
            "define RPS. HTTP requests/s counts k6's `http_reqs` (POST plus the SSE GET). "
            "Goodput here is successful asks/s; vLLM defines goodput against per-request SLOs "
            "(`--goodput ttft:..,e2el:..`), and no SLO was set for these runs."
        ),
        "https://docs.nvidia.com/nim/benchmarking/llm/latest/metrics.html",
    ),
    (
        "Error and success rate",
        (
            "error rate = failed / attempts, 429 rate = rejected / attempts, success rate = "
            "completed / attempts; broken down by HTTP 5xx, 429, other 4xx, status 0 (timeout or "
            "network) and failed SSE streams. `http_req_failed` is k6's built-in rate over the "
            "POSTs. Asks still running when k6 stopped are reported apart, not as errors."
        ),
        "https://grafana.com/docs/k6/latest/using-k6/metrics/reference/",
    ),
    (
        "TTFT, E2E latency, TPOT/ITL, output tokens/s",
        (
            "TTFT: request sent to first token. E2E: request sent to the full response. "
            "TPOT/ITL: (E2E - TTFT) / (output tokens - 1). Output tokens/s: output tokens / "
            "duration (aggregate) or per request. MLPerf Inference bounds TTFT and TPOT in its "
            "LLM Server scenario."
        ),
        "https://raw.githubusercontent.com/vllm-project/vllm/main/vllm/benchmarks/serve.py",
    ),
    (
        "Apdex",
        (
            "(satisfied + tolerating / 2) / samples; satisfied <= T, tolerating <= 4T, "
            "frustrated > 4T or an error. T = 10 s on E2E ask latency (see above)."
        ),
        "https://docs.newrelic.com/docs/apm/new-relic-apm/apdex/apdex-measure-user-satisfaction/",
    ),
    (
        "Scaling efficiency",
        (
            "throughput(N) / (N x throughput(1)): speedup divided by the number of workers "
            "(parallel efficiency), per reranker mode."
        ),
        "https://en.wikipedia.org/wiki/Speedup",
    ),
    (
        "Concurrency",
        (
            "VUs: k6's `vus` gauge (closed model, one ask in flight per VU). Mean asks in "
            "flight: sum of E2E latencies / window (Little's law, completed asks). No peak is "
            "reported: E2E is timed with 1 ms `Date.now()` steps, so one VU's back-to-back asks "
            "can appear to overlap and a sweep would overcount."
        ),
        "https://grafana.com/docs/k6/latest/using-k6/metrics/reference/",
    ),
    (
        "MLPerf Inference LLM latency bounds (context)",
        (
            "The datacenter Server scenario for Llama 2 70B constrains TTFT/TPOT (2000 ms/200 ms "
            "conversational, 450 ms/40 ms interactive). Shown for context only: these runs use "
            "a stub LLM."
        ),
        "https://github.com/mlcommons/inference_policies/blob/master/inference_rules.adoc",
    ),
)


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _machine_lines(machine: dict[str, Any]) -> list[str]:
    if not machine:
        return ["Machine info not recorded."]
    return [
        f"- **{key}**: {json.dumps(value) if isinstance(value, dict | list) else value}"
        for key, value in machine.items()
    ]


def _reranker_label(run: dict[str, Any]) -> str:
    """The run's reranker mode; flags a reranker the kernel OOM-killed mid-run, whose
    asks then fell back to RRF order (faster, lower quality)."""
    mode = run.get("config", {}).get("reranker", "n/a")
    if _reranker_oom(run):
        return f"{mode}, **OOM-killed: RRF fallback**"
    return mode


def _run_key(run: dict[str, Any]) -> tuple[bool, int]:
    """Reranker-on rows first, then by worker count."""
    return (run.get("config", {}).get("reranker", "on") != "on", run["workers"])


STAGE_COLUMNS = ("wall", "queue", "worker", "plan", "retrieve", "draft", "verify")


def _cpu(entry: dict[str, Any]) -> float:
    return _percent(entry.get("CPUPerc", "0")) or 0.0


def _where_the_time_goes(runs: Sequence[dict[str, Any]]) -> list[str]:
    """p50 ms per stage (bench/stages.py, from each ask's step events) and the busiest
    containers in the mid-run `docker stats` snapshot."""
    staged = [r for r in sorted(runs, key=_run_key) if r.get("stages", {}).get("asks")]
    if not staged:
        return []
    lines = [
        "",
        "## Where the time goes",
        "",
        (
            "p50 ms per stage over each run's succeeded asks, from the asks' own step events "
            "(`bench/stages.py`). `queue` is time waiting for a free worker (wall - worker); "
            "`retrieve` is query embedding + hybrid search + cross-encoder rerank on TEI (CPU); "
            "`plan`, `draft` and `verify` are stub-LLM calls."
        ),
        "",
        "| workers | asks | reranker | "
        + " | ".join(STAGE_COLUMNS)
        + " | rerank ran | busiest containers (CPU) |",
        "|---|---|---|" + "---|" * len(STAGE_COLUMNS) + "---|---|",
    ]
    for run in staged:
        st = run["stages"]
        cells = [_ms((st.get(k) or {}).get("p50")) for k in STAGE_COLUMNS]
        busiest = sorted(run.get("container_stats_mid_run") or [], key=_cpu, reverse=True)[:3]
        cpu = ", ".join(
            f"{e['Name'].removeprefix('driftline-bench-')} {e['CPUPerc']}" for e in busiest
        )
        lines.append(
            f"| {run['workers']} | {st['asks']} | {_reranker_label(run)} | "
            + " | ".join(cells)
            + f" | {_pct(st.get('rerank_ran_share'))} | {cpu or 'n/a'} |"
        )
    return lines


def _has(run: dict[str, Any], key: str) -> bool:
    return key in run.get("summary", {})


def _percentile_section(runs: Sequence[dict[str, Any]]) -> list[str]:
    rows = [r for r in runs if "p90" in r["summary"].get("latency_ms", {})]
    if not rows:
        return []
    lines = [
        "",
        "## Latency percentiles",
        "",
        (
            "End-to-end ask latency in ms (POST sent -> `final` event), from every raw k6 "
            f"sample. p99.9 needs at least {P99_9_MIN_N} samples and no run has that many; "
            "with n < 100, p99 is interpolated between the two largest samples."
        ),
        "",
        "| workers | reranker | n | min | p50 | p90 | p95 | p99 | p99.9 | max | mean | stddev |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in rows:
        lat = run["summary"]["latency_ms"]
        p999 = _ms(lat["p99_9"]) if lat["p99_9"] is not None else f"n/a (n<{P99_9_MIN_N})"
        lines.append(
            f"| {run['workers']} | {_reranker_label(run)} | {lat['count']} | {_ms(lat['min'])} "
            f"| {_ms(lat['p50'])} | {_ms(lat['p90'])} | {_ms(lat['p95'])} | {_ms(lat['p99'])} "
            f"| {p999} | {_ms(lat['max'])} | {_ms(lat['mean'])} | {_ms(lat['stddev'])} |"
        )
    return lines


def _llm_section(runs: Sequence[dict[str, Any]], median_ms: Any) -> list[str]:
    rows = [r for r in runs if _has(r, "streaming")]
    if not rows:
        return []
    lines = [
        "",
        "## LLM-serving view",
        "",
        (
            f"**Every LLM call here is the {STUB_LLM}** ({median_ms} ms median per call, "
            "log-normal), so TTFT and any per-token figure reflect the stub and Driftline's "
            "pipeline, not Claude. TTFT is measured by the client from POST to the first "
            "`token` event, so it includes queueing, planning and retrieval: tokens stream "
            "only in the `draft` stage."
        ),
        "",
        (
            "| workers | reranker | TTFT p50 | TTFT p90 | TTFT p95 | TTFT p99 | E2E p50 | E2E p95 "
            "| first token -> final, mean | SSE events / ask p50 | SSE events/s | TPOT / ITL "
            "| output tokens/s |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in rows:
        s = run["summary"]
        t, lat, st = s["ttft_ms"], s["latency_ms"], s["streaming"]
        lines.append(
            f"| {run['workers']} | {_reranker_label(run)} | {_ms(t['p50'])} | {_ms(t['p90'])} "
            f"| {_ms(t['p95'])} | {_ms(t['p99'])} | {_ms(lat['p50'])} | {_ms(lat['p95'])} "
            f"| {_ms(st['first_token_to_final_mean_ms'])} "
            f"| {_ms(st['sse_events_per_ask']['p50'])} | {_num(st['sse_events_per_s'], 1)} "
            "| not captured | not captured |"
        )
    lines += [
        "",
        (
            "All times in ms. `first token -> final, mean` is mean E2E minus mean TTFT (exact "
            "by linearity; per-ask pairs are not recoverable from the k6 output). It covers the "
            "rest of `draft` plus the `verify` stage, so it is **not** a decode time. "
            "`SSE events` count every event type (step, token, claim, final), not tokens."
        ),
        "",
        rows[0]["summary"]["streaming"]["not_captured"],
    ]
    return lines


def _errors_section(runs: Sequence[dict[str, Any]]) -> list[str]:
    rows = [r for r in runs if _has(r, "errors")]
    if not rows:
        return []
    t_s = rows[0]["summary"]["apdex"]["t_ms"] / 1000
    lines = [
        "",
        "## Errors, success rate and Apdex",
        "",
        (
            f"Apdex T = {t_s:g} s on E2E latency (tolerating up to {4 * t_s:g} s; failures and "
            "429s count as frustrated). T is about 1.5x to 2x an unloaded ask's in-worker time "
            "(4.5 to 7 s p50 from the stage timings), chosen from the service time, not from "
            "these results. `interrupted` asks were accepted but still running when k6 ended "
            "the test (30 s graceful stop); they are not errors and not in `attempts`."
        ),
        "",
        (
            "| workers | reranker | attempts | completed | success rate | 5xx | 429 "
            "| timeout/network | other 4xx | failed SSE | interrupted | http_req_failed "
            "| Apdex | satisfied / tolerating / frustrated |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in rows:
        s = run["summary"]
        e, a = s["errors"], s["apdex"]
        lines.append(
            f"| {run['workers']} | {_reranker_label(run)} | {s['attempts']} | {s['completed']} "
            f"| {_pct(s['success_rate'])} | {e['http_5xx']} | {e['http_429']} "
            f"| {e['http_timeout_or_network']} | {e['http_4xx_other']} | {e['failed_sse']} "
            f"| {e['interrupted_at_test_end']} | {_pct(s['http_req_failed_rate'])} "
            f"| {_num(a['score'], 3)} | {a['satisfied']} / {a['tolerating']} / "
            f"{a['frustrated']} |"
        )
    return lines


def _throughput_section(runs: Sequence[dict[str, Any]]) -> list[str]:
    rows = [r for r in runs if _has(r, "concurrency")]
    if not rows:
        return []
    lines = [
        "",
        "## Throughput and concurrency",
        "",
        (
            "| workers | reranker | VUs (max) | asks in flight, mean "
            "| HTTP requests/s | asks attempted/s | goodput (successful asks/s) |"
        ),
        "|---|---|---|---|---|---|---|",
    ]
    for run in rows:
        s = run["summary"]
        c = s["concurrency"]
        lines.append(
            f"| {run['workers']} | {_reranker_label(run)} | {c['vus_max']} "
            f"| {_num(c['in_flight_mean'], 1)} "
            f"| {_num(s['requests_per_s'])} | {_num(s['attempts_per_s'])} "
            f"| {_num(s['goodput_per_s'])} |"
        )
    return lines


def _scaling_section(runs: Sequence[dict[str, Any]]) -> list[str]:
    eff = scaling_efficiency(runs)
    if not eff:
        return []
    lines = [
        "",
        "## Scaling efficiency",
        "",
        (
            "throughput(N) / (N x throughput(1)), against the 1-worker run with the same "
            "reranker setting. 1.0 is linear scaling."
        ),
        "",
        "| workers | reranker | asks/s | speedup | efficiency | comparable |",
        "|---|---|---|---|---|---|",
    ]
    by_key = {(r["workers"], r.get("config", {}).get("reranker", "on")): r for r in runs}
    for e in eff:
        run = by_key[(e["workers"], e["reranker"])]
        note = "yes" if e["comparable"] else "**no**: reranker OOM-killed, RRF fallback"
        if not e["comparable"] and not _reranker_oom(run):
            note = "no 1-worker baseline"
        lines.append(
            f"| {e['workers']} | {_reranker_label(run)} | {_num(e['throughput_per_s'])} "
            f"| {_num(e['speedup'])} | {_num(e['efficiency'])} | {note} |"
        )
    return lines


def _saturation_section(runs: Sequence[dict[str, Any]]) -> list[str]:
    rows = [r for r in runs if r.get("saturation")]
    if not rows:
        return []
    lines = [
        "",
        "## Saturation",
        "",
        (
            "From one `docker stats --no-stream` snapshot taken half-way through each run (a "
            "point sample, not a time series). VM CPU is the sum of container CPU% over "
            "100% x the VM's vCPUs."
        ),
        "",
        "| workers | reranker | VM CPU | memory, all containers (MiB) | top CPU | top memory |",
        "|---|---|---|---|---|---|",
    ]
    for run in rows:
        sat = run["saturation"]
        cs = sat["containers"]
        top_cpu = sorted(cs, key=lambda c: c["cpu_percent"] or 0.0, reverse=True)[:3]
        top_mem = sorted(cs, key=lambda c: c["mem_mib"] or 0.0, reverse=True)[:3]
        cpu = ", ".join(f"{c['name']} {_num(c['cpu_percent'])}%" for c in top_cpu)
        mem = ", ".join(
            f"{c['name']} {_ms(c['mem_mib'])} MiB ({_num(c['mem_percent'], 1)}% of "
            f"{_ms(c['mem_limit_mib'])})"
            for c in top_mem
        )
        lines.append(
            f"| {run['workers']} | {_reranker_label(run)} | {_pct(sat['vm_cpu_utilisation'])} "
            f"| {_ms(sat['mem_mib_sum'])} | {cpu} | {mem} |"
        )
    return lines


def _queueing_section(runs: Sequence[dict[str, Any]]) -> list[str]:
    rows = [r for r in runs if r.get("queueing")]
    if not rows:
        return []
    lines = [
        "",
        "## Queueing vs work",
        "",
        "Server side, from each succeeded ask's step events (`bench/stages.py`), in ms.",
        "",
        (
            "| workers | reranker | asks | queue p50 | queue p95 | worker p50 | worker p95 "
            "| queue share of wall time (mean) |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for run in rows:
        q = run["queueing"]
        lines.append(
            f"| {run['workers']} | {_reranker_label(run)} | {q['asks']} "
            f"| {_ms(q['queue_p50_ms'])} | {_ms(q['queue_p95_ms'])} | {_ms(q['worker_p50_ms'])} "
            f"| {_ms(q['worker_p95_ms'])} | {_pct(q['queue_share_of_wall'])} |"
        )
    return lines


def _definitions_section() -> list[str]:
    lines = ["", "## Metric definitions", ""]
    for name, text, url in METRIC_DEFINITIONS:
        lines.append(f"- **{name}.** {text} Source: <{url}>")
    return lines


def render_readme(
    *,
    sha: str,
    runs: Sequence[dict[str, Any]],
    machine: dict[str, Any],
    ingest: dict[str, Any] | None,
    chaos: dict[str, Any] | None,
    notes: str | None = None,
) -> str:
    runs = sorted(runs, key=_run_key)
    median_ms = next(
        (r.get("config", {}).get("llm_median_ms") for r in runs if r.get("config")), None
    )
    lines = [
        f"# Driftline bench results: `{sha}`",
        "",
        (
            f"All LLM calls in these runs go to the **{STUB_LLM}** (`LatencyStubAdapter`: seeded "
            "log-normal latency, deterministic text), so the numbers measure Driftline, not a "
            "provider's quota. Embeddings and reranking are real (TEI on CPU)."
        ),
        "",
        "## Ask load (k6, `bench/run.sh N`)",
        "",
    ]
    if runs:
        lines += [
            (
                "| workers | VUs | window (s) | completed | throughput (asks/s) | p50 ms | p95 ms "
                "| p99 ms | TTFT p50 ms | TTFT p95 ms | 429 rate | error rate | reranker | OOM |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for run in runs:
            s, cfg = run["summary"], run.get("config", {})
            lat, ttft = s["latency_ms"], s["ttft_ms"]
            oom = ", ".join(run.get("oom_killed") or []) or "none"
            rerank = _reranker_label(run)
            lines.append(
                f"| {run['workers']} | {cfg.get('vus', 'n/a')} | {s.get('window_s', 0):.0f} "
                f"| {s['completed']} | {s['throughput_per_s']:.2f} | {_ms(lat['p50'])} "
                f"| {_ms(lat['p95'])} | {_ms(lat['p99'])} | {_ms(ttft['p50'])} "
                f"| {_ms(ttft['p95'])} | {_pct(s['rate_429'])} | {_pct(s['error_rate'])} "
                f"| {rerank} | {oom} |"
            )
        lines += _percentile_section(runs)
        lines += _llm_section(runs, median_ms if median_ms is not None else "n/a")
        lines += _errors_section(runs)
        lines += _throughput_section(runs)
        lines += _scaling_section(runs)
        lines += _saturation_section(runs)
        lines += _queueing_section(runs)
    else:
        lines.append("Ask load: not run.")
    lines += _where_the_time_goes(runs)
    lines += ["", "## Ingest throughput (`bench/ingest.sh`)", ""]
    if ingest and ingest.get("runs"):
        lines += [
            f"Corpus: {ingest.get('corpus', 'n/a')}.",
            "",
            "| ingest workers | documents | chunks | seconds | documents/min | chunks/s |",
            "|---|---|---|---|---|---|",
        ]
        for r in sorted(ingest["runs"], key=lambda r: r["workers"]):
            lines.append(
                f"| {r['workers']} | {r['documents']} | {r['chunks']} | {r['seconds']:.1f} "
                f"| {r['docs_per_min']:.1f} | {r['chunks'] / r['seconds']:.1f} |"
            )
        lines += [
            "",
            (
                "Per-document ingest time (p50/p95): not captured in this run. `ingest.sh` "
                "times the whole batch; per-document figures need each ingest job's "
                "`started_at` / `finished_at` exported from the jobs table."
            ),
        ]
    else:
        lines.append("Ingest throughput: not run.")
    lines += ["", "## Chaos (`bench/chaos.sh`)", ""]
    if chaos:
        lost = chaos.get("failed", 0) + chaos.get("no_answer", 0)
        verdict = "PASS" if chaos.get("exit_code") == 0 else "FAIL"
        asks = chaos.get("asks") or 0
        availability = _pct(chaos.get("succeeded", 0) / asks) if asks else "n/a"
        lines += [
            (
                f"**{verdict}**: {chaos.get('asks')} asks, {chaos.get('kills')} worker kills, "
                f"{lost} lost, {chaos.get('stuck')} stuck, dlq {chaos.get('dlq')}, "
                f"pending {chaos.get('pending')}."
            ),
            "",
            (
                f"Availability under chaos (succeeded / asks): **{availability}** "
                f"({chaos.get('succeeded')} / {chaos.get('asks')}). "
                + (
                    "Recovery: no ask was lost, stuck or left pending after the drain, so every "
                    "ask a killed worker held was reclaimed and finished. "
                    if lost == 0 and not chaos.get("stuck") and not chaos.get("pending")
                    else ""
                )
                + "Time to recover per kill: not captured in this run (needs the kill "
                "timestamps and each reclaimed job's reclaim and finish times)."
            ),
            "",
            "```json",
            json.dumps(chaos, indent=2, sort_keys=True),
            "```",
        ]
    else:
        lines.append("Chaos: not run.")
    if notes:
        lines += ["", "## Notes", "", notes.strip()]
    lines += _definitions_section()
    lines += ["", "## Machine", "", *_machine_lines(machine), ""]
    return "\n".join(lines)
