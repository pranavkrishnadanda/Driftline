# Driftline — Design Spec

**Date:** 2026-10-25
**Status:** Draft for review
**Owner:** solo developer

## 1. Summary

Driftline is a version-aware knowledge engine. You connect a document source and it:

1. **Tracks versions and supersession**: what changed, which document replaced which, and what was in force on any date.
2. **Answers questions with in-force citations only**, where every claim must be backed by an exact quote from a cited chunk.
3. **Watches for drift**: when a source changes, it re-checks the saved answers that cite it and pushes live alerts when they are no longer true.

The engine is domain-agnostic. Each domain is a tenant with its own connectors, skill pack and eval set.

### Goals
- A real, reproducible engineering system that demonstrates agentic AI (LangGraph, subagents, skills, MCP), RAG, LLM pipelines, guardrails, observability, evals and distributed processing.
- Headline, reproducible numbers: outdated-citation rate and citation precision vs. baselines, drift events caught on real dates, p95 latency and throughput vs. worker count.
- Zero recurring infrastructure cost: runs locally with Docker Compose. GitHub Actions and GitHub Pages provide the scheduled jobs and the public reports.

### Non-goals (v1)
- Public always-on hosted deployment, user accounts or billing.
- More than two built-in corpora (RBI/SEBI is planned for v2).
- Legal, medical or compliance advice. The UI carries a disclaimer.

## 2. Scope (v1)

| Corpus | Source | Version key |
|---|---|---|
| Pharma / healthtech | openFDA drug label API | `set_id` + `version`; `effective_time` → `valid_from` |
| Software | `kubernetes/website` docs + deprecation guides | Release branch (`v1.28`…`v1.31`) and commit date |
| Bring your own | Upload a folder of Markdown/PDF/DOCX, or connect a Git repo | Re-upload of the same path creates a new version |

## 3. Architecture

Approach: **modular monolith with a worker fleet**. One Python codebase with modules `gateway`, `ingest`, `index`, `agents`, `drift`, `eval`, `llm`, deployed as separate processes that communicate through Redis Streams.

```
Next.js (TS) ──REST+SSE──► FastAPI gateway ◄── MCP clients (Claude Code / Cursor)
                               │  enqueue / subscribe
                         Redis Streams (ingest, embed, agent, drift, events:*, DLQ)
                         + token buckets (LLM quota) + semantic cache
                 ┌─────────────┼──────────────┐
            ingest ×N      agent ×N        drift scheduler
                 └─────────────┼──────────────┘
                  Postgres 16 + pgvector  ·  Langfuse (self-hosted)
GitHub Actions: nightly drift watch · eval CI gate · k6 load test → GitHub Pages
```

### Processes
- **gateway**: FastAPI (async; asyncpg, redis.asyncio). Handles auth (API key per tenant), per-tenant rate limits, backpressure, SSE relay and the MCP server.
- **ingest worker**: fetch → hash → parse (LlamaIndex readers) → section diff → supersession extraction (LLM) → chunk → embed.
- **agent worker**: runs the LangGraph answer graph and publishes events.
- **drift scheduler**: polls sources on schedule, consumes `drift` events and re-verifies watched answers.
- **outbox relay**: moves committed outbox rows into Redis Streams.

### Distributed-processing guarantees
- Redis Streams consumer groups. Stalled messages are reclaimed with `XAUTOCLAIM` after a 60 s idle time.
- Every handler is idempotent. Ingest is keyed on `(document_id, content_hash)`, and agent jobs on `job_id`.
- A message moves to `dlq:{stream}` after 3 failed deliveries.
- Transactional outbox: domain writes and event rows commit together, and the relay publishes at-least-once. Consumers dedupe on event id.
- Backpressure: `POST /v1/ask` returns 429 + `Retry-After` when the agent stream's pending count exceeds a configured threshold (default 200).
- Each worker type scales independently (`docker compose up --scale agent=8`). Kubernetes manifests are provided for running on `kind`.

## 4. LLM gateway (`llm` module)

Every model call goes through this module.

- **Provider adapters** behind one interface (`complete`, `stream`, `embed`, `structured`):
  - **Anthropic (Claude)**: live; the primary LLM provider.
  - **Open-source embeddings**: `BAAI/bge-base-en-v1.5` (768-dim, MIT), served by Hugging Face Text Embeddings Inference (TEI) as the `embedder` Compose service. This is the primary embedding provider.
  - **Gemini**: optional LLM and embedding fallback, enabled when a key with credits is present.
  - **OpenAI**: adapter planned, enabled by config.
- **Model tiers** are set in config, not code (defaults):
  - `extract`: `claude-haiku-5-5`.
  - `answer` and `judge`: `claude-sonnet-5-5`.
  - `embed`: `bge-base-en-v1.5` via TEI.
- **Fallback chain** per tier, e.g. Claude Sonnet → Claude Haiku → Gemini if configured.
- **Circuit breaker** per (provider, model): opens after 5 consecutive failures or a 50% error rate over 30 s. Half-open retry after 30 s.
- **Retries**: exponential backoff with jitter. Up to 3 attempts for retryable errors (429, 5xx, timeouts).
- **Quota-aware rate limiting**: a Redis token bucket (requests/min and tokens/min) per model, shared by all workers. Callers wait in the queue rather than fail.
- **Semantic cache**:
  - Key: question embedding similarity ≥ 0.95 + tenant + as-of date + the set of in-force version ids.
  - Invalidated by drift events on any cited document.
- **Accounting**: tokens, cost and latency per call, tagged with tenant, job and graph node. Exported to Langfuse and to `/v1/stats`.
- The UI shows a "degraded" badge when a fallback model was used.

## 5. Agent design

### Answer graph (LangGraph `StateGraph`, Postgres checkpointer)

```
classify → plan ─┬→ retrieve → temporal_filter → rerank ─┐
                 └→ fan_out (Send) → subagents → merge ──┤
                                                         ▼
               insufficient_evidence ← verify_citations → respond
                        ▲                     │ fail (max 2)
                        └── re_retrieve ◄─────┘
```

- **classify**:
  - Determines intent, tenant/domain and `as_of` (defaults to today; parsed from the question, e.g. "in v1.28", "as of 2022").
  - Runs prompt-injection screening on user input.
- **plan**: decides single retrieval vs. fan-out for comparison or multi-part questions.
- **retrieve**: hybrid search, pgvector cosine + Postgres full-text, fused with reciprocal-rank fusion (k=60), top 30.
- **temporal_filter**: keeps only chunks from versions with `valid_from ≤ as_of < coalesce(valid_to, ∞)`, and drops versions that a `supersedes`/`deprecates` relation marks as replaced as of `as_of`.
- **rerank**: LLM-scored rerank down to the top 8. A cross-encoder can be swapped in via config.
- **subagents**: compiled subgraphs (retrieve → filter → draft), run in parallel with LangGraph `Send`. Each returns `{sub_question, findings[], citations[]}`.
- **draft**: structured output (Pydantic) where each sentence is a claim with chunk ids.
- **verify_citations** (guardrail):
  - Each claim is checked by an exact or near-exact quote match plus an LLM judge ("is this claim entailed by the quote?").
  - Unsupported claims trigger `re_retrieve` (at most 2 loops). After that they are dropped and flagged.
  - If fewer than 1 supported claim remains, the graph goes to `insufficient_evidence`, which returns the nearest sources.
- **respond**: `AnswerSchema {answer, claims[], citations[{chunk_id, version_id, quote}], as_of, confidence, degraded}`.
- **Human-in-the-loop**: watched answers with confidence < 0.6 call `interrupt()` and land in a review queue. Reviewer edits become eval cases.
- Every node publishes `step` events. The draft streams as `token` events, and verification results as `claim` events.

### Skills
- **Domain skill packs**: versioned directories `skills/<name>@<semver>/`, each containing:
  - `config.yaml`: retrieval parameters and chunking.
  - `glossary.yaml`
  - `prompts/` fragments
  - `eval.jsonl`
- The planner loads the tenant's pack. The eval report includes an ablation with and without the pack.
- The repo ships a **Claude Code Skill** (`.claude/skills/driftline/SKILL.md`) that teaches an agent to use the MCP tools.

### MCP server
Mounted on the gateway at `/mcp` (Streamable HTTP). Tools: `ask`, `diff_versions`, `get_timeline`, `watch_answer`, `list_sources`.

### Ingestion-side LLM pipeline
- **Supersession extraction**: a structured-output prompt over the new version and candidate documents (found by title/identifier similarity) returns `relations[{kind, target, evidence_quote, confidence}]`.
  - Relations with confidence ≥ 0.8 are applied.
  - Lower ones go to the review queue.
- **Injection guard**: ingested text is treated as data. Chunks containing instruction-like patterns are tagged, and their text is wrapped as quoted content in prompts.

## 6. Data model (Postgres + pgvector)

```
tenants(id, name, skill_pack, api_key_hash)
sources(id, tenant_id, kind, config jsonb, schedule, last_polled_at, status)
documents(id, source_id, external_id, title)               unique(source_id, external_id)
doc_versions(id, document_id, version_no, content_hash, valid_from, valid_to,
             raw_uri, diff_from_prev jsonb, created_at)     unique(document_id, content_hash)
chunks(id, version_id, ord, section_path, text, embedding vector(D), embed_model, tsv)
relations(id, src_version_id, dst_document_id, kind, evidence_chunk_id, confidence, status)
answers(id, tenant_id, question, as_of, body jsonb, confidence, watched, created_at)
answer_citations(answer_id, claim_idx, chunk_id)
drift_events(id, answer_id, old_version_id, new_version_id, verdict, detail jsonb, created_at)
review_items(id, kind, ref_id, payload jsonb, status)
jobs(id, tenant_id, kind, status, error, created_at, finished_at)
outbox(id, topic, payload jsonb, created_at, published_at)
eval_runs(id, git_sha, corpus, metrics jsonb, created_at)
```

- A new version closes the previous version's `valid_to` in the same transaction. A constraint guarantees that no two versions of a document have overlapping validity windows.
- Embeddings record `embed_model`. Changing the model triggers a background re-embed, and queries filter on the active model, so vectors from different models never mix.
- Indexes: HNSW on `embedding`, GIN on `tsv`, and btree on `(document_id, valid_from)`.

## 7. Drift engine

1. Ingest commits a new `doc_version` and an outbox row `version.created`.
2. The drift scheduler finds the watched answers whose citations point to the previous version.
3. For each affected claim, if its cited `section_path` is unchanged in `diff_from_prev`, the scheduler re-points the citation and stops there. Otherwise it re-runs the `verify_citations` subgraph against the new version.
4. It returns one of three verdicts:
   - `still_valid`: re-point silently.
   - `changed`: alert with a before/after diff.
   - `broken`: the cited text was removed. Regenerate the answer and put it into review.
5. The scheduler writes a `drift_events` row, publishes to `events:alerts:{tenant}`, and adds an entry to the drift log.

**Nightly GitHub Action** (`drift-watch.yml`, cron):
- Runs ingest for both corpora in the runner against the real sources.
- Commits `reports/drift-log.md` and a JSON of detected changes.
- Rebuilds the GitHub Pages site.

## 8. API and events

```
POST /v1/ask                      {question, as_of?, tenant} → 202 {job_id}
GET  /v1/jobs/{id}/events         SSE
POST /v1/answers/{id}/watch
GET  /v1/alerts/stream            SSE (per tenant)
GET  /v1/documents/{id}/timeline
POST /v1/sources                  connector config or multipart upload
GET  /v1/review                   POST /v1/review/{id}/resolve
GET  /v1/stats
GET  /healthz  /readyz
/mcp
```

**SSE contract** (Pydantic models; TypeScript types generated with `openapi-typescript`):
- `step {node, status, detail, t_ms}`
- `token {text}`
- `claim {idx, verified, citation}`
- `final {AnswerSchema}`
- `alert {drift_event}`
- `error {code, retryable}`

Every event carries a monotonically increasing `id`. On reconnect, `Last-Event-ID` replays missed events from the Redis stream. Heartbeats are sent every 15 s.

## 9. Frontend

Next.js (App Router) + TypeScript, Tailwind v4, shadcn/ui, TanStack Query.

**Views:**
1. **Ask**: chat with a live agent timeline. Nodes light up as they run, subagent branches appear in parallel, claims flip ✓/✗, and hovering a citation shows the exact quote.
2. **Version timeline**: versions on a time axis, side-by-side section diff, and a supersession graph (React Flow).
3. **Drift inbox**: live alerts with before/after and verdict; accept or send to review.
4. **Review queue**: low-confidence answers and relations.
5. **`/stats`**: corpus size, drift events over time, p95 latency, cost per answer, and eval scores vs. baselines.

**UI libraries and their responsibilities** (one owner per concern):

| Library | Responsibility |
|---|---|
| Motion (motion.dev) | All component-level animation: timeline node states, subagent branch expansion, claim ✓/✗, layout transitions, alert entry. |
| anime.js | Choreographed SVG sequences: supersession-graph edge drawing, version-timeline scrubber, landing hero. |
| Bklit UI | All `/stats` charts, installed via the `@bklit` shadcn registry. |
| Kokonut UI | Ask input, buttons, cards and text effects, installed via its shadcn registry. |

**Rules for agents building the UI:**
- Before writing UI code, fetch the current docs: motion.dev, animejs.com, Bklit and Kokonut UI (use `llms.txt` where available). Do not rely on remembered APIs.
- Install the Bklit skill: `npx -y skills add bklit/bklit-ui --agent claude-code`.
- Add components through their shadcn registries as source files, never as hand-copied snippets.
- Every animation honors `prefers-reduced-motion`.
- Never run Motion and anime.js on the same element.

"Coconut UI" in the original request means **Kokonut UI** (kokonut-labs/kokonutui) — confirmed.

## 10. Error handling

| Failure | Behavior |
|---|---|
| LLM error or quota exhausted | Retry with jitter → fall back to the next model → open the circuit breaker. Answer is marked `degraded`. |
| Worker crash mid-job | LangGraph resumes from the Postgres checkpoint, and `XAUTOCLAIM` hands the message to another worker. |
| Poison message | DLQ after 3 deliveries, an `error` event to the client, visible in the admin view. |
| Source fetch or parse failure | Exponential backoff. The source is marked `stale_source`, and answers citing it show a warning badge. |
| Insufficient evidence | Explicit refusal with the nearest sources. Never a guess. |
| SSE disconnect | Client reconnects with `Last-Event-ID`; missed events are replayed. |

## 11. Observability

- Langfuse (self-hosted in Compose) traces every graph run, node and LLM call, with cost.
- Structured JSON logs carry `trace_id`, `job_id` and `tenant`.
- Prometheus metrics endpoint: queue depth, pending/claimed counts, DLQ size, breaker state, cache hit rate.

## 12. Testing and evaluation

**Test policy (mandatory):**
- **TDD.** Every unit of behavior starts as a failing test, then gets the minimal implementation, then a refactor.
- **No mocking of real functions.** Test files must not use `unittest.mock`, `patch`, `MagicMock`, `monkeypatch` of project code, `jest.mock`/`vi.mock`, or any equivalent.
  - Tests exercise real code against real dependencies: Postgres and Redis via testcontainers, and a real FastAPI app via `httpx.AsyncClient`.
- **LLM calls in tests** use real provider responses recorded at the HTTP layer (VCR cassettes, re-recordable with `--record`). The adapter code still runs for real.
- `DeterministicAdapter` is a real implementation of the provider interface that ships in the codebase (`driftline.llm.adapters.deterministic`). It is not a mock.
  - Benchmarks use it.
  - Router tests use it to exercise retry, fallback and circuit-breaker paths, because provider outages can't be recorded on demand.
- Time-dependent code takes an injected `Clock`. Tests pass `ManualClock`, which is a real class in `driftline.clock`, rather than patching `time`.

**Tests:**
- **Unit** (pytest): temporal filter, diff, idempotency, token bucket, circuit breaker, SSE schemas, RRF fusion.
- **Integration** (testcontainers with Postgres + Redis): fixture corpus → ask → assert citations. Kill a worker mid-job and assert completion with zero lost jobs.
- **LLM**: recorded responses (VCR cassettes) keep CI deterministic and free. Contract tests cover all three adapters.
- **E2E** (Playwright): ask → live timeline → final answer; simulated drift → alert appears.

**Evals:**
- 150 golden questions per corpus (300 total). Each has an expected answer, expected source version ids and an `as_of` date. About ⅓ are "trap" questions whose answer changed between versions.
- **Metrics**: citation precision, outdated-citation rate, faithfulness (claim entailment), insufficient-evidence accuracy, p95 latency and cost per answer.
- **Baselines**: plain RAG on the same index (no temporal filter or verifier), and Gemini alone with no retrieval.
- **CI gate** (`eval.yml` on PR): fail if citation precision drops by more than 2 points or the outdated-citation rate rises by more than 1 point vs. `main`. Results publish to GitHub Pages on merge.

**Benchmarks:**
- k6 load test: throughput and p95 at 1, 4 and 8 agent workers. Ingest documents/minute vs. worker count.
- Chaos: kill workers randomly during a load run; assert zero lost jobs.
- LLM calls in benchmarks use a deterministic stub adapter (fixed latency distribution), so the numbers measure the system and not provider quota.

## 13. Repository layout

```
driftline/
  backend/            (uv; FastAPI, workers, llm, agents, ingest, drift, eval)
  frontend/           (Next.js + TS)
  skills/             (domain skill packs)
  .claude/skills/     (Claude Code skill for MCP usage)
  deploy/compose/     deploy/k8s/
  evals/              (golden sets, baselines, reports)
  bench/              (k6 scripts, chaos)
  .github/workflows/  (ci, eval, drift-watch, bench, pages)
  docs/
```

## 14. Milestones (~6 weeks, solo)

| Week | Deliverable |
|---|---|
| 1 | Repo, Compose stack, schema + migrations (Alembic), LLM gateway (Gemini + breaker + bucket), openFDA connector, ingest workers |
| 2 | Hybrid retrieval, temporal filter, base LangGraph graph, SSE contract and gateway relay |
| 3 | Citation verifier loop, subagent fan-out, Kubernetes docs connector, uploads, skill packs |
| 4 | Drift engine, outbox relay, watch/alerts, review queue, nightly drift Action |
| 5 | Frontend (Motion, anime.js, Bklit, Kokonut), MCP server, Claude Code Skill |
| 6 | Golden sets, eval CI gate, k6 + chaos benchmarks, GitHub Pages reports, README, demo video |

## 15. Risks

- **Gemini free-tier quota limits eval runs**: use cached cassettes in CI, run full live evals locally and in batches, and keep the token bucket strict.
- **openFDA label versions are uneven** (many labels have few versions): choose the eval set from labels with ≥3 versions and known safety-label changes.
- **Supersession extraction errors**: confidence threshold + review queue, and extraction precision is measured as its own eval.
- **Scope creep**: RBI/SEBI, hosted deployment and auth are explicitly v2.
