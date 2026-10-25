#!/usr/bin/env bash
# Shared by bench/run.sh and bench/ingest.sh (sourced, not run).
#
# The bench stack is deploy/compose/docker-compose.yml + bench/compose.bench.yml
# (+ bench/compose.no-reranker.yml when BENCH_RERANKER=off), merged into one file so that
# bench/chaos.sh (which takes a single COMPOSE_FILE) sees the same stack. It runs as the
# Compose project "driftline-bench" on its own host ports, never a dev stack.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$ROOT/bench/.work"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-driftline-bench}"
export BENCH_CORPUS_DIR="${BENCH_CORPUS_DIR:-$ROOT/bench/corpus}"
export DRIFTLINE_GATEWAY_PORT="${DRIFTLINE_GATEWAY_PORT:-58010}"
export GATEWAY_URL="http://localhost:$DRIFTLINE_GATEWAY_PORT"
# No paid key is ever passed through, whatever the calling shell has set.
export DRIFTLINE_ANTHROPIC_API_KEY="" DRIFTLINE_GEMINI_API_KEY=""
BENCH_RERANKER="${BENCH_RERANKER:-on}"
TENANT="${TENANT:-demo}"
# bench/k6/build.sh output (k6 + xk6-sse) goes first on PATH, for chaos.sh too.
export PATH="$ROOT/bench/.bin:$PATH"

blog() { printf '[bench %s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

merge_compose() {
  mkdir -p "$WORK"
  docker volume create driftline-bench-models >/dev/null
  local files=(-f "$ROOT/deploy/compose/docker-compose.yml" -f "$ROOT/bench/compose.bench.yml")
  if [[ "$BENCH_RERANKER" == "off" ]]; then
    files+=(-f "$ROOT/bench/compose.no-reranker.yml")
  fi
  docker compose -p "$COMPOSE_PROJECT_NAME" "${files[@]}" config >"$WORK/compose.yml"
  export COMPOSE_FILE="$WORK/compose.yml"
}

compose() { docker compose -p "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_FILE" "$@"; }
psql_q() { compose exec -T postgres psql -U driftline -d driftline -v ON_ERROR_STOP=1 -tAc "$1"; }

teardown() {
  blog "tearing down $COMPOSE_PROJECT_NAME (down -v)"
  compose down -v --remove-orphans >/dev/null 2>&1 || true
}

# Base services: everything but the scaled workers. The reranker only when enabled.
up_base() {
  local services=(postgres redis embedder gateway outbox-relay)
  [[ "$BENCH_RERANKER" == "on" ]] && services+=(reranker)
  # Build every backend image (the scaled workers too) from this checkout first.
  compose build gateway outbox-relay ingest-worker agent-worker >&2
  blog "up: ${services[*]}"
  compose up -d --wait --wait-timeout 900 "${services[@]}" >&2
}

# Stable mtimes: the upload connector dates a version by its file's mtime.
pin_corpus_mtime() {
  find "$BENCH_CORPUS_DIR" -type f -name '*.md' -exec touch -t 202601010000 {} +
}

enqueue_corpus() {
  compose run --rm --no-deps -T ingest-worker python -m driftline.ingest enqueue \
    --tenant "$TENANT" --kind upload --config '{"root":"/data/bench-corpus"}' --discover
}

drain_ingest() {
  compose run --rm --no-deps -T ingest-worker \
    python -m driftline.ingest worker --drain --timeout "${1:-900}"
}

# Containers of this project the kernel OOM-killed (name list, comma-separated).
oom_killed() {
  local ids
  ids="$(compose ps -aq)"
  [[ -z "$ids" ]] && return 0
  # shellcheck disable=SC2086 # one id per word
  docker inspect -f '{{.Name}} {{.State.OOMKilled}}' $ids |
    awk '$2 == "true" {sub("^/", "", $1); print $1}' | paste -sd, -
}

# Snapshot of every container's memory and CPU, as a JSON array.
stats_json() {
  # shellcheck disable=SC2046 # one id per word
  docker stats --no-stream --format '{{json .}}' $(compose ps -q) |
    python3 -c 'import json,sys; print(json.dumps([{k: r[k] for k in ("Name","MemUsage","MemPerc","CPUPerc")} for r in map(json.loads, sys.stdin)]))'
}

git_sha() { git -C "$ROOT" rev-parse --short=12 HEAD; }

results_dir() {
  local dir
  dir="$ROOT/bench/results/$(git_sha)"
  mkdir -p "$dir"
  printf '%s' "$dir"
}

write_machine_json() {
  local out="$1"
  python3 - "$out" <<'PY'
import json, platform, subprocess, sys

def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None

info = {
    "os": f"{sh('sw_vers', '-productName')} {sh('sw_vers', '-productVersion')} "
    f"({platform.machine()})" if platform.system() == "Darwin" else platform.platform(),
    "cpu": sh("sysctl", "-n", "machdep.cpu.brand_string") or platform.processor(),
    "host_cpus": int(sh("sysctl", "-n", "hw.ncpu") or 0) or None,
    "host_ram_gib": round(int(sh("sysctl", "-n", "hw.memsize") or 0) / 2**30, 1) or None,
    "docker_client": sh("docker", "version", "-f", "{{.Client.Version}}"),
    "docker_server": sh("docker", "version", "-f", "{{.Server.Version}}"),
    "docker_compose": sh("docker", "compose", "version", "--short"),
    "k6": sh("k6", "version").splitlines()[0] if sh("k6", "version") else None,
}
colima = sh("colima", "list", "--json")
if colima:
    vm = json.loads(colima.splitlines()[0])
    info["colima_vm"] = {
        "cpus": vm.get("cpus"),
        "memory_gib": round(vm.get("memory", 0) / 2**30, 1),
        "disk_gib": round(vm.get("disk", 0) / 2**30, 1),
        "arch": vm.get("arch"),
        "runtime": vm.get("runtime"),
    }
mem = sh("docker", "info", "-f", "{{.MemTotal}} {{.NCPU}} {{.KernelVersion}}")
if mem:
    total, ncpu, kernel = mem.split()
    info["docker_vm_visible"] = {
        "mem_gib": round(int(total) / 2**30, 2), "cpus": int(ncpu), "kernel": kernel,
    }
json.dump(info, open(sys.argv[1], "w"), indent=2, sort_keys=True)
open(sys.argv[1], "a").write("\n")
PY
}

summarize() { uv run --project "$ROOT/backend" python -m driftline.bench "$@"; }
