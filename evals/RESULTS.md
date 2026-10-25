# Eval results

All numbers below are copied from the report JSON files named in each section, exactly as
the runner produced them. Nothing was edited, rounded beyond 4 decimals, or dropped.
Driftline does not win every column: see the notes under each table.

## What was run

| | Real-Claude runs | Offline runs (CI gate baseline) |
|---|---|---|
| Date | 2026-10-25 | 2026-10-25 |
| Code | `e0c7cc1faecf51cee1428bd8d7ad76055f3b39b7` | `ce44d2b91109426c9ab416d7b58816da61b44d92` (same eval code; the later commit only adds these baselines) |
| Systems | `driftline`, `plain_rag` | `driftline`, `plain_rag` |
| LLM | answer and judge tiers `claude-sonnet-5-5`, extract (planner) `claude-haiku-5-5`, as configured. Fallbacks were configured, but `llm_calls` shows that only these primary models answered. | Offline extractive LLM: the in-repo `DeterministicAdapter` + `ExtractiveResponder`. No language model. |
| Cases | **Stratified sample, not the full set:** 40 pharma + 40 k8s | Same 40 + 40 (the CI gate subset) |
| Database | Full curation database: both corpora, 23 documents, 192 versions, 17,094 chunks. Restored from the golden-set curation `pg_dump`. | The gate snapshot (`evals/snapshot/gate.snapshot.gz`): 21 documents, 101 versions, 7,964 chunks |
| Retrieval | Hybrid retrieval, then the TEI `BAAI/bge-reranker-base` reranker | Hybrid retrieval in RRF order, **no reranker** (as in CI; see `evals/gate.sh`) |
| Reports | `evals/reports/e0c7cc1…/claude/` | `evals/reports/gate/` |

**Machine.** Apple M4 (10 cores, 16 GB), macOS 26.6.2. Postgres (pgvector pg16), Redis and
TEI 1.9.4 (`cpu-arm64`) ran in Docker inside a Colima VM with 4 vCPU and 5.8 GiB. Latency
numbers reflect that VM: on it, the CPU reranker alone takes about 2 to 7 s per call.

**The sample.** The cases come from `driftline.eval.snapshot.gate_subset(cases, 40)`. Each
`(kind, trap)` stratum gets one case, the rest are shared out in proportion, and cases
within a stratum are taken in sha256(id) order. This is the same subset the CI gate uses,
listed in `evals/snapshot/{pharma,k8s}.jsonl`:
- pharma: 13 traps, 20 stable `point_in_time`, 7 `current`;
- k8s: 13 traps, 23 stable `point_in_time`, 4 `current`.

The full golden sets have 150 cases per corpus. They were not all run with Claude because
of the $6 cost cap (see Cost below).

**Not run:**
- `no_retrieval`. The full-set offline runs of all three systems were started, then
  stopped for time. Their partial output was discarded.
- The faithfulness LLM judge (`--judge-sample`) in these runs. Its cassette test is
  `backend/tests/eval/test_judge_claude.py`.

## Metric definitions

From `backend/src/driftline/eval/metrics.py`:
- **Citation precision:** citations whose version was in force at `as_of` AND whose quote is
  supported by the cited chunk, divided by all citations. Pooled over all citations.
- **Outdated-citation rate:** citations of a real version that was not in force at `as_of`,
  divided by all citations.
- **Trap metrics:** the same two metrics over trap cases only. A trap is a question whose
  answer changed in the next version.
- **Faithfulness (verifier):** presented claims that pass the verifier's deterministic
  check, divided by all claims.
- **Insufficient-evidence accuracy:** cases answered when an answer is expected, or declined
  when the case expects insufficient evidence, divided by all cases. No golden case is
  `not_in_corpus`, so a correct case here is one that was answered.

**Stale and error cases.** A stale case is one whose expected version no longer exists. It
is excluded from the metrics and counted. An error case is a system failure. Both columns
are 0 in every run.

## Real Claude, stratified sample (40 + 40)

| corpus | system | cases | scored | stale | errors | citations | citation precision | outdated-citation rate | trap precision | trap outdated rate | faithfulness (verifier) | insufficient-evidence acc. | p95 latency (ms) | cost / answer (USD) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pharma | driftline | 40 | 40 | 0 | 0 | 57 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 0.9500 | 40597 | 0.0219 |
| pharma | plain_rag | 40 | 40 | 0 | 0 | 48 | 0.7917 | 0.2083 | 0.8889 | 0.1111 | 0.8000 | 0.7750 | 14286 | 0.0133 |
| k8s | driftline | 40 | 40 | 0 | 0 | 72 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 45052 | 0.0292 |
| k8s | plain_rag | 40 | 40 | 0 | 0 | 64 | 0.9688 | 0.0156 | 0.9500 | 0.0500 | 0.9667 | 0.9750 | 15135 | 0.0122 |

**Where the baseline wins:**
- Latency: Driftline's p95 is about 3× plain_rag's (plan, fan-out, verify, re-retrieve).
- Cost: Driftline costs about 1.6× (pharma) and 2.4× (k8s) per answer.
- Pharma insufficient-evidence accuracy: Driftline declined 2 of 40 answerable cases
  (`pharma-028`, `pharma-099`: "not enough in-force evidence").

**Where Driftline wins:**
- On k8s, the precision gap is small: plain_rag is 0.9688 against Driftline's 1.0000. The
  k8s pages change little between releases.

**Reranker timeouts.** The reranker timed out (10 s) and fell back to RRF order for 6
retrievals in pharma/driftline and 5 in k8s/driftline. There were none in the plain_rag
runs. This is the product's documented fallback, and it happened because the Colima VM is
slow, so those numbers include it.

## Offline extractive LLM, CI gate subset (40 + 40, snapshot DB, no reranker)

These are the committed baselines `.github/workflows/eval.yml` compares against
(`evals/reports/gate/`). They measure retrieval, the as-of filter and citation handling,
not a language model.

The extractive responder cites the first sentence of the top chunks. So plain_rag's
unfiltered retrieval shows up directly as outdated citations, which is why its numbers
here are far lower than with Claude.

| corpus | system | cases | scored | stale | errors | citations | citation precision | outdated-citation rate | trap precision | trap outdated rate | faithfulness (verifier) | insufficient-evidence acc. | p95 latency (ms) | cost / answer (USD) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pharma | driftline | 40 | 40 | 0 | 0 | 119 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 85 | 0.0000 |
| pharma | plain_rag | 40 | 40 | 0 | 0 | 112 | 0.2143 | 0.7857 | 0.1579 | 0.8421 | 0.2143 | 1.0000 | 123 | 0.0000 |
| k8s | driftline | 40 | 40 | 0 | 0 | 120 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 1.0000 | 75 | 0.0000 |
| k8s | plain_rag | 40 | 40 | 0 | 0 | 98 | 0.2653 | 0.7347 | 0.3889 | 0.6111 | 0.2653 | 1.0000 | 107 | 0.0000 |

**Determinism.** Two independent loads of the snapshot, each with a freshly built HNSW
index, gave identical reports. Every case, citation and metric matched; only latency
differed.

CI uses x86 TEI, whereas the baselines were made with arm64 TEI. A tiny embedding
difference could in principle move a near-tie, but this has not been observed yet.

## Baselines, exactly

- **`driftline`:** the full answer graph:
  1. plan (extract tier);
  2. sub-question fan-out;
  3. as-of-filtered hybrid retrieval and rerank;
  4. draft (answer tier);
  5. citation verification (judge tier) with up to 2 re-retrievals.

  The semantic cache is off.
- **`plain_rag`:** the same retriever and reranker with the as-of filter disabled
  (`in_force_only=False`), then one draft call. The draft uses the same system prompt,
  schema and model tier as Driftline. There is no planner, verifier or re-retrieval.

  Its prompt says only that the chunks "were retrieved for the question". The as-of filter
  never ran for it, so the prompt deliberately does not make Driftline's "only these chunks
  were in force then" claim (fixed in this change).

## Cost (actual, from `llm_calls`)

All Claude spend for this work came to **$4.687112**, summed from `llm_calls.cost_usd` for
eval jobs in the run database:

| phase | Sonnet draft | Sonnet judge (verifier) | Haiku plan | total |
|---|---|---|---|---|
| Estimate: 5 + 5 cases × 2 systems; the reranker had crashed (OOM), so the runs were discarded | $0.384702 | $0.048466 | $0.001226 | $0.434394 |
| Aborted pharma/driftline run; the reranker was still down, so the run was discarded | $0.980816 | $0.203504 | $0.006868 | $1.191188 |
| **Reported runs** (the table above) | $2.699986 | $0.350402 | $0.011142 | **$3.061530** |

**Projection behind the sample.** The estimate gave $0.0295 per case for driftline and
$0.0140 for plain_rag. At that rate the full 150 + 150 cases would cost about $13, so the
deterministic stratified sample above was run instead. A watchdog stopped all runs at
$5.90.

**Excluded.** Recording the judge cassette (2 Sonnet calls in a throwaway test database)
is not in `llm_calls`. It cost roughly $0.004, estimated from typical judge-call token
counts.

## Reproduce

1. Restore the curation dump into a fresh Postgres.
2. Rebuild the gate data:
   `uv run --project backend python evals/snapshot/build.py --dsn <dsn>`.
   It is byte-for-byte reproducible: the snapshot's sha256 is in `evals/snapshot/gate.manifest.json`.
3. Run the gate locally:
   ```
   python -m driftline.db.migrate
   python -m driftline.eval load-snapshot --path evals/snapshot/gate.snapshot.gz
   DRIFTLINE_LLM_OFFLINE=true evals/gate.sh run <out> <sha>
   ```
4. Refresh the baseline after an intended change: `evals/gate.sh baseline <sha>`.
