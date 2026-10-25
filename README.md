# Driftline

**A version-aware knowledge engine.** Driftline tracks every version of your documents, knows which version was in force on any date, answers questions only from in-force sources with exact-quote citations, and raises alerts when a source changes under an answer you already gave.

Regular RAG answers from whatever text it retrieves, including superseded text. Driftline answers "what was true *as of* this date", and shows its evidence.

It works across domains. v1 ships with two real corpora plus your own documents:

| Corpus | Source | How versions are tracked |
|---|---|---|
| Pharma / healthtech | openFDA (discovery) + DailyMed SPL history | Every published label version, `effective_time` → `valid_from` |
| Software | `kubernetes/website` release branches | One version per `release-1.N` branch, from the v1.N.0 release date |
| Bring your own | Markdown / PDF / DOCX folder | Re-uploading the same path creates a new version |

## Architecture

A modular monolith with a horizontally scalable worker fleet. Processes communicate through Redis Streams.

```
Next.js (TS) ──REST + SSE──► FastAPI gateway ◄── MCP clients
                                  │
              Redis Streams (ingest, embed, agent, drift, events, DLQ)
              + shared token buckets + semantic cache
                 ┌────────────────┼────────────────┐
            ingest ×N         agent ×N         drift scheduler
                 └────────────────┼────────────────┘
        Postgres 16 + pgvector (versions, chunks, HNSW, FTS, outbox)
                                  │
             LLM router ──► Anthropic Claude (Haiku / Sonnet)
                        ──► TEI embeddings (bge-base, open source)
```

**What is built so far:**

- **Temporal version store.** Each document version has a `[valid_from, valid_to)` window. A Postgres `btree_gist` exclusion constraint guarantees that windows never overlap. When a new version arrives, the previous one is closed in the same transaction. Re-ingesting identical content does nothing.
- **Distributed ingestion.**
  - Redis Streams consumer groups, with `XAUTOCLAIM` reclaiming jobs from crashed workers and a dead-letter queue after 3 failed deliveries.
  - A transactional outbox with `SKIP LOCKED`, so committed events are always published, even if the relay crashes partway.
  - Workers scale with `--scale ingest-worker=N`.
- **Processing pipeline.** Section-aware chunking (LlamaIndex `SentenceSplitter`, 256 tokens), section hashing for diffs, and batched embedding through a TEI server.
- **Supersession extraction.** Claude extracts "replaces / amends" links between documents. A link is applied automatically only when confidence is ≥ 0.8 *and* the quoted evidence really appears in the new version. Anything weaker goes to human review.
- **Resilient LLM gateway.**
  - Fallback chains per tier.
  - A circuit breaker: opens after 5 straight failures or a ≥50% error rate, then allows one half-open probe.
  - Retries with jitter.
  - A token-bucket rate limiter in Redis Lua, shared across workers.
  - A `degraded` flag when a fallback model answered.

## Tech stack

Python 3.12 · FastAPI · asyncpg · Redis Streams · Postgres 16 + pgvector · Alembic · LlamaIndex · Anthropic Claude · Hugging Face TEI (bge-base-en-v1.5) · Docker Compose · GitHub Actions · uv · ruff · pytest + testcontainers

Planned: LangGraph, MCP server, Next.js + TypeScript, Motion, anime.js, Kokonut UI, Bklit UI.

## Quick start

Prerequisites: Docker (Colima or Docker Desktop), [uv](https://docs.astral.sh/uv/), and an Anthropic API key.

```bash
# 1. Configure ports and secrets (deploy/compose/.env is git-ignored)
cp deploy/compose/.env.example deploy/compose/.env
# then add a line to deploy/compose/.env:  DRIFTLINE_ANTHROPIC_API_KEY=<your key>

# 2. Start the stack: Postgres, Redis, TEI embedder, gateway, workers
docker compose -f deploy/compose/docker-compose.yml up -d --build --scale ingest-worker=3

# 3. Check health
curl localhost:8010/healthz
curl localhost:8010/readyz

# 4. Ingest documents (files placed in the "uploads" volume)
docker compose -f deploy/compose/docker-compose.yml exec ingest-worker \
  python -m driftline.ingest enqueue --tenant demo --kind upload \
  --config '{"root": "/data/uploads"}' --discover
```

Default ports: gateway `8010`, Postgres `5433`, TEI `8080`, Redis `6379`. You can change them in `deploy/compose/.env`.

## Use from Claude Code / Cursor

The gateway serves an MCP server at `/mcp` (Streamable HTTP) with five tools: `ask` (a
cited answer as of a date or release), `list_sources`, `get_timeline`, `diff_versions`
and `watch_answer`. It needs a tenant API key as a bearer token. Create one, then
register the server:

```bash
export DRIFTLINE_KEY=<your tenant key>
claude mcp add --transport http driftline http://localhost:8010/mcp --header "Authorization: Bearer $DRIFTLINE_KEY"
```

The repo's Claude Code Skill (`.claude/skills/driftline/SKILL.md`) teaches the agent
when to use Driftline, to always pass `as_of` for historical questions, and how to read
citations. The [MCP guide](docs/mcp.md) covers creating API keys, the Cursor config,
`DRIFTLINE_MCP_ALLOWED_HOSTS` for Compose and remote hosts, a reference for every tool,
and troubleshooting (401, 421).

## Tests

The tests use **no mocks**. They run against real Postgres, Redis and TEI containers started by testcontainers, plus recorded Anthropic responses (vcrpy cassettes, scrubbed of keys and account IDs). Logic that depends on an LLM uses `DeterministicAdapter`, a real in-repo provider, and time-dependent logic uses an injected `ManualClock`.

```bash
cd backend
uv sync
uv run pytest -q          # 185 passed, 2 skipped (the 2 Gemini cassette tests need credits)
uv run ruff check . && uv run ruff format --check .
```

With Colima, point testcontainers at the socket:

```bash
DOCKER_HOST=unix://$HOME/.colima/default/docker.sock \
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock uv run pytest -q
```

CI (GitHub Actions) runs lint, format and the full test suite on every push.

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| P1 Foundation | Schema, Streams, rate limiter, breaker, router, gateway, CI | ✅ |
| P1b Providers | Anthropic, TEI embeddings, Gemini fallback | ✅ |
| P2 Ingestion | openFDA/DailyMed, Kubernetes docs, upload, version store, outbox, supersession | ✅ |
| P3 Retrieval + Agent | Hybrid search (pgvector + FTS + RRF), as-of filter, rerank, LangGraph agent with subagent fan-out, citation verifier, `/v1/ask` + SSE replay | 🚧 |
| P4 Drift + Review | Drift re-verification, alerts, human review queue | ⏳ |
| P5 Frontend | Next.js live agent timeline, version graph, drift inbox | ⏳ |
| P6 MCP + Skills | MCP server, domain skill packs | ⏳ |
| P7 Evals + Bench | Golden sets, baselines, load and chaos tests, public reports | ⏳ |

The design and plans are in [`docs/superpowers`](docs/superpowers).

## Disclaimer

Driftline is an engineering project. Its answers are not legal, medical or compliance advice.
