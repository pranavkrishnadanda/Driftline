#!/usr/bin/env bash
# Chaos run: load the gateway with asks while `docker kill`-ing a random agent-worker
# every KILL_EVERY seconds, then wait for the backlog to drain and check that no ask was
# lost (spec section 3, P7 review focus 4). Exits non-zero on any lost or stuck job.
#
# Expects the Compose stack to be up already (bench/run.sh N brings it up with
# DRIFTLINE_LLM_BENCH=true and seeds the corpus). Load comes from bench/k6/ask.js when
# both it and k6 exist; otherwise from a plain curl loop posting asks.
#
# Checks, over the asks created during this run (jobs.created_at >= the run's start):
#   - none still `running` or `queued` after DRAIN_TIMEOUT seconds   (stuck)
#   - none `failed`, and every `succeeded` one has its answer row     (lost)
#   - the `agent-workers` group has no pending entries, and dlq:agent is empty
#
# Env: DURATION (180), KILL_EVERY (20), DRAIN_TIMEOUT (300; reclaim needs 60 s idle),
#      ASK_INTERVAL (0.2, curl loop only), TENANT (demo), GATEWAY_URL, COMPOSE_FILE.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/deploy/compose/docker-compose.yml}"
DURATION="${DURATION:-180}"
KILL_EVERY="${KILL_EVERY:-20}"
DRAIN_TIMEOUT="${DRAIN_TIMEOUT:-300}"
ASK_INTERVAL="${ASK_INTERVAL:-0.2}"
TENANT="${TENANT:-demo}"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:${DRIFTLINE_GATEWAY_PORT:-8010}}"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
psql_q() { compose exec -T postgres psql -U driftline -d driftline -v ON_ERROR_STOP=1 -tAc "$1"; }
redis_q() { compose exec -T redis redis-cli "$@"; }
log() { printf '[chaos %s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

LOAD_PID=""
# shellcheck disable=SC2329 # invoked by the EXIT trap
cleanup() {
  if [[ -n "$LOAD_PID" ]] && kill -0 "$LOAD_PID" 2>/dev/null; then
    kill "$LOAD_PID" 2>/dev/null || true
    wait "$LOAD_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

curl_load() {
  local end=$((SECONDS + DURATION)) n=0
  while ((SECONDS < end)); do
    n=$((n + 1))
    curl -s -o /dev/null -X POST "$GATEWAY_URL/v1/ask" \
      -H 'Content-Type: application/json' \
      -d "{\"tenant\":\"$TENANT\",\"question\":\"chaos ask $n: how often should ALT be checked?\"}" \
      || true
    sleep "$ASK_INTERVAL"
  done
}

WORKERS="$(compose ps -q agent-worker | wc -l | tr -d ' ')"
if ((WORKERS < 2)); then
  log "need at least 2 running agent-workers (found $WORKERS); run bench/run.sh N first"
  exit 2
fi
START_TS="$(psql_q "SELECT now()")"
SINCE="created_at >= '$START_TS'::timestamptz AND kind = 'ask'"
log "start $START_TS: $WORKERS agent-workers, ${DURATION}s load, kill every ${KILL_EVERY}s"

if [[ -f "$ROOT/bench/k6/ask.js" ]] && command -v k6 >/dev/null 2>&1; then
  log "load: k6 bench/k6/ask.js"
  k6 run --quiet -e "BASE_URL=$GATEWAY_URL" -e "TENANT=$TENANT" \
    --duration "${DURATION}s" "$ROOT/bench/k6/ask.js" >&2 &
else
  log "load: curl loop (bench/k6/ask.js or k6 not found)"
  curl_load &
fi
LOAD_PID=$!

KILLS=0
END=$((SECONDS + DURATION))
while ((SECONDS + KILL_EVERY <= END)); do
  sleep "$KILL_EVERY"
  running=()
  while IFS= read -r id; do
    [[ -n "$id" ]] && running+=("$id")
  done < <(compose ps -q --status running agent-worker)
  if ((${#running[@]} == 0)); then
    log "no running agent-worker to kill"
    continue
  fi
  victim="${running[RANDOM % ${#running[@]}]}"
  docker kill "$victim" >/dev/null
  KILLS=$((KILLS + 1))
  log "killed agent-worker ${victim:0:12} (kill #$KILLS)"
  # Bring the dead container back (same hostname, so the same consumer name), keeping
  # the worker count steady; the others must reclaim what it held.
  compose up -d --no-recreate --scale "agent-worker=$WORKERS" agent-worker >/dev/null 2>&1
done
wait "$LOAD_PID" || log "load generator exited non-zero"
LOAD_PID=""

log "load done; draining (timeout ${DRAIN_TIMEOUT}s)"
DRAIN_END=$((SECONDS + DRAIN_TIMEOUT))
while :; do
  open="$(psql_q "SELECT count(*) FROM jobs WHERE $SINCE AND status IN ('running','queued')")"
  if ((open == 0)) || ((SECONDS >= DRAIN_END)); then
    break
  fi
  sleep 5
done

total="$(psql_q "SELECT count(*) FROM jobs WHERE $SINCE")"
succeeded="$(psql_q "SELECT count(*) FROM jobs WHERE $SINCE AND status = 'succeeded'")"
stuck="$(psql_q "SELECT count(*) FROM jobs WHERE $SINCE AND status IN ('running','queued')")"
failed="$(psql_q "SELECT count(*) FROM jobs WHERE $SINCE AND status = 'failed'")"
no_answer="$(psql_q "SELECT count(*) FROM jobs j WHERE j.$SINCE AND j.status = 'succeeded' \
  AND NOT EXISTS (SELECT 1 FROM answers a WHERE a.job_id = j.id)")"
dlq="$(redis_q XLEN dlq:agent | tr -d '\r')"
pending="$(redis_q XPENDING agent agent-workers | head -n 1 | tr -d '\r')"

log "asks=$total succeeded=$succeeded stuck=$stuck failed=$failed no_answer=$no_answer"
log "dlq:agent=$dlq agent-workers pending=${pending:-0} kills=$KILLS"
printf '{"asks":%s,"succeeded":%s,"stuck":%s,"failed":%s,"no_answer":%s,"dlq":%s,"pending":%s,"kills":%s}\n' \
  "$total" "$succeeded" "$stuck" "$failed" "$no_answer" "$dlq" "${pending:-0}" "$KILLS"

status=0
if ((total == 0)); then
  log "FAIL: no asks were created; the load never reached the gateway"
  status=1
fi
if ((stuck > 0)); then
  log "FAIL: $stuck asks stuck in running/queued after the drain:"
  psql_q "SELECT id, status, created_at FROM jobs WHERE $SINCE \
    AND status IN ('running','queued') ORDER BY created_at LIMIT 20" >&2
  status=1
fi
if ((failed > 0 || no_answer > 0)); then
  log "FAIL: lost asks (failed=$failed, succeeded without an answer=$no_answer):"
  psql_q "SELECT id, error FROM jobs WHERE $SINCE AND status = 'failed' LIMIT 20" >&2
  status=1
fi
if ((dlq > 0)); then
  log "FAIL: $dlq messages in dlq:agent"
  status=1
fi
if ((${pending:-0} > 0)); then
  log "FAIL: ${pending} entries still pending in agent-workers"
  status=1
fi
((status == 0)) && log "PASS: zero lost or stuck asks across $KILLS worker kills"
exit "$status"
