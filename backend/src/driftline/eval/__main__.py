"""`python -m driftline.eval {run,compare}`.

run      --corpus C --system S [--cases PATH] [--tenant NAME] [--reports-dir DIR]
         Evaluate one system on a golden set (default: evals/golden/<corpus>.jsonl)
         against the corpus's tenant (default: the tenant named like the corpus).
         Exit 1 when any case errored.
compare  --base <sha|path> --head <path> [--reports-dir DIR]
         The CI gate (spec section 12). Exit 0 pass, 1 regression, 2 no usable base
         (missing, or a run of another corpus, system or LLM).
load-snapshot --path FILE
         Load an eval-gate DB snapshot (driftline.eval.snapshot) into the configured,
         freshly migrated database. Exit 2 when it is altered or the database is not empty.
site     --out DIR [--repo DIR] [--source-sha SHA]
         Build the static report site (driftline.eval.site) from the committed reports.
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

import asyncpg
import redis.asyncio as aioredis

from driftline.agents.__main__ import build_agent_router
from driftline.agents.graph import AgentConfig, AgentDeps
from driftline.agents.llm import AgentLLM
from driftline.clock import SystemClock
from driftline.config import Settings
from driftline.eval.curate import add_curate_parser, curate
from driftline.eval.metrics import gate
from driftline.eval.runner import SYSTEMS, EvalDeps, report_path, run
from driftline.eval.site import build_site
from driftline.eval.snapshot import SnapshotError, load_snapshot
from driftline.eval.types import EvalReport, GoldenCase
from driftline.obs.cost import CostLedger
from driftline.retrieval.hybrid import HybridRetriever
from driftline.retrieval.rerank import TEIReranker

REPO = Path(__file__).resolve().parents[4]
DEFAULT_REPORTS = REPO / "evals" / "reports"
GATED = ("citation_precision", "outdated_citation_rate")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m driftline.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="evaluate one system on a golden set")
    r.add_argument("--corpus", required=True)
    r.add_argument("--system", required=True, choices=SYSTEMS)
    r.add_argument("--cases", type=Path, help="JSONL golden cases")
    r.add_argument("--tenant", help="tenant name (default: the corpus name)")
    r.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    r.add_argument("--git-sha", help="commit being evaluated (default: git rev-parse HEAD)")
    r.add_argument("--judge-sample", type=int, default=0)
    c = sub.add_parser("compare", help="gate a head report against a base run")
    c.add_argument("--base", required=True, help="a commit sha or a report path")
    c.add_argument("--head", required=True, type=Path, help="the head report path")
    c.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS)
    s = sub.add_parser("load-snapshot", help="load an eval-gate DB snapshot")
    s.add_argument("--path", required=True, type=Path, help="the .snapshot.gz file")
    w = sub.add_parser("site", help="build the static report site")
    w.add_argument("--out", required=True, type=Path, help="output directory (replaced)")
    w.add_argument("--repo", type=Path, default=REPO, help="repository root to read from")
    w.add_argument("--source-sha", help="commit the site is built from (shown in the footer)")
    add_curate_parser(sub)
    return parser


def load_cases(path: Path) -> list[GoldenCase]:
    return [
        GoldenCase.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def git_sha() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    cases = load_cases(args.cases or REPO / "evals" / "golden" / f"{args.corpus}.jsonl")
    clock = SystemClock()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=4)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        tenant_name = args.tenant or args.corpus
        async with pool.acquire() as conn:
            tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE name = $1", tenant_name)
        if tenant_id is None:
            print(f"no tenant named {tenant_name!r}", file=sys.stderr)
            return 2
        router = build_agent_router(settings, redis, clock=clock)
        agent = AgentDeps(
            pool=pool,
            llm=AgentLLM(router, ledger=CostLedger(pool)),
            retriever=HybridRetriever(
                pool,
                router,
                embed_model=settings.model_embed,
                dim=settings.embed_dim,
                candidates=settings.retrieval_candidates,
                rrf_k=settings.rrf_k,
            ),
            reranker=TEIReranker(settings.rerank_url),
            clock=clock,
            config=AgentConfig.from_settings(settings),
        )
        deps = EvalDeps(
            agent=agent,
            tenant_id=tenant_id,
            git_sha=args.git_sha or git_sha(),
            reports_dir=args.reports_dir,
            timer=clock,
            judge_sample=args.judge_sample,
        )
        report = await run(args.corpus, args.system, cases, deps)
    finally:
        await redis.aclose()
        await pool.close()
    path = report_path(args.reports_dir, report.git_sha, report.corpus, report.system)
    print(f"wrote {path}")
    for name in sorted(report.metrics):
        print(f"{name}: {report.metrics[name]:.4f}")
    errors = int(report.metrics.get("error_count", 0))
    if errors:
        print(f"{errors} case(s) failed with an error", file=sys.stderr)
        return 1
    return 0


def _compare(args: argparse.Namespace) -> int:
    head = EvalReport.model_validate_json(args.head.read_text())
    base_path = Path(args.base)
    if not base_path.is_file():
        base_path = report_path(args.reports_dir, args.base, head.corpus, head.system)
    if not base_path.is_file():
        print(f"no base report for {args.base!r} (looked for {base_path})", file=sys.stderr)
        return 2
    base = EvalReport.model_validate_json(base_path.read_text())
    if (base.corpus, base.system) != (head.corpus, head.system):
        print(
            f"the base must be a run of the same corpus and system: base is "
            f"{base.corpus}/{base.system}, head is {head.corpus}/{head.system}",
            file=sys.stderr,
        )
        return 2
    if base.llm != head.llm:
        print(
            f"the base must be answered by the same LLM: base is {base.llm!r}, "
            f"head is {head.llm!r}",
            file=sys.stderr,
        )
        return 2
    failures = gate(base.metrics, head.metrics)
    print(f"## Eval gate: {head.corpus} / {head.system} ({base.git_sha} -> {head.git_sha})")
    print()
    print(f"LLM: {head.llm}")
    print()
    print("| Metric | Base | Head | Change (points) |")
    print("|---|---|---|---|")
    for name in GATED:
        cells = [f"{r.metrics[name]:.4f}" if name in r.metrics else "-" for r in (base, head)]
        both = name in base.metrics and name in head.metrics
        change = f"{(head.metrics[name] - base.metrics[name]) * 100:+.2f}" if both else "-"
        print(f"| {name} | {cells[0]} | {cells[1]} | {change} |")
    print()
    if failures:
        print("**FAIL**")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("**PASS**")
    return 0


async def _load_snapshot(args: argparse.Namespace, settings: Settings) -> int:
    conn = await asyncpg.connect(settings.database_url)
    try:
        rows = await load_snapshot(conn, args.path)
    except SnapshotError as exc:
        print(f"snapshot not loaded: {exc}", file=sys.stderr)
        return 2
    finally:
        await conn.close()
    print(f"loaded {args.path}: {rows}")
    return 0


async def amain(argv: list[str], settings: Settings | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "compare":
        return _compare(args)
    if args.command == "load-snapshot":
        return await _load_snapshot(args, settings or Settings())
    if args.command == "curate":
        return await curate(args)
    if args.command == "site":
        data = build_site(args.repo, args.out, source_sha=args.source_sha)
        skipped = sum(len(files) for files in data.unreadable.values())
        print(f"wrote {args.out} ({skipped} unreadable input file(s) skipped)")
        return 0
    return await _run(args, settings or Settings())


if __name__ == "__main__":
    sys.exit(asyncio.run(amain(sys.argv[1:])))
