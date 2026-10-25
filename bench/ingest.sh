#!/usr/bin/env bash
# bench/ingest.sh: ingest throughput (documents/minute) at 1, 2 and 4 ingest workers.
#
# For each worker count W, on a fresh bench stack (`down -v`; no reranker, no agents):
#   1. build a corpus of COPIES x the bench/corpus documents (every heading suffixed with
#      "(copy k)", so each copy is its own document with its own section text);
#   2. enqueue it all (upload connector, --discover);
#   3. start W `ingest worker --drain` containers at once and time until the last exits
#      (each exits only when the ingest and embed streams and the outbox are empty).
# Chunking, the outbox relay and embedding (TEI on CPU, shared by all workers) are all
# inside the timed window; supersession extraction is off (it needs an LLM key).
# Writes bench/results/<sha>/ingest.json and re-renders the README.
#
# Env: WORKER_COUNTS ("1 2 4"), COPIES (10).
set -euo pipefail
# shellcheck source=bench/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

WORKER_COUNTS="${WORKER_COUNTS:-1 2 4}"
COPIES="${COPIES:-10}"
BENCH_RERANKER=off

CORPUS="$WORK/ingest-corpus"
rm -rf "$CORPUS"
mkdir -p "$CORPUS"
for k in $(seq 1 "$COPIES"); do
  for f in "$ROOT"/bench/corpus/*.md; do
    sed -E "s/^(#+ .*)$/\1 (copy $k)/" "$f" >"$CORPUS/$(basename "$f" .md)-copy$k.md"
  done
done
export BENCH_CORPUS_DIR="$CORPUS"
pin_corpus_mtime

merge_compose
OUT="$(results_dir)"
trap teardown EXIT
runs=()
for W in $WORKER_COUNTS; do
  teardown
  up_base
  enqueue_corpus >/dev/null
  queued="$(psql_q "SELECT count(*) FROM jobs WHERE kind = 'ingest'")"
  blog "ingest: $queued documents queued; starting $W drain worker(s)"
  start="$(python3 -c 'import time; print(time.time())')"
  ids=()
  for i in $(seq 1 "$W"); do
    ids+=("$(compose run -d --no-deps ingest-worker \
      python -m driftline.ingest worker --drain --timeout 1800 --consumer "ingest-$i")")
  done
  codes="$(docker wait "${ids[@]}" | paste -sd, -)"
  end="$(python3 -c 'import time; print(time.time())')"
  for id in "${ids[@]}"; do docker logs "$id" 2>&1 | tail -n 2 >&2; docker rm "$id" >/dev/null; done
  docs="$(psql_q "SELECT count(*) FROM documents")"
  chunks="$(psql_q "SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")"
  missing="$(psql_q "SELECT count(*) FROM chunks WHERE embedding IS NULL")"
  failed="$(psql_q "SELECT count(*) FROM jobs WHERE kind = 'ingest' AND status <> 'succeeded'")"
  oom="$(oom_killed)"
  run="$(python3 -c "
import json
s = $end - $start
print(json.dumps({'workers': $W, 'documents': $docs, 'chunks': $chunks,
  'chunks_missing_embedding': $missing, 'jobs_not_succeeded': $failed,
  'exit_codes': '$codes', 'seconds': round(s, 2), 'docs_per_min': round($docs / s * 60, 2),
  'chunks_per_min': round($chunks / s * 60, 2), 'oom_killed': [x for x in '$oom'.split(',') if x]}))
")"
  blog "W=$W: $run"
  runs+=("$run")
done

python3 - "$OUT/ingest.json" "$COPIES" "${runs[@]}" <<'PY'
import json, sys
out, copies, *runs = sys.argv[1:]
json.dump({
    "corpus": f"{copies} copies of the 6 bench/corpus Markdown documents "
              "(headings suffixed per copy), upload connector",
    "extraction": "off (no LLM key)",
    "embedder": "TEI BAAI/bge-base-en-v1.5 on CPU, one replica",
    "timing": "enqueue first, then wall clock from starting W `worker --drain` containers "
              "until the last exits (includes ~container start-up)",
    "runs": [json.loads(r) for r in runs],
}, open(out, "w"), indent=2, sort_keys=True)
open(out, "a").write("\n")
PY
write_machine_json "$OUT/machine.json"
summarize readme "$OUT"
blog "wrote $OUT/ingest.json"
