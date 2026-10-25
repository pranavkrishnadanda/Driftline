"""`python -m driftline.bench {k6,readme}`.

- `k6 RAW --meta META --out OUT`: summarise one k6 NDJSON run (`RAW`, optionally .gz) and
  write `OUT` = META's fields + `"summary"`.
- `readme DIR`: render `DIR/README.md` from `DIR/workers-*.json`, `machine.json`,
  `ingest.json` and `chaos.json` (each optional).
"""

import argparse
import json
import sys
from pathlib import Path

from driftline.bench.summarize import render_readme, summarize_k6_file


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.is_file() else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m driftline.bench")
    sub = parser.add_subparsers(dest="command", required=True)
    k6 = sub.add_parser("k6", help="summarise a k6 NDJSON run")
    k6.add_argument("raw", type=Path)
    k6.add_argument("--meta", type=Path, required=True)
    k6.add_argument("--out", type=Path, required=True)
    readme = sub.add_parser("readme", help="render README.md for a results directory")
    readme.add_argument("dir", type=Path)
    args = parser.parse_args(argv)

    if args.command == "k6":
        run = json.loads(args.meta.read_text())
        run["summary"] = summarize_k6_file(args.raw)
        args.out.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
        print(json.dumps(run["summary"], sort_keys=True))
        return 0

    runs = [json.loads(p.read_text()) for p in sorted(args.dir.glob("workers-*.json"))]
    md = render_readme(
        sha=args.dir.name,
        runs=runs,
        machine=_load(args.dir / "machine.json") or {},
        ingest=_load(args.dir / "ingest.json"),
        chaos=_load(args.dir / "chaos.json"),
    )
    (args.dir / "README.md").write_text(md)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
