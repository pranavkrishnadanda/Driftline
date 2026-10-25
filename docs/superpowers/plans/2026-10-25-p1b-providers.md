# P1b Providers Addendum: Claude LLM, Open-Source Embeddings, Port 5433

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Each task runs in its own git worktree as a parallel subagent. **Read `docs/superpowers/plans/2026-10-25-p1-foundation.md` "Global Constraints" first. They all still apply**: TDD, no mocking, `Co-Authored-By` trailer, never read or commit `.env`.

**Goal:** Make Claude the primary LLM provider and the open-source `bge-base-en-v1.5` on TEI the primary embedding provider, keep Gemini as an optional fallback, and move local Postgres to host port 5433.

**Why:** The Gemini project's prepaid credits are exhausted (HTTP 402), so Gemini-backed recording and runtime are blocked. The user chose Claude for LLM calls and open-source embeddings, with Gemini optional.

**Spec:** `docs/superpowers/specs/2026-10-25-driftline-design.md` §4 (updated).

## Global Constraints (in addition to P1)

**Defaults**
- Anthropic model IDs: `claude-haiku-5-5` (extract) and `claude-sonnet-5-5` (answer). Pin exact IDs; don't use aliases.
- Embedding model: `BAAI/bge-base-en-v1.5`. Output dimension is **768** (it must match `vector(768)`), and vectors are L2-normalised.

**Settings** (env prefix `DRIFTLINE_`, added by T13 only)
- `anthropic_api_key: str | None`
- `embed_url: str` (default `http://localhost:8080`)
- `model_extract`, `model_answer`, `model_fallback`, `model_embed`: updated defaults.

**Ports**
- Postgres host port is `DRIFTLINE_POSTGRES_PORT`, default **5433**. Port 5432 is taken by a native Postgres on the dev machine.
- Embedder host port is `DRIFTLINE_EMBED_PORT`, default **8080**.

**Recorded-HTTP tests**
- A cassette test whose cassette file is missing **while record mode is `none`** is *skipped* with the reason `cassette not recorded: <provider> credentials/credits required`. In any other record mode it runs for real.
- This is a skip, not a mock. The test executes real code the moment a cassette exists.
- Implement it once as the fixture `require_cassette` in `backend/tests/conftest_cassettes.py`, and register that file via `pytest_plugins` in `backend/tests/conftest.py` (T9).

## Execution Waves

| Wave | Tasks (parallel) | Notes |
|---|---|---|
| A | **T9, T10, T12** | T9 lands on `p1/t6-router` (which carries T5 and T6), then T5, T6 and T9 merge into `main`. T10 and T12 branch from `main`. |
| B | **T11** | Branches from `main` after Wave A merges (it edits compose, as T12 does). |
| C | **T13** | Needs T10 and T11. Wires `build_router` and config. |

The gate after each wave: on `main`, the full suite is green, with skips allowed only for missing cassettes.

---

### Task 9: Skip-when-cassette-missing, then merge the adapters and router (Wave A)

**Branch:** check out the existing `p1/t6-router`. It already contains T5 and T6.

**Files:**
- Create: `backend/tests/conftest_cassettes.py`
- Modify: `backend/tests/conftest.py` (add one line: `pytest_plugins = ["conftest_cassettes"]`)
- Modify: `backend/tests/llm/test_gemini_adapter.py` (each `@pytest.mark.vcr` test also uses the `require_cassette` fixture)

**Interfaces:**
- Produces fixture `require_cassette`. It resolves the cassette path pytest-recording uses for the requesting test (`<test dir>/cassettes/<module name>/<test name>.yaml`). It calls `pytest.skip(...)` when that file is missing and `request.config.getoption("--record-mode")` is `"none"`.
- Consumers: T10's Anthropic tests, and any future recorded test.

**Steps (TDD):**
1. Write `backend/tests/test_require_cassette.py`, using pytest's `pytester` (this needs `-p pytester`; enable it in that test module via `pytest_plugins = ["pytester"]`). It covers:
   - (a) a test using `require_cassette` with no cassette and record mode `none` → reported as skipped, with the reason text;
   - (b) the same test with an existing cassette file → it runs (passes);
   - (c) no cassette with `--record-mode=once` → it runs (here it fails, because the inner test asserts False, which proves it ran).

   Run it and watch it FAIL.
2. Implement the fixture and register it. Run the test and watch it PASS.
3. Apply it to the 3 Gemini recorded tests. `uv run pytest -q` → all pass, with exactly **2 skipped** (`test_complete_returns_text_and_usage` and `test_embed_returns_vectors_of_requested_dim`). The recorded 404 test still runs and passes.
4. Commit: `test(p1): skip recorded tests only when their cassette is missing`.

**Orchestrator then merges** `p1/t6-router` into `main`.

---

### Task 10: Anthropic adapter (Wave A)

**Before writing code:** invoke the `claude-api` skill to confirm the current `anthropic` Python SDK usage: async client, `messages.create`, the usage fields and the error classes.

**Files:**
- Modify: `backend/pyproject.toml` (add `anthropic`), `backend/uv.lock`
- Create: `backend/src/driftline/llm/adapters/anthropic.py`
- Test: `backend/tests/llm/test_anthropic_adapter.py`, plus cassettes

**Interfaces:**
- Consumes: `driftline.llm.types` and `driftline.clock`.
- Produces `AnthropicAdapter(api_key: str, *, clock: Clock | None = None)`, with `name = "anthropic"`:
  - `complete(model, request)`: system messages are joined into the `system` param; user and assistant messages map to Anthropic messages; `max_tokens = request.max_output_tokens`. Text is the concatenation of `text` content blocks, and usage maps from `input_tokens` / `output_tokens`.
  - Empty text → raise a non-retryable `ProviderError` mentioning `stop_reason`, via a pure helper `_result_text(message)`.
  - Errors: status 408, 409, 429, 5xx and 529 (overloaded), plus connection or timeout errors, raise a retryable `ProviderError(status=…)`. Other 4xx statuses raise a non-retryable one.
  - `embed(...)`: raise a non-retryable `ProviderError("anthropic does not provide embeddings")`.

**Tests (TDD):**
- `test_complete_returns_text_and_usage` (recorded): the reply contains "PONG", `provider == "anthropic"`, and `input_tokens > 0`.
- `test_unknown_model_is_non_retryable_provider_error` (recorded): status 404, `retryable is False`.
- `test_empty_response_raises_non_retryable` (offline): build a real SDK `Message` object with empty content and `stop_reason="max_tokens"`.
- `test_embed_is_unsupported` (offline).

Recorded tests use `require_cassette`, and `vcr_config` filters the `x-api-key` and `authorization` headers. T9 provides `require_cassette` on `main` only after Wave A. Since T10 runs in parallel, copy the fixture **verbatim** from the definition above into your branch's `backend/tests/conftest_cassettes.py`. The orchestrator resolves the duplicate at merge by keeping T9's version.

**Recording:**
- Only when `DRIFTLINE_ANTHROPIC_API_KEY` is non-empty in `/Users/pranavkrishnadanda/Downloads/driftline/backend/.env`. Check with `grep -q '^DRIFTLINE_ANTHROPIC_API_KEY=.\+'`, never print it.
- Load the key with `uv run --env-file <that path> pytest ... --record-mode=once`.
- Run both leak checks (header grep, then the literal key value) and the no-key replay.
- If the key is empty: commit without cassettes. The 2 recorded tests skip.

Commit: `feat(p1): Anthropic Claude adapter with recorded tests`.

---

### Task 11: Open-source embedder (Wave B)

**Files:**
- Modify: `deploy/compose/docker-compose.yml` (add the `embedder` service)
- Create: `backend/src/driftline/llm/adapters/tei.py`
- Test: `backend/tests/llm/test_tei_adapter.py`, plus a session fixture `embedder_url` in `backend/tests/llm/conftest.py`

**Step 0 (investigate, then report in the final report):**
- Check whether the official TEI CPU image runs natively on linux/arm64 (Colima on Apple Silicon): `docker manifest inspect ghcr.io/huggingface/text-embeddings-inference:<latest cpu tag>`.
- **If arm64 is available:** use TEI. Pin the exact tag and pass `--model-id BAAI/bge-base-en-v1.5`.
- **If not:** create `embedder/` (a FastAPI app using `sentence-transformers` with the same model) that exposes a **TEI-compatible** API: `POST /embed` with `{"inputs": [...], "normalize": true}` returns `[[float]]`, and `GET /health`. Build it with its own `embedder/Dockerfile` and `embedder/pyproject.toml`. The adapter is the same either way.

**Interfaces:**
- `TEIEmbeddingAdapter(base_url: str, *, timeout_s: float = 30.0)`, with `name = "tei"`:
  - `embed(model, texts, dim)` calls `POST {base_url}/embed`. It raises a non-retryable `ProviderError` if the returned dimension differs from `dim`. Connection errors and 5xx are retryable.
  - `complete(...)` raises a non-retryable `ProviderError("tei provides embeddings only")`.
- Compose: the `embedder` service maps `${DRIFTLINE_EMBED_PORT:-8080}:80` (or the fallback app's port), has a model cache volume, and a healthcheck on `/health`.

**Tests (TDD), against a real embedder container started by a testcontainers `DockerContainer` fixture (session-scoped, with a wait on `/health`):**
- `test_embed_returns_768_dim_unit_vectors`
- `test_similar_texts_score_higher_than_unrelated`: cosine("boxed warning: liver toxicity", "hepatotoxicity warning") > cosine(that first text, "kubectl rollout restart")
- `test_dimension_mismatch_raises_non_retryable` (ask for 384)
- `test_unreachable_embedder_is_retryable_provider_error` (`base_url` `http://127.0.0.1:1`)
- `test_complete_is_unsupported`

Mark the container tests `@pytest.mark.slow`, and register the marker in `pyproject.toml` (the only allowed edit to that file in this task). They still run by default and in CI.

Commit: `feat(p1): open-source bge-base embedder service and adapter`.

---

### Task 12: Postgres host port 5433 (Wave A)

**Files:** `deploy/compose/docker-compose.yml` (postgres `ports` only) and `deploy/compose/.env.example`.

**Steps:**
1. Failing check: `docker compose -p driftline-t12 -f deploy/compose/docker-compose.yml up -d postgres`. Wait for it to be healthy, then `pg_isready -h localhost -p 5433` (or a Python asyncpg connect to `localhost:5433` using the driftline credentials). It FAILS.
2. Change the mapping to `"${DRIFTLINE_POSTGRES_PORT:-5433}:5432"`, and add `DRIFTLINE_POSTGRES_PORT=5433` with a comment to `.env.example`.
3. Rerun the check: it passes. Confirm the gateway service still reaches Postgres on the internal `postgres:5432`: bring up the full stack and `curl localhost:8010/readyz`. Then `down -v`.
4. Commit: `chore(p1): default local postgres host port to 5433`.

---

### Task 13: Wire providers into `build_router` and config (Wave C)

**Files:** `backend/src/driftline/config.py`, `backend/src/driftline/llm/router.py` (`build_router` only), `backend/tests/test_config.py`, `backend/tests/llm/test_router.py`.

**Behavior:**
- Settings gain `anthropic_api_key: str | None = None` and `embed_url: str = "http://localhost:8080"`.
- Defaults become: `model_extract = "claude-haiku-5-5"`, `model_answer = "claude-sonnet-5-5"`, `model_embed = "BAAI/bge-base-en-v1.5"`, and `model_fallback` = `[]`.
- Gemini fallback is opt-in through `gemini_fallback_models: list[str] = ["gemini-3.8-flash"]`, used only when `gemini_api_key` is set.
- `build_router` chains:
  - `extract`: `[anthropic/haiku]`, plus Gemini fallbacks if the Gemini key is set.
  - `answer`: `[anthropic/sonnet, anthropic/haiku]`, plus Gemini fallbacks if set.
  - `embed`: `[tei/model_embed]`.
- Providers are registered only when their credentials or URL exist.
- `build_router` raises `ValueError` if no LLM provider key is set at all.
- Remove the old "Gemini key required" test and replace it with the new behavior.

**Tests (TDD):**
- `test_build_router_claude_primary_with_gemini_fallback`
- `test_build_router_without_gemini_has_no_gemini_routes`
- `test_build_router_requires_some_llm_key`
- `test_embed_tier_uses_tei`
- Config: the defaults match the values above, and no default contains `"2.5"`.

Commit: `feat(p1): Claude-primary routing with open-source embeddings and optional Gemini`.
