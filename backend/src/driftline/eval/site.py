"""The static report site: `python -m driftline.eval site --out reports/site`.

Every number on the site is read from a committed report file:
- `evals/reports/**/*.json` (EvalReport), grouped by directory: real-Claude runs and the
  offline CI-gate baselines;
- `evals/golden/<corpus>.jsonl` and `evals/snapshot/<corpus>.jsonl` (set sizes, trap flags,
  sample strata);
- `evals/RESULTS.md` (only the run date, from its "| Date | ... |" row);
- `bench/results/**/*.json` (load test and chaos summaries, when published);
- `reports/drift-latest.json` (the nightly drift watch).

Missing inputs render an empty state, and unreadable files are listed, never crashed on.
Charts are inline SVG rendered here, so the site loads nothing from the network.
"""

from __future__ import annotations

import json
import math
import re
import shutil
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any, get_args

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError

from driftline.eval.types import EvalReport, System

TEMPLATES = Path(__file__).with_name("site_templates")
REPO_URL = "https://github.com/pranavkrishnadanda/Driftline"
PAGES_URL = "https://pranavkrishnadanda.github.io/Driftline/"
# The recorded demo of the web app: a static export the pages workflow adds under demo/
# after this site is built (frontend, NEXT_PUBLIC_DRIFTLINE_DEMO=1).
DEMO_PATH = "demo/"
SYSTEM_LABELS = {"driftline": "Driftline", "plain_rag": "Plain RAG", "no_retrieval": "No retrieval"}
CORPUS_ORDER = ("pharma", "k8s")


@dataclass(frozen=True)
class Page:
    file: str
    template: str
    title: str


PAGES = (
    Page("index.html", "index.html.j2", "Overview"),
    Page("evaluation.html", "evaluation.html.j2", "Evaluation"),
    Page("benchmarks.html", "benchmarks.html.j2", "Benchmarks"),
    Page("drift.html", "drift.html.j2", "Drift log"),
    Page("screenshots.html", "screenshots.html.j2", "Screenshots"),
)

# (metric key, column label, higher is better)
METRICS = (
    ("citation_precision", "Citation precision", True),
    ("outdated_citation_rate", "Outdated-citation rate", False),
    ("trap_citation_precision", "Trap precision", True),
    ("trap_outdated_citation_rate", "Trap outdated rate", False),
    ("faithfulness", "Faithfulness (verifier)", True),
    ("insufficient_evidence_accuracy", "Insufficient-evidence acc.", True),
    ("latency_p95_ms", "p95 latency (ms)", False),
    ("cost_per_answer_usd", "Cost / answer (USD)", False),
)
LABELS = {key: label for key, label, _ in METRICS}
PLAIN_NAMES = {
    "citation_precision": "citation precision",
    "outdated_citation_rate": "outdated-citation rate",
    "trap_citation_precision": "trap citation precision",
    "trap_outdated_citation_rate": "trap outdated-citation rate",
    "faithfulness": "faithfulness (verifier)",
    "insufficient_evidence_accuracy": "insufficient-evidence accuracy",
    "latency_p95_ms": "p95 latency (ms)",
    "cost_per_answer_usd": "cost per answer (USD)",
}


def fmt(name: str, value: float) -> str:
    """Format a metric exactly as evals/RESULTS.md does."""
    if name == "latency_p95_ms":
        return f"{value:.0f}"
    if name in ("cases", "scored", "citations", "stale_case_count", "error_count", "claims"):
        return f"{value:.0f}"
    return f"{value:.4f}"


# ---------------------------------------------------------------------------- eval data


@dataclass
class Strata:
    traps: int
    stable_point_in_time: int
    current: int
    other: int


@dataclass
class EvalGroup:
    """All reports in one directory of evals/reports (one run of one LLM setup)."""

    path: str  # repo-relative directory
    kind: str  # "claude" | "offline" | "other"
    reports: list[EvalReport]
    golden: dict[str, dict[str, Any]]  # case id -> golden case (trap, kind)

    @property
    def label(self) -> str:
        return {
            "claude": "Real Claude",
            "offline": "Offline extractive LLM (CI gate baseline)",
        }.get(self.kind, self.path)

    @property
    def anchor(self) -> str:
        return "run-" + re.sub(r"[^a-z0-9]+", "-", self.path.lower()).strip("-")

    @property
    def git_sha(self) -> str:
        return self.reports[0].git_sha

    @property
    def llm(self) -> str:
        return self.reports[0].llm

    @property
    def corpora(self) -> list[str]:
        found = {r.corpus for r in self.reports}
        return [c for c in CORPUS_ORDER if c in found] + sorted(found - set(CORPUS_ORDER))

    @property
    def systems(self) -> list[str]:
        found = {r.system for r in self.reports}
        return [s for s in get_args(System) if s in found]

    @property
    def missing_systems(self) -> list[str]:
        return [s for s in get_args(System) if s not in self.systems]

    def report(self, corpus: str, system: str) -> EvalReport | None:
        for r in self.reports:
            if (r.corpus, r.system) == (corpus, system):
                return r
        return None

    def rows(self) -> list[EvalReport]:
        return [
            r for c in self.corpora for s in self.systems if (r := self.report(c, s)) is not None
        ]

    @property
    def total_cost_usd(self) -> float:
        return sum(case.cost_usd for r in self.reports for case in r.cases)

    @property
    def judge_run(self) -> bool:
        return any(r.metrics.get("claims_judged", 0) > 0 for r in self.reports)

    def primary_models(self) -> dict[str, str]:
        """tier -> first model of its chain, from the report's `llm` string."""
        out: dict[str, str] = {}
        for part in self.llm.split(";"):
            m = re.match(r"\s*(?:.*\()?(\w+)=([^>;)]+)", part)
            if m:
                out[m.group(1)] = m.group(2).split("/", 1)[-1].strip()
        return out


@dataclass
class Headline:
    group: EvalGroup
    date: str | None
    full_set_sizes: dict[str, int]  # corpus -> golden cases
    sample_sizes: dict[str, int]  # corpus -> cases in the run
    strata: dict[str, Strata]
    subset_file: dict[str, bool]  # corpus -> the run's cases are exactly evals/snapshot/<c>
    losses: list[str]
    not_run: list[str]


@dataclass
class TrapRow:
    corpus: str
    system: str
    trap_cases: int
    other_cases: int
    trap_precision: str
    trap_outdated: str
    trap_with_outdated: int
    other_with_outdated: int
    trap_declined: int
    other_declined: int


# ---------------------------------------------------------------------------- bench data


@dataclass
class BenchFile:
    name: str
    values: dict[str, Any]  # flattened scalars


@dataclass
class BenchRun:
    path: str
    workers: list[tuple[int, BenchFile]]
    chaos: BenchFile | None
    machine: dict[str, Any]
    other: list[BenchFile]
    throughput_key: str | None
    p95_key: str | None

    @property
    def chaos_lost(self) -> int | None:
        """Lost or stuck jobs in the chaos run, or None when the summary has no counts."""
        if self.chaos is None:
            return None
        keys = [
            k for k in ("stuck", "failed", "no_answer", "dlq", "pending") if k in self.chaos.values
        ]
        if not keys:
            return None
        return int(sum(float(self.chaos.values[k]) for k in keys))


@dataclass
class SiteData:
    groups: list[EvalGroup] = field(default_factory=list)
    headline: Headline | None = None
    bench: BenchRun | None = None
    bench_other_runs: list[str] = field(default_factory=list)
    drift: dict[str, Any] | None = None
    screenshots: list[dict[str, str]] = field(default_factory=list)
    unreadable: dict[str, list[str]] = field(default_factory=dict)  # page -> files


def _rel(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _load_groups(repo: Path, unreadable: list[str]) -> list[EvalGroup]:
    root = repo / "evals" / "reports"
    by_dir: dict[Path, list[EvalReport]] = {}
    for path in sorted(root.rglob("*.json")) if root.is_dir() else []:
        try:
            report = EvalReport.model_validate_json(path.read_text())
        except (ValidationError, ValueError, OSError):
            unreadable.append(_rel(repo, path))
            continue
        by_dir.setdefault(path.parent, []).append(report)
    golden: dict[str, dict[str, Any]] = {}
    for corpus_file in sorted((repo / "evals" / "golden").glob("*.jsonl")):
        for case in _read_jsonl(corpus_file):
            if "id" in case:
                golden[case["id"]] = case
    groups = []
    for directory, reports in by_dir.items():
        llm = reports[0].llm
        if llm.startswith("offline"):
            kind = "offline"
        elif "anthropic/" in llm:
            kind = "claude"
        else:
            kind = "other"
        groups.append(EvalGroup(_rel(repo, directory), kind, reports, golden))
    order = {"claude": 0, "offline": 1, "other": 2}
    groups.sort(key=lambda g: (order[g.kind], g.path))
    return groups


def _results_date(repo: Path) -> str | None:
    path = repo / "evals" / "RESULTS.md"
    if not path.is_file():
        return None
    m = re.search(
        r"^\|\s*Date\s*\|\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\s*\|", path.read_text(), re.MULTILINE
    )
    return m.group(1) if m else None


def _strata(cases: list[dict[str, Any]]) -> Strata:
    traps = sum(1 for c in cases if c.get("trap"))
    pit = sum(1 for c in cases if not c.get("trap") and c.get("kind") == "point_in_time")
    current = sum(1 for c in cases if not c.get("trap") and c.get("kind") == "current")
    return Strata(traps, pit, current, len(cases) - traps - pit - current)


def _ratio(a: float, b: float) -> str:
    return f"{a / b:.1f}×" if b else "n/a"


def _losses(group: EvalGroup) -> list[str]:
    """Every metric where the baseline beat Driftline, plus Driftline's declined cases."""
    out = []
    for corpus in group.corpora:
        ours, base = group.report(corpus, "driftline"), group.report(corpus, "plain_rag")
        if ours is None or base is None:
            continue
        for key, _, higher in METRICS:
            if key not in ours.metrics or key not in base.metrics:
                continue
            a, b = ours.metrics[key], base.metrics[key]
            if (b > a) if higher else (b < a):
                line = (
                    f"{corpus}, {PLAIN_NAMES[key]}: plain RAG {fmt(key, b)}, "
                    f"Driftline {fmt(key, a)}"
                )
                if key in ("latency_p95_ms", "cost_per_answer_usd"):
                    line += f" ({_ratio(a, b)} plain RAG's)"
                out.append(line)
        declined = [
            c.case_id
            for c in ours.cases
            if c.status == "scored"
            and c.answer_status != "answered"
            and c.scores.get("insufficient_evidence_accuracy", 1.0) < 1.0
        ]
        answerable = sum(
            1 for c in ours.cases if group.golden.get(c.case_id, {}).get("kind") != "not_in_corpus"
        )
        if declined:
            out.append(
                f"{corpus}: Driftline declined {len(declined)} of {answerable} answerable "
                f"cases as insufficient evidence ({', '.join(declined)})"
            )
    return out


def _headline(repo: Path, groups: list[EvalGroup]) -> Headline | None:
    claude = [g for g in groups if g.kind == "claude"]
    if not claude:
        return None
    group = claude[-1]
    full, sample, strata, subset = {}, {}, {}, {}
    for corpus in group.corpora:
        golden = _read_jsonl(repo / "evals" / "golden" / f"{corpus}.jsonl")
        if golden:
            full[corpus] = len(golden)
        report = group.report(corpus, "driftline") or next(
            r for r in group.reports if r.corpus == corpus
        )
        ids = {c.case_id for c in report.cases}
        sample[corpus] = len(ids)
        strata[corpus] = _strata([group.golden[i] for i in ids if i in group.golden])
        snap = {c.get("id") for c in _read_jsonl(repo / "evals" / "snapshot" / f"{corpus}.jsonl")}
        subset[corpus] = snap == ids
    not_run = [f"the {s} baseline (no report committed)" for s in group.missing_systems]
    if not group.judge_run:
        not_run.append(
            "the faithfulness LLM judge (claims_judged is 0 in every report; faithfulness "
            "is the verifier's deterministic check)"
        )
    return Headline(
        group, _results_date(repo), full, sample, strata, subset, _losses(group), not_run
    )


def _trap_rows(group: EvalGroup) -> list[TrapRow]:
    rows = []
    for r in group.rows():
        trap = [c for c in r.cases if group.golden.get(c.case_id, {}).get("trap")]
        other = [c for c in r.cases if not group.golden.get(c.case_id, {}).get("trap")]

        def outdated(cases):
            return sum(1 for c in cases if c.scores.get("outdated_citation_rate", 0) > 0)

        def declined(cases):
            return sum(1 for c in cases if c.status == "scored" and c.answer_status != "answered")

        rows.append(
            TrapRow(
                r.corpus,
                r.system,
                len(trap),
                len(other),
                fmt("x", r.metrics.get("trap_citation_precision", float("nan"))),
                fmt("x", r.metrics.get("trap_outdated_citation_rate", float("nan"))),
                outdated(trap),
                outdated(other),
                declined(trap),
                declined(other),
            )
        )
    return rows


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, (str, int, float, bool)) or value is None:
        out[prefix or "value"] = value
    return out


def _pick(files: list[BenchFile], pattern: str, avoid: str = r"ttft|first") -> str | None:
    for f in files:
        for key, v in f.values.items():
            if (
                re.search(pattern, key, re.IGNORECASE)
                and not re.search(avoid, key, re.IGNORECASE)
                and isinstance(v, (int, float))
                and not isinstance(v, bool)
            ):
                return key
    return None


def _load_bench_dir(repo: Path, directory: Path, unreadable: list[str]) -> BenchRun | None:
    workers: list[tuple[int, BenchFile]] = []
    chaos, other, machine = None, [], {}
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            unreadable.append(_rel(repo, path))
            continue
        if not isinstance(raw, dict):
            unreadable.append(_rel(repo, path))
            continue
        if isinstance(raw.get("machine"), dict):
            machine.update(_flatten(raw["machine"]))
        elif isinstance(raw.get("machine"), str):
            machine.setdefault("machine", raw["machine"])
        values = {k: v for k, v in _flatten(raw).items() if not k.startswith("machine")}
        bf = BenchFile(path.name, values)
        stem = path.stem.lower()
        m = re.match(r"workers-(\d+)$", stem)
        if m or isinstance(raw.get("workers"), int) and "chaos" not in stem:
            workers.append((int(m.group(1)) if m else raw["workers"], bf))
        elif stem.startswith("chaos"):
            chaos = bf
        elif stem.startswith("machine"):
            machine.update(_flatten(raw))
        else:
            other.append(bf)
    if not (workers or chaos or other or machine):
        return None
    workers.sort(key=lambda w: w[0])
    files = [w[1] for w in workers]
    return BenchRun(
        _rel(repo, directory),
        workers,
        chaos,
        machine,
        other,
        _pick(files, r"throughput|rps|per_s(ec)?$"),
        _pick(files, r"p95"),
    )


def _load_bench(repo: Path, unreadable: list[str]) -> tuple[BenchRun | None, list[str]]:
    root = repo / "bench" / "results"
    if not root.is_dir():
        return None, []
    dirs = [root, *sorted(d for d in root.rglob("*") if d.is_dir())]
    runs = [r for d in dirs if (r := _load_bench_dir(repo, d, unreadable)) is not None]
    if not runs:
        return None, []

    def stamp(run: BenchRun) -> str:
        for _, f in run.workers:
            for key in ("generated_at", "date", "finished_at", "started_at"):
                if isinstance(f.values.get(key), str):
                    return f.values[key]
        return ""

    runs.sort(key=lambda r: (stamp(r), r.path))
    return runs[-1], [r.path for r in runs[:-1]]


def _load_drift(repo: Path, unreadable: list[str]) -> dict[str, Any] | None:
    path = repo / "reports" / "drift-latest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        unreadable.append(_rel(repo, path))
        return None
    if not isinstance(data, dict) or not isinstance(data.get("totals"), dict):
        unreadable.append(_rel(repo, path))
        return None
    data.setdefault("documents", [])
    data.setdefault("changes", [])
    return data


SCREENSHOT_CAPTIONS = {
    "landing": "Landing page",
    "ask-answered": "Ask: an answer with its verified citation and source version",
    "document-timeline": "Document timeline: versions, what changed, related documents",
    "drift-inbox": "Drift inbox: answers whose cited text changed or was removed",
    "review-queue": "Review queue",
    "stats": "Stats dashboard",
    "ask-answered-dark": "Ask, dark theme",
    "ask-answered-mobile": "Ask on a phone-sized screen",
}


def _screenshots(repo: Path) -> list[dict[str, str]]:
    root = repo / "docs" / "screenshots"
    order = list(SCREENSHOT_CAPTIONS)
    files = [
        p
        for p in (root.iterdir() if root.is_dir() else [])
        if p.suffix.lower() in (".webp", ".png", ".jpg", ".jpeg")
    ]
    files.sort(key=lambda p: (order.index(p.stem) if p.stem in order else len(order), p.name))
    return [
        {
            "file": p.name,
            "caption": SCREENSHOT_CAPTIONS.get(p.stem, p.stem.replace("-", " ")),
            "mobile": "mobile" in p.stem,
        }
        for p in files
    ]


def load_site_data(repo: Path) -> SiteData:
    eval_bad: list[str] = []
    bench_bad: list[str] = []
    drift_bad: list[str] = []
    groups = _load_groups(repo, eval_bad)
    bench, bench_other = _load_bench(repo, bench_bad)
    return SiteData(
        groups=groups,
        headline=_headline(repo, groups),
        bench=bench,
        bench_other_runs=bench_other,
        drift=_load_drift(repo, drift_bad),
        screenshots=_screenshots(repo),
        unreadable={"evaluation": eval_bad, "benchmarks": bench_bad, "drift": drift_bad},
    )


# ---------------------------------------------------------------------------- README


def readme_results_table(headline: Headline) -> str:
    """The README's headline table: the real-Claude metrics, formatted like RESULTS.md."""
    cols = ["Corpus", "System", "Cases", *LABELS.values()]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in headline.group.rows():
        cells = [r.corpus, f"`{r.system}`", fmt("cases", r.metrics["cases"])]
        cells += [fmt(k, r.metrics[k]) for k in LABELS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- SVG charts

_W, _PAD_L, _PAD_R, _PAD_T, _PAD_B = 640, 92, 64, 16, 40


def bar_chart_svg(
    title: str,
    desc: str,
    groups: list[tuple[str, list[tuple[str, float, str]]]],
    max_value: float = 1.0,
) -> str:
    """Horizontal grouped bars. groups: [(group label, [(series, value, display)])]."""
    bar_h, gap, group_gap = 18, 4, 18
    n_bars = sum(len(bars) for _, bars in groups)
    height = _PAD_T + n_bars * (bar_h + gap) + len(groups) * group_gap + _PAD_B
    plot_w = _W - _PAD_L - _PAD_R
    uid = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    parts = [
        _svg_open(uid, height, title, desc),
    ]
    axis_y = height - _PAD_B + 6
    for i in range(5):
        frac = i / 4
        x = _PAD_L + plot_w * frac
        parts.append(
            f'<line class="grid" x1="{x:.1f}" y1="{_PAD_T}" x2="{x:.1f}" y2="{axis_y - 6}"/>'
            f'<text class="tick" x="{x:.1f}" y="{axis_y + 12}" text-anchor="middle">'
            f"{max_value * frac:g}</text>"
        )
    y = _PAD_T
    for label, bars in groups:
        block = len(bars) * (bar_h + gap)
        parts.append(
            f'<text class="glabel" x="{_PAD_L - 10}" y="{y + block / 2:.1f}" '
            f'text-anchor="end" dominant-baseline="middle">{escape(label)}</text>'
        )
        for series, value, display in bars:
            w = max(plot_w * min(value / max_value, 1.0), 0.0) if max_value else 0.0
            r = min(4.0, w / 2)
            parts.append(
                f'<g class="mark"><title>{escape(label)}, {escape(SYSTEM_LABELS.get(series, series))}: '
                f"{escape(display)}</title>"
                f'<rect class="hit" x="{_PAD_L}" y="{y - 1}" width="{plot_w}" height="{bar_h + 2}"/>'
                f'<path class="s-{escape(series)}" d="{_bar_path(_PAD_L, y, w, bar_h, r)}"/>'
                f'<text class="vlabel" x="{_PAD_L + w + 6:.1f}" y="{y + bar_h / 2:.1f}" '
                f'dominant-baseline="middle">{escape(display)}</text></g>'
            )
            y += bar_h + gap
        y += group_gap
    parts.append(
        f'<line class="axis" x1="{_PAD_L}" y1="{_PAD_T}" x2="{_PAD_L}" y2="{axis_y - 6}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _nice_step(raw: float) -> float:
    """The smallest 1, 2, 2.5 or 5 × 10^k step at least `raw` (axis ticks)."""
    if raw <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(raw))
    return next(m * exp for m in (1, 2, 2.5, 5, 10) if m * exp >= raw)


def _svg_open(uid: str, height: int, title: str, desc: str) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {_W} {height}" role="img" '
        f'aria-labelledby="{uid}-t {uid}-d" preserveAspectRatio="xMinYMin meet">'
        f'<title id="{uid}-t">{escape(title)}</title><desc id="{uid}-d">{escape(desc)}</desc>'
    )


def _bar_path(x: float, y: float, w: float, h: float, r: float) -> str:
    """A bar anchored square at the baseline, rounded at its data end."""
    if w <= 0:
        return f"M{x},{y}h0v{h}h0z"
    return (
        f"M{x:.1f},{y:.1f}h{w - r:.1f}q{r:.1f},0 {r:.1f},{r:.1f}v{h - 2 * r:.1f}"
        f"q0,{r:.1f} -{r:.1f},{r:.1f}h-{w - r:.1f}z"
    )


def line_chart_svg(
    title: str, desc: str, points: list[tuple[int, float, str]], y_label: str
) -> str:
    """A single-series line over worker counts. points: [(workers, value, display)]."""
    height = 260
    plot_w, plot_h = _W - _PAD_L - _PAD_R, height - _PAD_T - _PAD_B - 8
    xs = [p[0] for p in points]
    x_min, x_max = min(xs), max(xs)
    step = _nice_step(max(p[1] for p in points) * 1.1 / 4)
    y_max = step * 4
    uid = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

    def px(x: float) -> float:
        return _PAD_L + (plot_w * (x - x_min) / (x_max - x_min) if x_max > x_min else plot_w / 2)

    def py(v: float) -> float:
        return _PAD_T + plot_h * (1 - v / y_max)

    parts = [
        _svg_open(uid, height, title, desc),
    ]
    for i in range(5):
        v = y_max * i / 4
        parts.append(
            f'<line class="grid" x1="{_PAD_L}" y1="{py(v):.1f}" x2="{_PAD_L + plot_w}" '
            f'y2="{py(v):.1f}"/><text class="tick" x="{_PAD_L - 8}" y="{py(v):.1f}" '
            f'text-anchor="end" dominant-baseline="middle">{v:,.10g}</text>'
        )
    base = _PAD_T + plot_h
    for x in xs:
        parts.append(
            f'<text class="tick" x="{px(x):.1f}" y="{base + 18}" text-anchor="middle">{x}</text>'
        )
    parts.append(
        f'<text class="tick" x="{_PAD_L + plot_w / 2}" y="{height - 4}" '
        f'text-anchor="middle">agent workers</text>'
        f'<text class="tick" x="14" y="{_PAD_T + plot_h / 2}" text-anchor="middle" '
        f'transform="rotate(-90 14 {_PAD_T + plot_h / 2})">{escape(y_label)}</text>'
    )
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(v):.1f}" for i, (x, v, _) in enumerate(points)
    )
    parts.append(f'<path class="line s-driftline" d="{path}"/>')
    for x, v, display in points:
        parts.append(
            f'<g class="mark"><title>{x} workers: {escape(display)}</title>'
            f'<circle class="hit" cx="{px(x):.1f}" cy="{py(v):.1f}" r="14"/>'
            f'<circle class="dot s-driftline" cx="{px(x):.1f}" cy="{py(v):.1f}" r="5"/>'
            f'<text class="vlabel" x="{px(x):.1f}" y="{py(v) - 12:.1f}" '
            f'text-anchor="middle">{escape(display)}</text></g>'
        )
    parts.append(
        f'<line class="axis" x1="{_PAD_L}" y1="{base}" x2="{_PAD_L + plot_w}" y2="{base}"/></svg>'
    )
    return "".join(parts)


def _eval_charts(group: EvalGroup) -> list[str]:
    charts = []
    for key, title, desc in (
        (
            "outdated_citation_rate",
            f"Outdated-citation rate, {group.label} (lower is better)",
            "Share of citations pointing at a version not in force at the question's date.",
        ),
        (
            "citation_precision",
            f"Citation precision, {group.label} (higher is better)",
            "Share of citations in force at the question's date with a supported quote.",
        ),
    ):
        bars = []
        for corpus in group.corpora:
            series = [
                (s, r.metrics[key], fmt(key, r.metrics[key]))
                for s in group.systems
                if (r := group.report(corpus, s)) is not None and key in r.metrics
            ]
            if series:
                bars.append((corpus, series))
        if bars:
            charts.append(bar_chart_svg(title, desc, bars))
    return charts


def _bench_charts(run: BenchRun) -> list[str]:
    charts = []
    for key, title in ((run.throughput_key, "Throughput"), (run.p95_key, "p95 latency")):
        if key is None:
            continue
        points = [
            (w, float(f.values[key]), f"{f.values[key]:g}")
            for w, f in run.workers
            if isinstance(f.values.get(key), (int, float))
        ]
        if points:
            charts.append(
                line_chart_svg(
                    f"{title} vs agent workers",
                    f"{title} ({key}) at each worker count, from {run.path}.",
                    points,
                    key,
                )
            )
    return charts


# ---------------------------------------------------------------------------- build


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["fmt"] = lambda value, name="x": fmt(name, value)
    env.globals.update(
        PAGES=PAGES,
        METRICS=METRICS,
        SYSTEM_LABELS=SYSTEM_LABELS,
        REPO_URL=REPO_URL,
        PAGES_URL=PAGES_URL,
        DEMO_PATH=DEMO_PATH,
    )
    return env


def build_site(repo: Path, out: Path, *, source_sha: str | None = None) -> SiteData:
    """Render every page into `out` (created, and emptied first if it exists)."""
    data = load_site_data(repo)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    for asset in (TEMPLATES / "assets").iterdir():
        shutil.copy(asset, out / "assets" / asset.name)
    if data.screenshots:
        (out / "screenshots").mkdir()
        for shot in data.screenshots:
            shutil.copy(repo / "docs" / "screenshots" / shot["file"], out / "screenshots")
    (out / ".nojekyll").write_text("")
    env = _env()
    context = {
        "data": data,
        "h": data.headline,
        "source_sha": source_sha,
        "eval_charts": {g.path: _eval_charts(g) for g in data.groups},
        "trap_rows": {g.path: _trap_rows(g) for g in data.groups},
        "bench_charts": _bench_charts(data.bench) if data.bench else [],
    }
    for page in PAGES:
        html = env.get_template(page.template).render(page=page, **context)
        (out / page.file).write_text(html)
    return data
