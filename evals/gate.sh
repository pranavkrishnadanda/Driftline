#!/usr/bin/env bash
# The eval CI gate (spec section 12), shared by .github/workflows/eval.yml and local runs.
#
#   evals/gate.sh run OUT_DIR SHA           run driftline and plain_rag on both gate subsets
#   evals/gate.sh compare BASE_DIR OUT_DIR SHA
#                                           gate OUT_DIR/SHA/<corpus>.<system>.json against
#                                           BASE_DIR/<corpus>.<system>.json; Markdown on stdout
#   evals/gate.sh baseline SHA              refresh evals/reports/gate/ from a local run
#
# Needs a database loaded from evals/snapshot/gate.snapshot.gz (DRIFTLINE_DATABASE_URL),
# the TEI embedder (DRIFTLINE_EMBED_URL), and DRIFTLINE_LLM_OFFLINE=true: the offline
# extractive LLM, so the gate is free and needs no key. It measures retrieval, the as-of
# filter and the citation machinery.
#
# The gate runs WITHOUT the cross-encoder reranker (RRF order, the documented fallback):
# on CPU the reranker takes ~6 s per question, which would put the four runs at ~17 min
# before any setup. Without it they take well under a minute. The full results in
# evals/RESULTS.md use the reranker.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORPORA=(pharma k8s)
SYSTEMS=(driftline plain_rag)
TENANT=eval-golden

eval_cli() {
  uv run --project "$REPO/backend" python -m driftline.eval "$@"
}

run() {
  local out="$1" sha="$2"
  if [[ "${DRIFTLINE_LLM_OFFLINE:-}" != "true" ]]; then
    echo "the gate runs offline only: set DRIFTLINE_LLM_OFFLINE=true" >&2
    exit 2
  fi
  export DRIFTLINE_RERANK_URL="" # empty: reranking off, RRF order (see above)
  for corpus in "${CORPORA[@]}"; do
    for system in "${SYSTEMS[@]}"; do
      eval_cli run --corpus "$corpus" --system "$system" --tenant "$TENANT" \
        --cases "$REPO/evals/snapshot/$corpus.jsonl" --reports-dir "$out" --git-sha "$sha"
    done
  done
}

compare() {
  local base="$1" out="$2" sha="$3" worst=0 code
  echo "# Eval gate (offline extractive LLM, gate subset)"
  echo
  echo "Fails on a citation precision drop of more than 2 points or an outdated-citation"
  echo "rate rise of more than 1 point against the baseline committed on the base branch."
  echo
  for corpus in "${CORPORA[@]}"; do
    for system in "${SYSTEMS[@]}"; do
      code=0
      eval_cli compare --base "$base/$corpus.$system.json" \
        --head "$out/$sha/$corpus.$system.json" 2>&1 || code=$?
      echo
      if ((code > worst)); then worst=$code; fi
    done
  done
  if ((worst == 2)); then
    echo "**ERROR: a baseline report is missing or unusable; the gate cannot pass without it.**"
  fi
  return "$worst"
}

baseline() {
  local sha="$1" tmp
  tmp="$(mktemp -d)"
  run "$tmp" "$sha"
  mkdir -p "$REPO/evals/reports/gate"
  cp "$tmp/$sha"/*.json "$tmp/$sha"/*.md "$REPO/evals/reports/gate/"
  rm -rf "$tmp"
}

case "${1:-}" in
  run) run "$2" "$3" ;;
  compare) compare "$2" "$3" "$4" ;;
  baseline) baseline "$2" ;;
  *)
    echo "usage: $0 run OUT_DIR SHA | compare BASE_DIR OUT_DIR SHA | baseline SHA" >&2
    exit 2
    ;;
esac
