"""Summarise k6 bench runs and render `bench/results/<sha>/README.md`.

Input is k6's NDJSON output (`k6 run --out json=raw.ndjson`, optionally gzipped): one
`Point` line per sample. `bench/k6/ask.js` emits the samples read here:

- `ask_latency` (ms, POST sent -> `final` received) and `ask_ttft` (ms, -> first token);
- the counters `ask_completed`, `ask_rejected` (HTTP 429 backpressure) and `ask_failed`.

Percentiles are computed from every raw sample (linear interpolation, the same as
`statistics.quantiles(method="inclusive")`), not taken from k6's own summary. Throughput is
completed asks over the sample window (first to last sample). Nothing is dropped: 429s and
failures are counted in `attempts` and reported as rates.
"""

import gzip
import json
import math
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

STUB_LLM = "stub LLM"
QUANTILES = {"p50": 0.50, "p95": 0.95, "p99": 0.99}

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
    out["mean"] = sum(values) / len(values) if values else None
    out["max"] = max(values) if values else None
    out["count"] = len(values)
    return out


def summarize_k6(lines: Iterable[str]) -> Summary:
    samples: dict[str, list[float]] = {}
    first: datetime | None = None
    last: datetime | None = None
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") != "Point":
            continue
        data = row["data"]
        t = datetime.fromisoformat(data["time"])
        first = t if first is None or t < first else first
        last = t if last is None or t > last else last
        samples.setdefault(row["metric"], []).append(float(data["value"]))

    completed = int(sum(samples.get("ask_completed", [])))
    rejected = int(sum(samples.get("ask_rejected", [])))
    failed = int(sum(samples.get("ask_failed", [])))
    attempts = completed + rejected + failed
    window_s = (last - first).total_seconds() if first and last else 0.0
    return {
        "window_s": window_s,
        "attempts": attempts,
        "completed": completed,
        "rejected_429": rejected,
        "failed": failed,
        "throughput_per_s": completed / window_s if window_s > 0 else 0.0,
        "rate_429": rejected / attempts if attempts else 0.0,
        "error_rate": failed / attempts if attempts else 0.0,
        "latency_ms": _stats(samples.get("ask_latency", [])),
        "ttft_ms": _stats(samples.get("ask_ttft", [])),
        "http_reqs": int(sum(samples.get("http_reqs", []))),
    }


def summarize_k6_file(path: Path | str) -> Summary:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return summarize_k6(fh)


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _machine_lines(machine: dict[str, Any]) -> list[str]:
    if not machine:
        return ["Machine info not recorded."]
    return [
        f"- **{key}**: {json.dumps(value) if isinstance(value, dict | list) else value}"
        for key, value in machine.items()
    ]


STAGE_COLUMNS = ("wall", "queue", "worker", "plan", "retrieve", "draft", "verify")


def _cpu(entry: dict[str, Any]) -> float:
    try:
        return float(str(entry.get("CPUPerc", "0")).rstrip("%"))
    except ValueError:
        return 0.0


def _where_the_time_goes(runs: Sequence[dict[str, Any]]) -> list[str]:
    """p50 ms per stage (bench/stages.py, from each ask's step events) and the busiest
    containers in the mid-run `docker stats` snapshot."""
    staged = [
        r for r in sorted(runs, key=lambda r: r["workers"]) if r.get("stages", {}).get("asks")
    ]
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
        "| workers | asks | "
        + " | ".join(STAGE_COLUMNS)
        + " | rerank ran | busiest containers (CPU) |",
        "|---|---|" + "---|" * len(STAGE_COLUMNS) + "---|---|",
    ]
    for run in staged:
        st = run["stages"]
        cells = [_ms((st.get(k) or {}).get("p50")) for k in STAGE_COLUMNS]
        busiest = sorted(run.get("container_stats_mid_run") or [], key=_cpu, reverse=True)[:3]
        cpu = ", ".join(
            f"{e['Name'].removeprefix('driftline-bench-')} {e['CPUPerc']}" for e in busiest
        )
        lines.append(
            f"| {run['workers']} | {st['asks']} | "
            + " | ".join(cells)
            + f" | {_pct(st.get('rerank_ran_share'))} | {cpu or 'n/a'} |"
        )
    return lines


def render_readme(
    *,
    sha: str,
    runs: Sequence[dict[str, Any]],
    machine: dict[str, Any],
    ingest: dict[str, Any] | None,
    chaos: dict[str, Any] | None,
) -> str:
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
        for run in sorted(runs, key=lambda r: r["workers"]):
            s, cfg = run["summary"], run.get("config", {})
            lat, ttft = s["latency_ms"], s["ttft_ms"]
            oom = ", ".join(run.get("oom_killed") or []) or "none"
            lines.append(
                f"| {run['workers']} | {cfg.get('vus', 'n/a')} | {s.get('window_s', 0):.0f} "
                f"| {s['completed']} | {s['throughput_per_s']:.2f} | {_ms(lat['p50'])} "
                f"| {_ms(lat['p95'])} | {_ms(lat['p99'])} | {_ms(ttft['p50'])} "
                f"| {_ms(ttft['p95'])} | {_pct(s['rate_429'])} | {_pct(s['error_rate'])} "
                f"| {cfg.get('reranker', 'n/a')} | {oom} |"
            )
    else:
        lines.append("Ask load: not run.")
    lines += _where_the_time_goes(runs)
    lines += ["", "## Ingest throughput (`bench/ingest.sh`)", ""]
    if ingest and ingest.get("runs"):
        lines += [
            f"Corpus: {ingest.get('corpus', 'n/a')}.",
            "",
            "| ingest workers | documents | chunks | seconds | documents/min |",
            "|---|---|---|---|---|",
        ]
        for r in sorted(ingest["runs"], key=lambda r: r["workers"]):
            lines.append(
                f"| {r['workers']} | {r['documents']} | {r['chunks']} | {r['seconds']:.1f} "
                f"| {r['docs_per_min']:.1f} |"
            )
    else:
        lines.append("Ingest throughput: not run.")
    lines += ["", "## Chaos (`bench/chaos.sh`)", ""]
    if chaos:
        lost = chaos.get("failed", 0) + chaos.get("no_answer", 0)
        verdict = "PASS" if chaos.get("exit_code") == 0 else "FAIL"
        lines += [
            (
                f"**{verdict}**: {chaos.get('asks')} asks, {chaos.get('kills')} worker kills, "
                f"{lost} lost, {chaos.get('stuck')} stuck, dlq {chaos.get('dlq')}, "
                f"pending {chaos.get('pending')}."
            ),
            "",
            "```json",
            json.dumps(chaos, indent=2, sort_keys=True),
            "```",
        ]
    else:
        lines.append("Chaos: not run.")
    lines += ["", "## Machine", "", *_machine_lines(machine), ""]
    return "\n".join(lines)
