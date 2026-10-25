# P7 Evals + Bench Implementation Plan

> **For agentic workers:** executed by parallel subagents, one per task, each in its own git worktree. Follow the P3 Implementer protocol (`docs/superpowers/plans/2026-10-25-p3-retrieval-agent.md`): TDD; no mocks; unexpected errors are reported after one fix attempt of at most 15 minutes; **no Co-Authored-By or AI attribution in commits**; never read `.env`; latest stable versions, checked before pinning.

**Goal:** produce the headline numbers that make Driftline credible to a reviewer, and publish them:
- outdated-citation rate and citation precision vs. baselines;
- faithfulness;
- insufficient-evidence accuracy;
- p95 latency and throughput vs. worker count;
- zero lost jobs under chaos.

Publish them to GitHub Pages, and gate PRs on regressions.

**Architecture:**
- **Golden sets:** `evals/golden/{pharma,k8s}.jsonl` holds 150 questions each: question, `as_of`, expected answer, expected version ids and a `trap` flag. About ⅓ are "trap" questions whose answer changed between versions.
- **Eval runner:** `python -m driftline.eval run --corpus pharma --system driftline|plain_rag|no_retrieval`. It executes each question through the real system, scores it, writes `eval_runs` and `evals/reports/<sha>/<corpus>.json`, and renders Markdown.
- **Baselines:** `plain_rag` uses the same index with no temporal filter and no verifier; `no_retrieval` uses the LLM alone.
- **CI gate:** `eval.yml` runs on PRs using recorded cassettes, so it costs nothing and is deterministic.
- **Benchmarks:** k6 drives the gateway at 1, 4 and 8 agent workers, using a latency-distribution stub adapter so the numbers measure the system and not the provider quota. A chaos script kills workers at random during a load run, then the zero-lost-jobs check runs.
- **Pages site:** a static site built from `evals/reports` and `bench/results`, deployed by `pages.yml`.

**Spec:** `docs/superpowers/specs/2026-10-25-driftline-design.md` §12 (Evals, Benchmarks), §1 (headline numbers), §14 (week 6).

**Depends on:** P3 and P4 merged. P6 skill packs are needed for the with/without-pack ablation; if P6 isn't merged, skip the ablation and note it.

## Global Constraints
Same as P3, plus:
- **Never fabricate eval data or results.** Golden questions must come from the real ingested corpora: each expected version id and quote must exist in the DB, and the curation tooling (T1) verifies this. Benchmark numbers come only from real runs; the report records the machine, the commit and the worker counts.
- The bench stub adapter is a real `LLMProvider` implementation in `backend/src/driftline/llm/adapters/latency.py`. It has a seeded log-normal latency and deterministic text. It is not a mock, and it is labelled "stub LLM" in every bench report.

## Review Focus
1. **A golden question whose expected version no longer exists** after re-ingest: the runner marks it `stale_case` and excludes it from the metrics, with the count reported. It never scores it as a model failure. Owner: T2.
2. **Ties and partial citations:** precision counts only citations whose version is in force at `as_of` *and* whose quote is supported. Partial overlap with an expected version doesn't count. Owner: T2 (metric unit tests).
3. **The CI eval with a missing cassette** must fail loudly in CI (record mode none). Skipping would hide regressions. Owner: T4.
4. **A worker killed mid-job during the bench:** the job completes on another worker (XAUTOCLAIM), and the bench asserts that the `jobs` table has 0 rows stuck in `running` after a drain timeout. Owner: T5.
5. **A Pages build with no previous results** (first run) renders an empty-state section, never a crash. Owner: T6.

---

## Wave 0 (1 agent): Task 0, eval foundation
- Create `backend/src/driftline/eval/{__init__,types.py}`:
  - `GoldenCase {id, corpus, question, as_of, expected_answer, expected_version_ids, expected_quotes, trap: bool}`;
  - `CaseResult`;
  - `EvalReport {system, corpus, git_sha, metrics, cases}`.
- Create `backend/src/driftline/llm/adapters/latency.py` (`LatencyStubAdapter(seed, median_ms, sigma)`), and register it as the router chain option `bench` behind `settings.llm_bench=True`.
- Tests: `backend/tests/eval/test_types.py` and `backend/tests/llm/test_latency_adapter.py` (a seeded distribution is reproducible and the median is within ±10% over 1,000 draws, using `ManualClock`-driven sleeps or measuring the requested delays without real sleeping).
- Commit `feat(p7): eval types and latency stub adapter`.

## Wave 1 (3 agents in parallel)

### Task 1: golden-set curation tooling and the sets
- Create `backend/src/driftline/eval/curate.py`:
  - `propose_cases(pool, corpus, n)` finds documents with ≥3 versions and sections that changed between versions (from `section_hashes`), and drafts trap and non-trap questions with Claude (extract tier, structured output), each tied to a real version id and quote;
  - `validate_case(pool, case)` checks that the versions exist, the quote is present in that version's chunks, and `as_of` falls inside the version window.
- CLI: `python -m driftline.eval curate --corpus pharma --n 150 --out evals/golden/pharma.jsonl`.
- **The sets are generated from the real ingested corpora** (run ingest first: openFDA labels with ≥3 versions, Kubernetes releases 1.20–1.36) and then validated.
  - Commit only validated cases.
  - Record generation cost and model in `evals/golden/README.md`.
  - If fewer than 150 valid cases come out of a corpus, commit what validated and report the shortfall. **Don't pad.**
- Tests: `backend/tests/eval/test_curate.py` (validation against seeded real DB rows; a cassette for the proposer).

### Task 2: metrics and the runner
- Create `backend/src/driftline/eval/metrics.py`, with pure functions:
  - `citation_precision`, `outdated_citation_rate`, `faithfulness` (from the verifier's claim results, plus an LLM judge on a sample; judge tier, cassette);
  - `insufficient_evidence_accuracy`;
  - `latency_p95`, `cost_per_answer`.
- Create `backend/src/driftline/eval/runner.py`:
  - `run(corpus, system, cases, deps) -> EvalReport`;
  - systems `driftline` (the full P3 graph), `plain_rag` (same retriever with `as_of` filtering disabled, no verifier, single draft) and `no_retrieval`;
  - `stale_case` handling;
  - writes `eval_runs` and the JSON report.
- Create `backend/src/driftline/eval/__main__.py` with `run` and `compare --base <sha>`.
- Tests: `backend/tests/eval/test_metrics.py` (hand-built cases, including the tie and partial cases) and `backend/tests/eval/test_runner.py` (a 5-case mini set on seeded data with DeterministicAdapter; `stale_case` exclusion).

### Task 3: k6 load test and chaos
- `bench/k6/ask.js` (latest k6) posts asks and follows the SSE to `final`, recording time-to-first-token and total latency.
- `bench/run.sh N` does three things:
  1. brings Compose up with `--scale agent-worker=N` and `DRIFTLINE_LLM_BENCH=true`;
  2. seeds and ingests the fixture corpus;
  3. runs k6 for 3 minutes and writes `bench/results/<sha>/workers-N.json`.
- `bench/chaos.sh` runs a load test while killing a random agent-worker every 20 s (`docker kill`), then asserts zero stuck or lost jobs with a SQL check through `docker compose exec postgres psql`.
- `bench/ingest.sh` measures documents/minute at 1, 2 and 4 ingest workers.
- Test: `backend/tests/bench/test_bench_summary.py` covers the summarizer (`bench/summarize.py`, which parses k6 JSON into p50/p95/throughput) using a real recorded k6 output file committed as a fixture.
- Run the bench for real at 1, 4 and 8 workers plus chaos, and commit the results with machine info.

## Wave 2 (2 agents in parallel)

### Task 4: eval CI gate
- `.github/workflows/eval.yml` runs on `pull_request`:
  - services for Postgres, Redis and TEI;
  - it restores the eval fixture DB (a `pg_dump` of the ingested eval corpora, committed via Git LFS **only if under 50 MB**; otherwise it re-ingests from cassettes);
  - it runs `python -m driftline.eval run` for both corpora in cassette mode (record mode none, so a missing cassette fails), then `compare --base main`;
  - it fails if citation precision drops by more than 2 points or the outdated-citation rate rises by more than 1 point;
  - it posts a summary to the job summary.
- Use the latest action majors.
- Record cassettes once locally with `uv run --env-file .env`, then scrub and leak-check them.
- Test: `backend/tests/eval/test_compare.py` covers the gate thresholds.

### Task 5: chaos assertion hardening
- Make `bench/chaos.sh` exit non-zero on any lost job.
- Add `backend/tests/integration/test_worker_kill.py`: start 2 in-process agent workers, kill one mid-job (cancel its task without acking), and assert the other completes the job via XAUTOCLAIM, using `ManualClock` to advance past the idle threshold.

## Wave 3 (1 agent): Task 6, GitHub Pages report site and README
- `reports/site/` is a static site generated by `python -m driftline.eval site`, using Jinja2 templates plus a small amount of vanilla JS. Charts are pre-rendered SVG from the report JSON. It shows:
  - headline metrics vs. baselines;
  - per-corpus tables;
  - trap-question breakdowns;
  - the bench charts (throughput and p95 vs. workers);
  - the chaos result;
  - the drift log from P4.
  It has an empty state when there are no results.
- `.github/workflows/pages.yml` runs on push to main: build the site, then `actions/upload-pages-artifact` and `actions/deploy-pages` (latest majors).
- README: the headline numbers table (taken from real reports and linked), architecture, screenshots from P5, and the demo-video link placeholder **only if the user provides a video**; otherwise omit it.
- Test: `backend/tests/eval/test_site.py`: the site builds from fixture reports and from an empty state.

**Final P7 gate:** the full suite; ruff; the no-mock grep; no AI attribution; push; CI, eval and Pages workflows green; the Pages URL reported to the user.

## Notes and follow-ups from Wave 0

- **Sandbox quirk:** worktree agents can't run a command containing the token `tests/eval`, because it's read as a shell `eval`. Name the test files explicitly (e.g. `tests/eval/test_types.py`), or run from the `tests` directory with `eval/test_x.py`.
- **T3 (bench):**
  - **Bench must win over offline.** `agents/__main__.py:build_agent_router` checks `llm_offline` before `build_router`, so with both set the bench stub never runs. Make `llm_bench` take precedence there.
  - **Per-worker seeds.** Every worker process with the same `llm_bench_seed` draws the same latency sequence. Derive a per-worker seed (`seed ^ hash(consumer)`) so workers aren't lock-stepped. Pin both with tests.
- **`GoldenCase` rules:** `as_of` is a `date`, `expected_version_ids` are UUIDs (non-empty unless `kind == "not_in_corpus"`), and `golden_from_seed` rejects unfilled seeds.
