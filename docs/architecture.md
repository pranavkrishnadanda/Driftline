# Driftline architecture

Driftline is a modular monolith: one Python package, run as one HTTP gateway and a fleet of horizontally scalable workers. The processes never call each other directly. They share Postgres (the source of truth) and Redis (streams, caches and rate limits). Every service below is a real entry in [`deploy/compose/docker-compose.yml`](../deploy/compose/docker-compose.yml), except the web app, which runs on its own (`bun run dev`).

## 1. System overview

```mermaid
flowchart TB
  subgraph clients["Clients"]
    WEB["Next.js web app<br/>:3000"]
    MCPC["MCP clients<br/>Claude Code, Cursor"]
    REST["REST / SSE clients"]
  end

  GW["FastAPI gateway :8010<br/>/v1 REST + SSE, /mcp"]

  subgraph redis["Redis 7"]
    SING[["stream: ingest"]]
    SEMB[["stream: embed"]]
    SAG[["stream: agent"]]
    SDR[["stream: drift"]]
    SEV[["events:ask:{job}<br/>events:alerts:{tenant}"]]
    CACHE[("semantic cache<br/>+ token buckets")]
  end

  subgraph workers["Worker fleet"]
    POLL["drift-poll<br/>source scheduler"]
    IW["ingest-worker xN"]
    RELAY["outbox-relay"]
    AW["agent-worker xN<br/>LangGraph"]
    DW["drift-worker xN"]
  end

  PG[("Postgres 16 + pgvector<br/>versions, chunks, HNSW, FTS,<br/>answers, outbox, checkpoints")]

  subgraph models["Models"]
    EMB["TEI embedder<br/>bge-base-en-v1.5"]
    RR["TEI reranker<br/>bge-reranker-base"]
    ROUTER{{"LLM router"}}
    CLAUDE["Anthropic Claude<br/>Haiku / Sonnet"]
    OFF["Offline deterministic<br/>responder"]
  end

  subgraph ext["External sources"]
    FDA["openFDA / DailyMed"]
    K8S["kubernetes/website"]
    UP["uploads volume"]
  end

  WEB -->|"REST + SSE"| GW
  MCPC -->|"Streamable HTTP"| GW
  REST -->|"REST + SSE"| GW
  GW -->|"XADD ask job"| SAG
  GW -->|"read + replay"| SEV
  GW -->|"jobs, answers, review"| PG

  POLL -->|"due sources"| SING
  SING --> IW
  SEMB --> IW
  IW -->|"fetch"| ext
  IW -->|"versions, chunks, outbox"| PG
  IW -->|"embed"| EMB

  RELAY -->|"claim outbox rows"| PG
  RELAY -->|"version.created"| SEMB
  RELAY -->|"version.created"| SDR
  RELAY -->|"ask.resume / ask.regenerate"| SAG
  RELAY -->|"drift.alert"| SEV

  SAG --> AW
  AW -->|"step, token, claim, final"| SEV
  AW -->|"as-of search, answers"| PG
  AW -->|"lookup / store"| CACHE
  AW -->|"rerank"| RR
  AW --> ROUTER

  SDR --> DW
  DW -->|"verdicts, alerts"| PG
  DW --> ROUTER
  IW -->|"supersession"| ROUTER

  ROUTER -->|"extract / answer / judge tiers"| CLAUDE
  ROUTER -.->|"DRIFTLINE_LLM_OFFLINE=true"| OFF
```

How to read it:

- **The gateway is thin.** It authenticates the tenant, writes a `jobs` row, pushes work onto a stream and serves events. It never calls a model.
- **Streams carry work, Postgres carries truth.** Anything that must not be lost (a new version, a drift alert, a reviewer's decision) is first written to the `outbox` table in the same transaction as the change. The `outbox-relay` then publishes it to Redis. If the relay crashes, the row is simply published later.
- **Every worker type scales out.** Consumer groups split the work, `XAUTOCLAIM` takes over messages from a dead consumer after 60 s, and the 3rd failed delivery goes to `dlq:<stream>`. `drift-poll` needs only one replica: it claims each due source with a compare-and-set.
- **The LLM router** has four tiers. `extract` is Haiku (planning, supersession). `answer` is Sonnet, then Haiku (drafting). `judge` is Sonnet, then Haiku (claim checks). `embed` goes to TEI. Optional fallbacks come after these: extra Claude models, then Gemini when `DRIFTLINE_GEMINI_API_KEY` is set. With `DRIFTLINE_LLM_OFFLINE=true`, the agent and drift workers swap every LLM tier for the in-repo deterministic responder. Without an LLM key, the ingest worker still chunks and embeds, but skips supersession extraction.

## 2. The ask lifecycle

What happens between `POST /v1/ask` and the final answer, including a dropped connection:

```mermaid
sequenceDiagram
  autonumber
  participant C as Client (web, MCP, curl)
  participant GW as FastAPI gateway
  participant PG as Postgres
  participant AS as Redis stream "agent"
  participant W as agent-worker
  participant EV as Redis events:ask:{job}
  participant SC as Semantic cache (Redis)

  C->>GW: POST /v1/ask {tenant, question, as_of}
  GW->>AS: check backlog (429 + Retry-After if too deep)
  GW->>PG: INSERT jobs (status queued)
  GW->>AS: XADD AskJob
  GW-->>C: 202 {job_id, events_url}
  C->>GW: GET /v1/jobs/{job_id}/events (SSE)
  AS->>W: XREADGROUP (consumer group)
  W->>W: run answer graph (Postgres checkpointer)
  W->>SC: lookup (same tenant, as_of day, similarity >= 0.95)
  loop every graph step
    W->>EV: XADD step / token / claim event
    GW->>EV: read new events
    GW-->>C: SSE event with id
  end
  Note over C,GW: Connection drops. The browser reconnects with Last-Event-ID n
  C->>GW: GET events, Last-Event-ID: n
  GW->>EV: replay every event after n, then follow live
  W->>SC: store answer (cited, not waiting for review)
  W->>PG: INSERT answers + answer_citations, job succeeded
  W->>EV: XADD final
  GW-->>C: SSE final (answer, citations, confidence)
```

Notes:

- A cache hit skips the planner, retrieval and models entirely (step 9). Only cited answers that are not waiting for review are stored, and a hit is served only if every version it cites is still in force at the requested `as_of`.
- The event log is capped (10,000 events) and expires after 24 h. A client that asks for an expired range gets an `error` event with code `events_expired` instead of silent gaps. Heartbeats keep idle connections alive every 15 s.
- `GET /v1/jobs/{job_id}` returns the same final answer for clients that poll instead of streaming. The MCP `ask` tool uses the same job path and waits for the result.
- If a worker crashes mid-ask, another worker reclaims the stream entry and resumes from the last checkpointed node. A queued ask whose stream entry was lost is failed by the `reap` sweep (`enqueue_lost`), never left hanging.

## 3. The LangGraph answer graph

The real nodes and conditional edges of [`agents/graph.py`](../backend/src/driftline/agents/graph.py):

```mermaid
flowchart TD
  S(["START"]) --> classify["classify<br/>screen question, pick as_of"]
  classify -->|"refused or empty corpus"| respond
  classify -->|"ok"| cache["cache<br/>semantic lookup"]
  cache -->|"hit"| respond
  cache -->|"miss"| plan["plan<br/>split into sub-questions"]

  plan -->|"Send"| sub1["subagent 1<br/>as-of hybrid search + rerank"]
  plan -->|"Send"| sub2["subagent 2"]
  plan -->|"Send, up to 4"| subn["subagent N"]
  sub1 --> merge
  sub2 --> merge
  subn --> merge["merge evidence"]

  merge -->|"no evidence"| respond
  merge -->|"evidence"| draft["draft<br/>streams tokens"]
  draft -->|"malformed draft"| respond
  draft -->|"draft ok"| verify["verify<br/>quote in cited version?"]
  verify -->|"unsupported claims,<br/>attempts < 2"| re_retrieve["re_retrieve<br/>search for failed claims"]
  re_retrieve --> draft
  verify -->|"all supported or<br/>retries spent"| respond["respond<br/>answered or insufficient_evidence"]

  respond -->|"watched answer, or<br/>confidence < 0.6"| review["review<br/>interrupt() until a human decides"]
  respond -->|"otherwise"| E(["END"])
  review -->|"approve / edit / reject"| E
```

- **Insufficient evidence path.** If no claim survives verification (or there was no evidence or no valid draft), `respond` returns `status: insufficient_evidence` with the nearest in-force sources and `confidence: 0`. It never returns an unverified answer.
- **Confidence** is the share of claims that verified, scaled by 0.9 when a fallback model answered (`degraded`).
- **Review.** When the graph pauses at `review`, the worker opens a `low_confidence_answer` review item and marks the job `needs_review`. The reviewer's decision is written to the outbox as `ask.resume`, the relay puts it on the `agent` stream, and a worker resumes the same thread from its checkpoint.

## 4. Ingestion, outbox and drift detection

```mermaid
flowchart LR
  subgraph ingest["ingest-worker: stream ingest"]
    ENQ["drift-poll or CLI enqueue"] -->|"XADD ingest"| FETCH["connector fetch<br/>openFDA/DailyMed, k8s git, upload"]
    FETCH --> HASH["hash content<br/>+ per-section hashes"]
    HASH --> CHUNK["section-aware chunks<br/>256 tokens"]
  end

  subgraph tx["one Postgres transaction"]
    CLOSE["close previous version<br/>set valid_to"] --> INS["insert doc_version + chunks"]
    INS --> OBX["outbox row<br/>version.created"]
  end

  CHUNK --> CLOSE
  CHUNK -.->|"same as current version"| NOOP["no-op"]
  OBX --> RELAY["outbox-relay<br/>SKIP LOCKED"]
  RELAY -->|"XADD embed"| EMBED["ingest-worker: embed via TEI<br/>+ supersession extraction"]
  RELAY -->|"XADD drift"| ENGINE["drift-worker: drift engine"]
  EMBED -.->|"confidence < 0.8 or<br/>quote not found"| RQ

  ENGINE --> DIFF{"cited section:<br/>cited vs latest version"}
  DIFF -->|"unchanged, or changed<br/>but quote still verifies"| SV["still_valid<br/>re-point citation"]
  DIFF -->|"changed, quote fails"| CH["changed<br/>+ before/after diff"]
  DIFF -->|"section removed"| BR["broken"]

  CH --> ALERT["outbox row<br/>drift.alert"]
  BR --> ALERT
  BR --> RQ["review queue<br/>review_items"]
  ALERT -->|"relay"| ALOG[["events:alerts:{tenant}"]]
  ALOG --> SSE["GET /v1/alerts/stream<br/>SSE drift inbox"]
  RQ --> RES["POST /v1/review/{id}/resolve"]
  RES -->|"outbox ask.regenerate<br/>or ask.resume"| AGENT[["stream: agent"]]
  RES -->|"outbox cache.invalidate"| CINV["drop cached answers<br/>citing replaced versions"]
```

- **Exactly one version per change.** `upsert_version` compares the new content with the current version. If they match, nothing happens. Otherwise it closes the old window, inserts the new version and its chunks, and writes the `version.created` outbox row, all in one transaction. Reverting to older content creates a new version, too.
- **Fan-out.** `TOPIC_STREAMS` in [`ingest/outbox.py`](../backend/src/driftline/ingest/outbox.py) maps `version.created` to the `embed` and `drift` streams, and `ask.resume` / `ask.regenerate` to `agent`. `drift.alert` goes to the tenant's alert log, and the relay applies `cache.invalidate` directly.
- **The drift engine** compares each cited section between the cited version and the document's **latest** version, so a worker that falls behind (v1, v2, v3) evaluates once, against v3. All writes for one event happen in one transaction under a per-document advisory lock. A unique index on `(answer_id, new_version_id, claim_idx)` makes redelivery harmless. `still_valid` re-points silently; `changed` and `broken` raise alerts. `broken` also opens a `broken_answer` review item. Approving it regenerates the answer through the agent.
- **Review effects commit with the decision.** Resolving an item locks it (`FOR UPDATE`), so a second resolve gets 409. Its follow-ups (resume, regenerate, cache invalidation) are outbox rows in the same transaction.

## 5. Data model

The core tables, from the Alembic migrations in [`backend/migrations/versions`](../backend/migrations/versions):

```mermaid
erDiagram
  tenants ||--o{ sources : owns
  sources ||--o{ documents : contains
  documents ||--o{ doc_versions : "has versions"
  doc_versions ||--o{ chunks : "split into"
  doc_versions ||--o{ relations : "declares (src)"
  documents ||--o{ relations : "is target of (dst)"
  tenants ||--o{ answers : owns
  answers ||--o{ answer_citations : cites
  chunks ||--o{ answer_citations : "cited by"
  answers ||--o{ drift_events : "re-checked in"
  doc_versions ||--o{ drift_events : "old / new version"
  tenants ||--o{ review_items : queues
  tenants ||--o{ jobs : runs
  jobs ||--o| answers : produces
  jobs ||--o{ llm_calls : "costed by"
  review_items ||--o{ eval_cases : "edit becomes"
  tenants ||--o{ eval_cases : owns

  tenants {
    uuid id PK
    text name
    text skill_pack
    text api_key_hash
  }
  sources {
    uuid id PK
    text kind "openfda, git_docs, upload"
    jsonb config
    text schedule
    text status
  }
  documents {
    uuid id PK
    text external_id
    text title
  }
  doc_versions {
    uuid id PK
    int version_no
    text version_key
    text content_hash
    timestamptz valid_from
    timestamptz valid_to "no overlap, btree_gist"
    jsonb section_hashes
  }
  chunks {
    uuid id PK
    text section_path
    text text
    vector embedding "768-d, HNSW"
    tsvector tsv "GIN"
  }
  relations {
    uuid id PK
    text kind "supersedes, amends, deprecates"
    real confidence
    text status "applied, pending_review, rejected"
  }
  answers {
    uuid id PK
    timestamptz as_of
    jsonb body
    real confidence
    boolean watched
  }
  answer_citations {
    uuid answer_id FK
    int claim_idx
    uuid chunk_id FK
  }
  drift_events {
    uuid id PK
    int claim_idx
    text verdict "still_valid, changed, broken"
    jsonb detail
  }
  review_items {
    uuid id PK
    text kind
    uuid ref_id
    text status "open, resolved"
  }
  jobs {
    uuid id PK
    text kind
    text status "queued to succeeded, failed, needs_review"
  }
  outbox {
    bigserial id PK
    text topic
    jsonb payload
    timestamptz published_at
  }
  llm_calls {
    bigserial id PK
    text node
    text tier
    text model
    numeric cost_usd
  }
  eval_runs {
    uuid id PK
    text git_sha
    text corpus
    jsonb metrics
  }
  eval_cases {
    uuid id PK
    text question
    timestamptz as_of
    jsonb expected
  }
```

`outbox` and `eval_runs` stand alone: the outbox is a queue of topics with JSON payloads, and an eval run records metrics per commit and corpus. Two smaller tables are not drawn: `source_cursors` (per-source fetch cursors) and the LangGraph checkpointer's own tables.

## 6. CI/CD and automation

```mermaid
flowchart LR
  PUSH["push / pull request"] --> CI["ci.yml"]
  CI --> BE["backend job<br/>uv sync, ruff check,<br/>ruff format --check, pytest"]
  CI --> FE["frontend job<br/>install, lint, typecheck,<br/>vitest, next build"]
  FE --> LH["Lighthouse<br/>report only, artifact"]

  CRON["nightly 02:30 UTC<br/>or manual"] --> DWW["drift-watch.yml"]
  DWW --> SVC["Postgres, Redis, TEI<br/>service containers"]
  SVC --> RUN["migrate, relay, enqueue pinned sources,<br/>ingest until drained, drift until drained"]
  RUN --> REP["drift report"]
  REP -->|"only when changed"| COMMIT["commit reports/drift-log.md<br/>+ drift-latest.json"]
```

The backend CI job runs the full suite against real service containers (testcontainers). The drift watch runs offline (`DRIFTLINE_LLM_OFFLINE=true`), so it needs no paid key. `eval.yml` gates pull requests on the offline eval, and `pages.yml` rebuilds and deploys the report site when reports change.
