"""Build the eval CI gate's data from a database that holds the full golden corpora.

    uv run --project backend python evals/snapshot/build.py --dsn postgresql://...

1. For each corpus, pick the gate subset of evals/golden/<corpus>.jsonl
   (`driftline.eval.snapshot.gate_subset`) and write it to <out-dir>/<corpus>.jsonl.
2. Export the versions those cases need, plus each one's previous and next version, with
   their chunks and embeddings, to <out-dir>/gate.snapshot.gz and gate.manifest.json.

The source database is the golden-set curation database (evals/golden/README.md),
restored from its pg_dump. Same database, same golden files: same bytes.
Load the result with `python -m driftline.eval load-snapshot`.
"""

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

import asyncpg

from driftline.eval.snapshot import export_snapshot, gate_subset, snapshot_versions
from driftline.eval.types import GoldenCase

REPO = Path(__file__).resolve().parents[2]


def _args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dsn", required=True, help="database with the full golden corpora")
    parser.add_argument("--golden-dir", type=Path, default=REPO / "evals" / "golden")
    parser.add_argument("--out-dir", type=Path, default=REPO / "evals" / "snapshot")
    parser.add_argument("--corpora", nargs="+", default=["pharma", "k8s"])
    parser.add_argument("--per-corpus", type=int, default=40)
    parser.add_argument("--source", default="", help="a note on the source database")
    return parser.parse_args(argv)


async def build(args: argparse.Namespace) -> dict:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    expected, counts, golden_sha = set(), {}, {}
    for corpus in args.corpora:
        path = args.golden_dir / f"{corpus}.jsonl"
        text = path.read_text()
        cases = [GoldenCase.model_validate_json(line) for line in text.splitlines() if line]
        picked = gate_subset(cases, args.per_corpus)
        (args.out_dir / f"{corpus}.jsonl").write_text(
            "".join(c.model_dump_json() + "\n" for c in picked)
        )
        expected |= {v for c in picked for v in c.expected_version_ids}
        counts[corpus] = len(picked)
        golden_sha[corpus] = hashlib.sha256(text.encode()).hexdigest()
    conn = await asyncpg.connect(args.dsn)
    try:
        versions = await snapshot_versions(conn, expected)
        if missing := expected - set(versions):
            raise SystemExit(f"{len(missing)} expected version(s) are not in the database")
        return await export_snapshot(
            conn,
            versions,
            args.out_dir / "gate.snapshot.gz",
            cases=counts,
            per_corpus=args.per_corpus,
            golden_sha256=golden_sha,
            expected_versions=len(expected),
            source=args.source,
        )
    finally:
        await conn.close()


def main(argv: list[str]) -> int:
    manifest = asyncio.run(build(_args(argv)))
    print(f"wrote {manifest['file']}: {manifest['bytes']} bytes, rows {manifest['rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
