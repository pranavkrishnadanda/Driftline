#!/usr/bin/env bash
# bench/run.sh N: the ask load test at N agent workers (spec section 12, P7 task 3).
#
#   1. a fresh bench stack (project driftline-bench, `down -v` first) with N agent
#      workers on the stub LLM (DRIFTLINE_LLM_BENCH=true; no paid key reaches it);
#   2. the fixture corpus (bench/corpus) seeded through upload ingest and drained;
#   3. a WARMUP k6 run (discarded), then a DURATION k6 run of bench/k6/ask.js;
#   4. bench/results/<sha>/workers-N.json (+ raw k6 NDJSON, gzipped) and machine.json,
#      and the results README re-rendered.
#
# Env: VUS (4 x N), DURATION (180s), WARMUP (20s), BENCH_RERANKER (on|off),
#      BENCH_LLM_MEDIAN_MS (800), BENCH_LLM_SIGMA (0.5), BENCH_LLM_SEED (0),
#      KEEP_UP=1 leaves the stack up afterwards (bench/chaos.sh then runs against it).
set -euo pipefail
# shellcheck source=bench/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

N="${1:?usage: bench/run.sh N (agent workers)}"
VUS="${VUS:-$((4 * N))}" # 4 in flight per agent worker: each is kept busy, latency comparable
DURATION="${DURATION:-180s}"
WARMUP="${WARMUP:-20s}"
export BENCH_LLM_MEDIAN_MS="${BENCH_LLM_MEDIAN_MS:-800}" BENCH_LLM_SIGMA="${BENCH_LLM_SIGMA:-0.5}"
export BENCH_LLM_SEED="${BENCH_LLM_SEED:-0}"

if ! k6 version 2>/dev/null | grep -q xk6-sse; then
  blog "k6 with xk6-sse not found; building it (bench/k6/build.sh)"
  "$ROOT/bench/k6/build.sh" >&2
fi

merge_compose
teardown
[[ "${KEEP_UP:-0}" == 1 ]] || trap teardown EXIT

OUT="$(results_dir)"
pin_corpus_mtime
up_base
blog "seeding the fixture corpus via upload ingest"
enqueue_corpus >&2
drain_ingest 900 >&2
docs="$(psql_q "SELECT count(*) FROM documents")"
chunks="$(psql_q "SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")"
blog "corpus: $docs documents, $chunks embedded chunks"

blog "up: $N agent-worker(s)"
compose up -d --wait --wait-timeout 300 --scale "agent-worker=$N" agent-worker >&2

k6_run() { # duration, extra args...
  local duration="$1"
  shift
  k6 run --quiet -e "BASE_URL=$GATEWAY_URL" -e "TENANT=$TENANT" -e "VUS=$VUS" \
    -e "DURATION=$duration" "$@" "$ROOT/bench/k6/ask.js"
}

blog "warm-up: $WARMUP at $VUS VUs (discarded)"
k6_run "$WARMUP" >/dev/null 2>&1 || blog "warm-up k6 exited non-zero"
# Let the warm-up's in-flight asks finish so they do not count against the run.
for _ in $(seq 1 150); do
  open="$(psql_q "SELECT count(*) FROM jobs WHERE kind = 'ask' AND status IN ('queued','running')")"
  ((open == 0)) && break
  sleep 2
done

RAW="$WORK/workers-$N.ndjson"
blog "run: $DURATION at $VUS VUs, $N agent worker(s)"
(sleep "$(( ${DURATION%s} / 2 ))" && stats_json >"$WORK/stats-$N.json" 2>/dev/null) &
STATS_PID=$!
k6_status=0
k6_run "$DURATION" --out "json=$RAW" >&2 || k6_status=$?
wait "$STATS_PID" || true
gzip -9 -f "$RAW"

oom="$(oom_killed)"
[[ -n "$oom" ]] && blog "OOM-killed containers: $oom"
python3 - "$WORK/meta-$N.json" <<PY
import json, sys
stats = []
try:
    stats = json.load(open("$WORK/stats-$N.json"))
except (OSError, ValueError):
    pass
json.dump({
    "workers": $N,
    "llm": "stub LLM",
    "commit": "$(git_sha)",
    "k6_exit_code": $k6_status,
    "config": {
        "vus": $VUS, "duration": "$DURATION", "warmup": "$WARMUP",
        "reranker": "$BENCH_RERANKER", "semantic_cache": "off",
        "llm_median_ms": $BENCH_LLM_MEDIAN_MS, "llm_sigma": $BENCH_LLM_SIGMA,
        "llm_seed": $BENCH_LLM_SEED, "per_worker_seed": "seed ^ crc32(consumer)",
        "corpus": {"documents": $docs, "embedded_chunks": $chunks},
    },
    "oom_killed": [x for x in "$oom".split(",") if x],
    "container_stats_mid_run": stats,
}, open(sys.argv[1], "w"))
PY
summarize k6 "$RAW.gz" --meta "$WORK/meta-$N.json" --out "$OUT/workers-$N.json"
cp "$RAW.gz" "$OUT/k6-workers-$N.ndjson.gz"
blog "wrote $OUT/workers-$N.json"

if [[ "${CHAOS:-0}" == 1 ]]; then
  # bench/chaos.sh on this same stack: k6 load while a random agent-worker is killed every
  # KILL_EVERY s, then the zero-lost/stuck-jobs checks. Its JSON summary goes to chaos.json.
  blog "chaos: bench/chaos.sh against $N agent workers"
  chaos_status=0
  CHAOS_DURATION="${CHAOS_DURATION:-180}"
  chaos_json="$(VUS="$VUS" DURATION="$CHAOS_DURATION" GATEWAY_URL="$GATEWAY_URL" TENANT="$TENANT" \
    "$ROOT/bench/chaos.sh")" ||
    chaos_status=$?
  python3 - "$OUT/chaos.json" "$chaos_status" "$N" "$chaos_json" \
    "$CHAOS_DURATION" "${KILL_EVERY:-20}" <<'PY'
import json, sys
out, status, workers, summary, duration, kill_every = sys.argv[1:]
data = json.loads(summary.strip().splitlines()[-1]) if summary.strip() else {}
data.update(exit_code=int(status), workers=int(workers), llm="stub LLM",
            duration_s=int(duration), kill_every_s=int(kill_every))
json.dump(data, open(out, "w"), indent=2, sort_keys=True)
open(out, "a").write("\n")
PY
  blog "chaos exit $chaos_status: $chaos_json"
fi
write_machine_json "$OUT/machine.json"
summarize readme "$OUT"
