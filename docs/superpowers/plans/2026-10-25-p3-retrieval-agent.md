# P3 Retrieval + Agent Implementation Plan

> **For agentic workers:** this plan is executed by parallel subagents, one per task, each in its own git worktree. Follow the "Implementer protocol" below exactly. Steps use checkbox (`- [ ]`) syntax.

**Goal:** answer questions "as of" a date from in-force document versions only, with verified exact-quote citations, streamed live over SSE.

**Architecture:**
- Hybrid retrieval: pgvector HNSW and Postgres FTS, fused with RRF (k=60), filtered to versions whose `[valid_from, valid_to)` window contains `as_of`, then reranked by a TEI cross-encoder.
- A LangGraph answer graph (Postgres checkpointer) plans, fans out sub-questions to subagents with `Send`, retrieves, drafts with structured output, and verifies every citation, re-retrieving up to 2 times.
- `POST /v1/ask` queues a job on a Redis Stream. Agent workers run the graph and append events to a per-ask Redis Stream.
- `GET /v1/ask/{id}/events` streams those events over SSE, with `Last-Event-ID` replay, heartbeats and backpressure.

**Tech stack:** Python 3.12, FastAPI, LangGraph + `langgraph-checkpoint-postgres`, asyncpg/psycopg-pool, Redis Streams, pgvector, TEI (bge-base embeddings and `BAAI/bge-reranker-base` rerank), Anthropic Claude (Haiku extract, Sonnet answer/judge), OpenTelemetry (Langfuse-compatible, no-op without keys).

**Spec:** `docs/superpowers/specs/2026-10-25-driftline-design.md`: §5 retrieval and agent, §3 backpressure, §4 cache and providers, §8 SSE, §12 test policy.

**Reference implementation:** local branch `p3-reference` (commit `db46236`). The P3 planner wrote it and dry-ran it against real containers before it was stopped. It is **unreviewed** and must never be merged or pushed as-is. Read files from it with `git show p3-reference:<path>`. Dry-run status:

| Area | Status in reference |
|---|---|
| `tests/llm` (structured output, streaming, JSON stream) | 65 passed, 5 skipped |
| `tests/retrieval`, `tests/obs`, `tests/cache` | 25 passed |
| `tests/agents` | all passed; the Claude cassette test is skipped (no cassette yet) |
| `tests/integration` | 3 passed |
| `tests/gateway/test_ask_api.py` | **hangs** at `test_stream_limit_returns_503_and_unknown_job_404` |
| `tests/test_p3_fixtures.py` | **hangs** (suspected: reranker fixture start-up or model download) |
| `tests/test_heartbeat.py` | passes (already renamed from `test_health.py`, which clashed with `tests/gateway/test_health.py`) |

## Global Constraints

- TDD in every task: write or port the test, run it and watch it fail for the right reason, write or port the implementation, run it and watch it pass, then commit.
- **No mocks.** No `unittest.mock`, `MagicMock`, `monkeypatch` of our functions, or fake HTTP. Use real Postgres, Redis and TEI through testcontainers, `DeterministicAdapter` (a real in-repo provider), `ManualClock`, and vcrpy cassettes for Anthropic. Cassette tests skip only when the cassette is missing and the record mode is none.
- LLM tiers: extract `claude-haiku-5-5`; answer and judge `claude-sonnet-5-5`. Embeddings: TEI `BAAI/bge-base-en-v1.5`, 768-dim. Reranker: TEI `BAAI/bge-reranker-base`. If the reranker is unreachable, fall back to RRF order.
- Ports: Postgres 5433, gateway 8010, embedder 8080, reranker 8081, Redis 6379. Never touch the native Postgres on 5432 or the process on port 8000.
- Never read or print any `.env` file. Load keys only with `uv run --env-file .env`.
- **Commits: no `Co-Authored-By` trailer and no Claude/AI attribution of any kind.**
- Use the latest stable version of any new dependency. Verify it on PyPI; don't guess.
- Test env prefix (inline, never `export` in a shared shell): `DOCKER_HOST=unix:///Users/pranavkrishnadanda/.colima/default/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`
- Do not run `git gc`.

## Implementer protocol (every task)

1. Work only in your worktree, on branch `p3/tN-<name>` (`git branch -m p3/tN-<name>`). First rebase onto local `main`, which holds the merged earlier waves.
2. Touch only the files listed for your task. If you need another file, stop and report.
3. For each test file: port it from `p3-reference` (`git show p3-reference:backend/tests/... > ...`). Run it and confirm it fails because the implementation is missing (an ImportError or AttributeError naming the module). Then port the implementation and run it to green.
4. **Review while porting; don't copy blindly.** Check each module against the spec section named in your task. Check for: SQL injection (parameterised queries only), tenant isolation (every query filters `tenant_id`), unbounded loops, missing timeouts on network calls, swallowed exceptions, and any mock usage. Fix small issues test-first and list each one in your report.
5. **Errors:** the deliberate TDD red is expected. Any other failure, hang (>120 s for one test), or crash: you get **one** focused fix attempt of at most 15 minutes. If it is still failing, **stop and report**: the test name, the exact error (≤15 lines), and your hypothesis. The orchestrator will dispatch a fixer. Don't keep going.
6. Run each test command with a hard time limit: `perl -e 'alarm 300; exec @ARGV' uv run pytest ...`.
7. Gate before committing: your task's tests plus `uv run ruff check . && uv run ruff format --check .`, and `grep -rnE "unittest.mock|MagicMock|monkeypatch" tests src` must print nothing.
8. Commit with a plain message (`feat(p3): ...`, `test(p3): ...`) and **no trailer**. Do not push.
9. Report: branch, commit hash, test summary line, the review fixes you made, and anything you left unresolved.

## Review Focus (pinned by tests in the owning task)

1. **A client reconnects mid-stream with `Last-Event-ID`.** It gets only the missed events, in order, then live ones. If it is too far behind, it gets `events_expired`. Owner: T7 (`test_reconnect_with_last_event_id_replays_only_missed_events`, `test_client_too_far_behind_gets_events_expired`).
2. **A question dated before a rule changed** must cite the old version, never the in-force-today one. Owner: T8 (`test_question_dated_before_the_change_cites_the_old_version`).
3. **An empty corpus, or an `as_of` before any version** must return insufficient evidence, without drafting or spending LLM tokens. Owners: T2, T8.
4. **The LLM returns malformed or truncated JSON** for structured output: this is retried, then becomes a terminal error event, never a crash. Owner: T1 (`test_jsonstream`, router structured tests).
5. **Concurrent asks beyond `ask_max_pending`** get 429 with `Retry-After`. More SSE streams than `sse_max_connections` get 503. Owner: T7.

---

## Wave 0: shared foundation (1 agent)

### Task 0: shared deps, config, migration, fixtures, compose, heartbeat, shared types

**Files (port from `p3-reference`):**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (langgraph, langgraph-checkpoint-postgres, psycopg-pool, opentelemetry-api/sdk/exporter-otlp-proto-http). Run `uv lock` instead of copying the lock file, so versions resolve fresh.
- Modify: `backend/src/driftline/config.py` (the P3 settings block: rerank, retrieval, agent, cache, ask/SSE, heartbeat, Langfuse).
- Modify: `backend/src/driftline/db/migrate.py`. Create: `backend/migrations/versions/0003_agent.py`. Tests: `backend/tests/db/test_migration_0003.py`, `backend/tests/db/test_migration_0002.py` (2-line change).
- Modify: `backend/src/driftline/llm/types.py` (structured-output and streaming fields on the request and result types; T1 implements the behaviour).
- Create: `backend/src/driftline/retrieval/{__init__,types}.py`, `backend/src/driftline/agents/{__init__,schemas,events}.py`, `backend/src/driftline/cache/__init__.py`, `backend/src/driftline/obs/__init__.py`. Test: `backend/tests/agents/test_agent_contracts.py`.
- Create: `backend/src/driftline/health.py`. Modify: `backend/src/driftline/ingest/__main__.py` (heartbeat loop). Test: `backend/tests/test_heartbeat.py`.
- Modify: `deploy/compose/docker-compose.yml`:
  - a `reranker` service on 8081;
  - a scalable `agent-worker`;
  - heartbeat healthchecks for `ingest-worker`, `outbox-relay` and `agent-worker`;
  - `DRIFTLINE_ANTHROPIC_API_KEY: ${DRIFTLINE_ANTHROPIC_API_KEY:-}` on the gateway and every worker.
  Tests: `backend/tests/test_compose.py`, `backend/tests/test_config.py`.
- Modify: `backend/tests/conftest.py`, `backend/tests/conftest_db.py`, `backend/tests/dbseed.py`. Create: `backend/tests/conftest_reranker.py`, `backend/tests/livesrv.py`, `backend/tests/test_p3_fixtures.py`.

**Interfaces produced:** everything later tasks import from `driftline.retrieval.types` (`Evidence`, `RetrievalQuery`), `driftline.agents.schemas` (`AnswerSchema`, `PlanOutput`, `DraftOutput`, `AskRequest`, `AskJob`), `driftline.agents.events` (`ASK_EVENT_ADAPTER`, `StepEvent`, `TokenEvent`, `FinalEvent`, `ErrorEvent`, `is_terminal`), `driftline.llm.types` (P3 fields), the `Settings` P3 fields, and the fixtures `reranker_url`, `checkpointer`, `seed_history`, `VersionSeed`, `embed_all` and `livesrv.serve`. Keep every name exactly as in `p3-reference`.

**Known issue to fix in this task:** `tests/test_p3_fixtures.py` hangs in the reference. Check whether the reranker container's model download is the cause: run `docker run --rm ghcr.io/huggingface/text-embeddings-inference:cpu-arm64-1.9.4 --model-id BAAI/bge-reranker-base` once in the background and time it. If that's the cause, cache the model in a named volume or mount, and give the fixture a readiness wait of at most 300 s that fails loudly instead of hanging. The 15-minute protocol budget applies; report if the hang is still there after that.

- [ ] Step 1: port `test_agent_contracts.py`, `test_migration_0003.py`, `test_heartbeat.py`, the compose/config test additions and `test_p3_fixtures.py`. Run them and confirm they fail.
- [ ] Step 2: port the deps (`uv add` with the latest versions, then `uv lock`), config, migration, types, health, compose and fixtures.
- [ ] Step 3: run the Wave 0 tests, then the **full** existing suite. Expected: 185 + new tests pass, 2 skipped.
- [ ] Step 4: gate, then commit `feat(p3): shared foundation for retrieval and agent`.

**Wave 0 gate (orchestrator):** merge `p3/t0-foundation`, then run the full suite, ruff and the no-mock grep on `main`.

---

## Wave 1: building blocks (5 agents in parallel)

### Task 1: structured output and streaming in the LLM gateway (spec §4)
- Modify: `backend/src/driftline/llm/router.py`, `backend/src/driftline/llm/adapters/anthropic.py`, `backend/src/driftline/llm/adapters/deterministic.py`. Create: `backend/src/driftline/llm/jsonstream.py`.
- Tests: `backend/tests/llm/test_router_structured.py`, `backend/tests/llm/test_anthropic_structured.py` (cassette), `backend/tests/llm/test_jsonstream.py`, `backend/tests/llm/test_deterministic_adapter.py`.
- Must preserve the existing fallback, breaker, `release_probe` and rate-limit semantics: the existing `tests/llm` must stay green. Record the Anthropic structured cassette with `uv run --env-file .env pytest --record-mode=once ...`, then run `scrub_response_headers` and the leak check (no `sk-ant`, no org id, no cookies).
- Commit: `feat(p3): structured output and token streaming in the LLM router`.

### Task 2: hybrid retrieval and rerank (spec §5)
- Create: `backend/src/driftline/retrieval/hybrid.py`, `backend/src/driftline/retrieval/rerank.py`. Tests: `backend/tests/retrieval/test_hybrid_retrieval.py`, `backend/tests/retrieval/test_rerank.py`.
- Review: tenant filter on every query, as-of window `valid_from <= as_of < coalesce(valid_to, infinity)`, applied supersession hides the replaced document, and an unreachable reranker falls back to RRF order (tested against a real closed port).
- Commit: `feat(p3): hybrid pgvector + FTS retrieval with RRF, as-of filter and rerank`.

### Task 3: cost accounting and tracing
- Create: `backend/src/driftline/obs/cost.py`, `backend/src/driftline/obs/tracing.py`. Tests: `backend/tests/obs/test_cost.py`, `backend/tests/obs/test_tracing.py`.
- Review: tracing is a no-op without both Langfuse keys, and there are no network calls in tests.
- Commit: `feat(p3): per-ask cost accounting and OpenTelemetry tracing`.

### Task 4: persistent ask event log and SSE framing (spec §8)
- Create: `backend/src/driftline/agents/eventlog.py`, `backend/src/driftline/gateway/sse.py`. Test: `backend/tests/agents/test_eventlog.py`.
- Review: monotonically increasing event ids, MAXLEN trimming, TTL, and replay from an id.
- Commit: `feat(p3): Redis Stream event log with replay and SSE framing`.

### Task 5: semantic cache (spec §4)
- Create: `backend/src/driftline/cache/semantic.py`. Test: `backend/tests/cache/test_semantic_cache.py`.
- Review: keys are scoped to tenant, as-of bucket and corpus; the 0.95 threshold; invalidation when a cited version is superseded.
- Commit: `feat(p3): semantic answer cache with version-scoped invalidation`.

**Wave 1 gate:** merge T1–T5 in order, then run the full suite, ruff and the no-mock grep.

---

## Wave 2: agent parts and API (2 agents in parallel)

### Task 6: prompts, guardrails and the offline responder (spec §5, §6)
- Create: `backend/src/driftline/agents/prompts.py`, `backend/src/driftline/agents/guardrails.py`, `backend/src/driftline/agents/offline.py`, `backend/src/driftline/agents/llm.py`.
- Tests: `backend/tests/agents/test_prompts.py`, `backend/tests/agents/test_guardrails.py`, `backend/tests/agents/test_offline_responder.py`.
- Review: instruction-like chunks are quoted and can't close the evidence fence; the citation quote check is exact and runs against the cited in-force chunk.
- Commit: `feat(p3): prompts, citation guardrails and offline responder`.

### Task 7: `/v1/ask` API and the SSE contract (spec §3, §8)
- Create: `backend/src/driftline/gateway/ask.py`, `backend/src/driftline/gateway/contract.py`, `contracts/sse/ask-events.v1.json` (generated with `uv run python -m driftline.gateway.contract --write`). Modify: `backend/src/driftline/gateway/app.py`.
- Test: `backend/tests/gateway/test_ask_api.py`.
- **Known issue to fix:** the reference hangs at `test_stream_limit_returns_503_and_unknown_job_404`. A likely cause is the over-limit SSE connection being accepted and waiting forever, or a test client that never closes the streaming response. Every SSE test must read with a timeout (`asyncio.wait_for`) so it fails instead of hanging. The 15-minute budget applies; then report.
- Commit: `feat(p3): /v1/ask with SSE replay, heartbeats and backpressure`.

**Wave 2 gate:** merge T6, then T7; full suite, ruff and the no-mock grep.

---

## Wave 3: answer graph (1 agent)

### Task 8: LangGraph answer graph (spec §5)
- Create: `backend/src/driftline/agents/graph.py`. Tests: `backend/tests/agents/test_answer_graph.py`, `backend/tests/agents/test_answer_graph_claude.py` (cassette).
- Review:
  - `Send` fan-out is bounded by `max_subagents`;
  - the verifier loop is bounded by `max_verify_retries`;
  - the Postgres checkpointer is used;
  - an empty corpus short-circuits before drafting;
  - injected document text never changes behaviour (covered by the Claude cassette test).
- Record the Claude cassette as in T1, then scrub and leak-check it.
- Commit: `feat(p3): LangGraph answer graph with subagent fan-out and citation verifier`.

**Wave 3 gate:** merge, then full suite, ruff and the no-mock grep.

---

## Wave 4: worker and end to end (2 agents in parallel)

### Task 9: agent worker and CLI
- Create: `backend/src/driftline/agents/worker.py`, `backend/src/driftline/agents/__main__.py`. Test: `backend/tests/agents/test_agent_worker.py`.
- Review: a redelivered finished job is not rerun; an LLM outage produces a terminal error event; offline mode builds a keyless router; the heartbeat is wired.
- Commit: `feat(p3): agent worker consuming the ask stream`.

### Task 10: end-to-end ask test and Compose smoke test
- Create: `backend/tests/integration/test_ask_e2e.py`.
- Two versions of a document go through the P2 ingest pipeline, then an as-of question is asked for each date. Assert:
  - the citations point to the version in force on that date;
  - SSE replay with `Last-Event-ID` returns exactly the missed events.
- Then run a Compose smoke test:
  - `docker compose -f deploy/compose/docker-compose.yml up -d --build --scale agent-worker=2`;
  - every service is healthy;
  - one real `POST /v1/ask` plus SSE against an uploaded doc. Use `DRIFTLINE_LLM_OFFLINE=true` unless the Anthropic key is present in `deploy/compose/.env`; check that only with `grep -q`.
  Report what you observed, then run `docker compose ... down`.
- Commit: `test(p3): end-to-end as-of ask with SSE replay`.

**Final P3 gate:**
- On `main`: the full suite, ruff, the no-mock grep and the cassette leak check;
- `git log --format=%B | grep -ci co-authored` returns 0;
- push to `origin main`, and GitHub CI is green.

## Follow-ups from Wave 1 reviews (owned by later tasks)

- **T7:** if a client's `Last-Event-ID` is higher than the log's `last_id`, it currently gets only heartbeats until the job ends. Clamp it to `last_id` (and send `events_expired` if a gap is detected) instead. Pin this with a test.
- **T8:** do **not** store `insufficient_evidence` (uncited) answers in the semantic cache. With no cited versions they can never be invalidated, so newly ingested documents would be ignored until the TTL expires. Pin this with a test.
- **T9:** `obs.cost.job_cost(conn, job_id)` filters by `job_id` only. Add a `tenant_id` parameter and filter, and update the worker's call.
- **T8:** when `router.structured(..., on_delta=...)` repairs a bad reply, the caller gets the bad attempt's deltas and then the repair's. A `JsonStringFieldStreamer` that has already finished ignores the repaired answer. Reset the streamer (and emit a `step` event `{node: "draft", status: "retry"}` so the UI clears the partial text) on repair. Pin this with a test using `DeterministicAdapter`.
- **T8:** give `AnthropicAdapter` an explicit request timeout from settings (`llm_timeout_s`, default 120) instead of the SDK's 600 s default, and pin it with a test that checks the configured client's timeout.
- **T9:** a job row can stay `queued` forever if publishing to the agent stream fails after the insert. Add a reaper to the agent worker CLI (`python -m driftline.agents reap`, plus a periodic call in `worker`). It marks `queued` jobs older than `ask_queue_timeout_s` (default 300) with no stream entry as `failed`, and appends a terminal `error {code: "enqueue_lost"}` event. Test this with real Postgres and Redis by inserting a job row with no stream entry and using `ManualClock`.
- **P6 T0:** `GET /v1/jobs/{id}` and `/v1/jobs/{id}/events` look jobs up by id only. When API-key auth lands, scope both to the caller's tenant (404 on mismatch), and pin that with tests.
- **T9:** `build_router` in `llm/router.py` doesn't pass `settings.llm_timeout_s` to `AnthropicAdapter(timeout_s=...)`. Wire it, and move the timeout test from `tests/agents/test_answer_graph.py` to `tests/llm/test_anthropic_adapter.py`.
- **Final P3 gate:** the reranker container sometimes isn't ready in full-suite runs (`httpx.ConnectError` in `test_rerank.py`). Watch for it; if it recurs, harden `conftest_reranker.py` (wait on a real `/rerank` call, not just `/health`).
