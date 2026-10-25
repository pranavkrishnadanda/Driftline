# Driftline Roadmap: Sub-Plans and Parallel Waves

**Spec:** `docs/superpowers/specs/2026-10-25-driftline-design.md`

The spec spans several subsystems, so implementation is split into seven sub-plans. Each sub-plan produces working, tested software on its own. Each one is written in full detail only after the previous plan merges, so it can cite real, merged interfaces instead of guessed ones.

## Execution model (applies to every sub-plan)

- **Only subagents write code.** The orchestrator (main session) dispatches tasks, reviews results, merges branches, and runs the full suite between waves.
- **Waves.** Tasks in the same wave touch disjoint files and run as **parallel subagents**, each in its own git worktree on branch `pN/tK-<slug>`.
- **Shared files.** Any file that two tasks would both touch (dependency manifests, package `__init__.py`, shared contracts) is created in that plan's Wave 0, by a single subagent, before the parallel waves.
- **TDD.** Every step sequence is: failing test → run it and see it fail → minimal code → run it and see it pass → commit.
- **No mocks.** No `unittest.mock`, `patch`, `MagicMock`, or `monkeypatch` of project code anywhere in the tests. Tests use real dependencies (testcontainers), real FastAPI apps, real recorded HTTP responses, and real in-repo implementations (`ManualClock`, `DeterministicAdapter`).
- **Per-task review.** After each task, a fresh reviewer subagent checks the work against its task text and the spec. The orchestrator merges approved branches in task-number order.
- **Wave gate.** After every wave, the orchestrator runs `cd backend && uv run pytest -q` (and the frontend suite once it exists) on `main`. The next wave starts only if everything passes.

## Sub-plans

| Plan | Delivers | Depends on | Can run in parallel with |
|---|---|---|---|
| **P1 Foundation** | Repo scaffold, Compose stack, schema + migrations, Redis Streams bus (consumer groups, reclaim, DLQ), LLM gateway (types, Gemini adapter, DeterministicAdapter, token bucket, circuit breaker, fallback router), gateway health API, CI | n/a | n/a |
| **P2 Ingestion** | Connector interface; openFDA, `kubernetes/website` and upload connectors; parse → hash → section diff → supersession extraction → chunk → embed workers; transactional outbox + relay | P1 | P5a |
| **P3 Retrieval + Agent** | Hybrid retrieval (pgvector + FTS + RRF), temporal filter, rerank, LangGraph answer graph with Postgres checkpointer, subagent fan-out (`Send`), citation verifier loop, structured output + streaming in the LLM gateway, semantic cache, cost accounting, Langfuse tracing, `/v1/ask` + SSE contract with `Last-Event-ID` replay, backpressure | P1, P2 schema in use | P5a |
| **P4 Drift + Review** | Drift scheduler, section-aware re-verification, verdicts, alerts stream, review queue + `interrupt()`, nightly `drift-watch.yml` | P2, P3 | P5b |
| **P5a Frontend shell** | Next.js + TS + Tailwind v4 + shadcn, Kokonut UI / Bklit registries, typed client generated from OpenAPI, Ask view against the SSE contract fixture | P1 (contract) | P2, P3 |
| **P5b Frontend features** | Live agent timeline (Motion), version timeline + supersession graph (anime.js + React Flow), drift inbox, review queue, `/stats` (Bklit) | P3, P4 API | P6 |
| **P6 MCP + Skills** | MCP server at `/mcp`, domain skill packs, Claude Code Skill | P3 | P5b |
| **P7 Evals + Bench** | Golden sets (150 per corpus), baselines, eval CI gate, k6 load + chaos tests, GitHub Pages reports, README + demo | P3, P4 | n/a |

Critical path: P1 → P2 → P3 → P4 → P7. Frontend (P5a and P5b) and P6 run alongside it.
