# Getting started

Prerequisites: Docker (Colima or Docker Desktop), [uv](https://docs.astral.sh/uv/) for running the backend outside Docker, [Bun](https://bun.sh) for the web app, and either an Anthropic API key or offline mode.

```bash
# 1. Configure ports and secrets (deploy/compose/.env is git-ignored)
cp deploy/compose/.env.example deploy/compose/.env
# Then add ONE of these lines to deploy/compose/.env:
#   DRIFTLINE_ANTHROPIC_API_KEY=<your key>     # answers with Claude
#   DRIFTLINE_LLM_OFFLINE=true                 # no key: deterministic offline answers

# 2. Start the stack: Postgres, Redis, TEI embedder + reranker, gateway and all workers
docker compose -f deploy/compose/docker-compose.yml up -d --build --scale ingest-worker=3

# 3. Check health (the gateway applies migrations before /healthz answers)
curl localhost:8010/healthz
curl localhost:8010/readyz
```

| Service | Host port | Env var to change it |
|---|---|---|
| Gateway (REST, SSE, `/mcp`, `/docs`) | `8010` | `DRIFTLINE_GATEWAY_PORT` |
| Postgres | `5433` | `DRIFTLINE_POSTGRES_PORT` |
| TEI embedder | `8080` | `DRIFTLINE_EMBED_PORT` |
| TEI reranker | `8081` | `DRIFTLINE_RERANK_PORT` |
| Redis | `6379` | fixed |

On amd64 hosts, set `DRIFTLINE_EMBED_IMAGE=ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.4` (the default TEI tag is the native arm64 one).

**Ingest documents.** `enqueue` creates the tenant if needed and queues one ingest job per document. `--discover` lists everything the source offers.

```bash
# Kubernetes docs: two files across two release branches
docker compose -f deploy/compose/docker-compose.yml exec ingest-worker \
  python -m driftline.ingest enqueue --tenant demo --kind git_docs --discover \
  --config '{"branches": ["release-1.35", "release-1.36"], "paths": ["content/en/docs/concepts/workloads/controllers/deployment.md"]}'

# Drug labels: openFDA discovery + DailyMed version history (here: the Lipitor label)
docker compose -f deploy/compose/docker-compose.yml exec ingest-worker \
  python -m driftline.ingest enqueue --tenant demo --kind openfda --discover \
  --config '{"search": "set_id:\"a60cc18b-0631-4cf0-b021-9f52224ece65\"", "limit": 1}'

# Your own files: copy them into the uploads volume first
docker compose -f deploy/compose/docker-compose.yml cp --index 1 ./my-docs/. ingest-worker:/data/uploads/
docker compose -f deploy/compose/docker-compose.yml exec ingest-worker \
  python -m driftline.ingest enqueue --tenant demo --kind upload --discover \
  --config '{"root": "/data/uploads"}'
```

The pinned sources that the nightly drift watch uses are in [`deploy/drift-watch/sources.json`](../deploy/drift-watch/sources.json), if you want a known-good set.

**Ask a question.** In dev mode (`DRIFTLINE_AUTH_REQUIRED` unset) the tenant name is enough. With an API key, send it as `Authorization: Bearer <key>`.

```bash
curl -s localhost:8010/v1/ask -H 'content-type: application/json' \
  -d '{"tenant": "demo", "question": "What does a Deployment rollout do?", "as_of": "2026-01-15T00:00:00Z"}'
# -> {"job_id": "...", "events_url": "/v1/jobs/<job_id>/events", "status_url": "/v1/jobs/<job_id>"}

curl -N localhost:8010/v1/jobs/<job_id>/events    # live SSE: step, token, claim ... final
```

The full API (ask, jobs, watch, drift events, alerts stream, document timeline, review, stats) is browsable at `http://localhost:8010/docs`. A checked-in copy is in [`contracts/openapi.json`](../contracts/openapi.json).

**Run the web app.**

```bash
cd frontend
bun install
bun run dev        # http://localhost:3000, talks to NEXT_PUBLIC_DRIFTLINE_API (default http://localhost:8010)
```

Pages: `/` (landing), `/ask` (live agent timeline and cited answer), `/timeline` and `/documents/[id]` (version history with diffs and the supersession graph), `/drift` (drift inbox), `/review` (review queue) and `/stats`. See [`frontend/README.md`](../frontend/README.md) for details.
