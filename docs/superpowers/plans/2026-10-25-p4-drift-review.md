# P4 Drift + Review Implementation Plan

> **For agentic workers:** executed by parallel subagents, one per task, each in its own git worktree. Follow the P3 plan's "Implementer protocol" (`docs/superpowers/plans/2026-10-25-p3-retrieval-agent.md`) and the "Global Constraints" below. Unlike P3, there is **no reference implementation**: you write the tests from the test specs below, then the code.

**Goal:** when a source document changes, every saved ("watched") answer that cites it is re-checked automatically. The engine decides `still_valid` / `changed` / `broken`, records a drift event, pushes a live alert over SSE, and routes broken or low-confidence answers into a human review queue.

**Architecture:**
- The outbox fans `version.created` out to a new `drift` Redis Stream.
- A `drift-worker` consumer group processes each event:
  - it finds watched answers whose citations point at the previous version of that document;
  - for each claim it compares the cited `section_path` hash between old and new versions (`doc_versions.section_hashes`);
  - an unchanged section means the citation is re-pointed (`still_valid`);
  - a changed section means the P3 citation verifier (`agents.guardrails.verify_claim`) re-runs against the new version (`still_valid` or `changed`);
  - cited text that is gone is `broken`: the answer is regenerated through the P3 answer graph and put into review.
- Verdicts are written to `drift_events` and published through the outbox to `events:alerts:{tenant}`. The gateway streams them over SSE.
- The review queue holds low-confidence answers (via LangGraph `interrupt()`), broken answers, and P2's pending supersession relations. Resolving an item resumes the graph or applies/rejects the relation, and records an eval case.

**Tech stack:** existing P1–P3 stack. No new services.

**Spec:** `docs/superpowers/specs/2026-10-25-driftline-design.md` §5 (human-in-the-loop), §6, §7, §8, §10.

**Depends on:** P3 merged. The P3 interfaces used here:
- `driftline.agents.schemas`: `AnswerSchema`, `Claim`, `Citation`, `AskJob`;
- `driftline.agents.guardrails`: `verify_claim`, `check_citation`, `quote_supported`, `evidence_index`;
- `driftline.agents.graph`: `run_ask`, `build_answer_graph`, `AgentDeps`;
- `driftline.agents.eventlog.AskEventLog`;
- `driftline.agents.events` (add `AlertEvent`);
- `driftline.gateway.sse`;
- `driftline.retrieval.types.Evidence`;
- `driftline.ingest.outbox.TOPIC_STREAMS`;
- the `answers` (`watched`, `job_id`, `status`), `answer_citations`, `drift_events`, `review_items`, `relations`, `doc_versions.section_hashes` and `diff_from_prev` tables.

**Before starting, each implementer must check the real signatures on `main`** (`grep -n "def " <module>`). If a name here differs from `main`, `main` wins; note it in your report.

## Global Constraints

Same as P3. In short:
- TDD, with no mocks (real Postgres/Redis/TEI via testcontainers, `DeterministicAdapter`, `ManualClock`, vcrpy cassettes);
- ports 5433/8010/8080/8081/6379;
- never read or print `.env`;
- **no Co-Authored-By or AI attribution in commits**;
- latest stable versions of any new dependency;
- test-run env prefix `DOCKER_HOST=unix:///Users/pranavkrishnadanda/.colima/default/docker.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`, with every pytest run wrapped in `perl -e 'alarm 300; exec @ARGV'`;
- report unexpected errors after a single fix attempt of at most 15 minutes.

## Review Focus

1. **The same `version.created` event delivered twice** (at-least-once relay): exactly one `drift_events` row per (answer, new version). Owner: T2 (`test_redelivered_event_creates_one_drift_event`).
2. **A document gets two new versions in quick succession** (v1 → v2 → v3 before the worker runs): the answer ends up evaluated against v3 and re-pointed once, never against a stale intermediate. Owner: T2 (`test_skipped_intermediate_version_evaluates_against_latest`).
3. **A content revert A → B → A** (known P2 limitation): the drift engine must still close and re-point correctly when the version store reuses the content hash. Owner: T1 (`test_revert_to_previous_content_creates_new_version`). Fix the version store so a revert creates a new version row with a new window.
4. **The alert SSE client reconnects with `Last-Event-ID`:** missed alerts are replayed and alerts from another tenant are never visible. Owner: T4.
5. **Resolving a review item twice, or concurrently:** the second call returns 409 and the graph is resumed once. Owner: T5.

---

## Wave 0 (1 agent)

### Task 0: drift foundation
**Files:**
- Create `backend/migrations/versions/0004_drift.py`, adding:
  - `drift_events.claim_idx int`, `drift_events.tenant_id uuid` (FK tenants), and `UNIQUE (answer_id, new_version_id, claim_idx)`;
  - `answers.watched_at timestamptz`;
  - `review_items.tenant_id uuid`, `review_items.resolution jsonb`, `review_items.resolved_at timestamptz`, `review_items.resolved_by text`, and `UNIQUE (kind, ref_id) WHERE status = 'open'`;
  - an `eval_cases(id, tenant_id, source_review_id, question, as_of, expected jsonb, created_at)` table;
  - index `answer_citations (chunk_id)`.
- Test: `backend/tests/db/test_migration_0004.py`.
- Modify `backend/src/driftline/ingest/outbox.py`: `TOPIC_STREAMS["version.created"] = ("embed", "drift")`, and add `TOPIC_STREAMS["drift.alert"] = ()`, with the alert stream chosen per tenant (see T3).
- Modify `backend/src/driftline/agents/events.py`: add `AlertEvent {type: "alert", drift_event_id, answer_id, verdict, document_title, old_version_id, new_version_id, before: str|None, after: str|None, t: datetime}`, included in the `ASK_EVENT_ADAPTER` union or a new `ALERT_EVENT_ADAPTER`.
- Modify `backend/src/driftline/config.py`: `drift_enabled: bool = True`, `drift_batch: int = 50`, `review_confidence_threshold: float = 0.6`.
- Modify `deploy/compose/docker-compose.yml`: a `drift-worker` service (`python -m driftline.drift worker`), scalable, with a heartbeat healthcheck and the Anthropic key env.
- Create `backend/src/driftline/drift/__init__.py` and `backend/src/driftline/review/__init__.py`.
- Modify `backend/tests/dbseed.py` to add `seed_watched_answer(conn, tenant_id, version_id, chunk_ids, claims) -> answer_id` (inserts `answers` with `watched=true` plus `answer_citations`).

**Test specs:**
- `test_migration_0004_upgrade_downgrade_roundtrip`: upgrade, then check the new columns, constraints and table exist; downgrade, then check they're gone.
- `test_version_created_fans_out_to_embed_and_drift`: insert an outbox row and run the relay once; one entry appears on each of `embed` and `drift`.
- `test_alert_event_round_trips_through_json`.
- In `test_compose.py`: the `drift-worker` service exists, has the heartbeat healthcheck and the key env, and has no `container_name` or ports.

**Gate:** full suite green, plus ruff and the no-mock grep. Commit `feat(p4): drift foundation (schema, streams, alert event)`.

---

## Wave 1 (3 agents in parallel)

### Task 1: section diff and the version-store revert fix
**Files:**
- Create `backend/src/driftline/drift/diff.py`:
  - `section_status(old_hashes: dict[str, str], new_hashes: dict[str, str], section_path: str) -> Literal["unchanged", "changed", "removed"]`;
  - `section_text_diff(old_text: str, new_text: str) -> str` (a unified diff, capped at 4 KB).
- Modify `backend/src/driftline/ingest/store.py` so the revert case (content identical to a non-current older version) creates a new version.
- Tests: `backend/tests/drift/test_diff.py`, and add `test_revert_to_previous_content_creates_new_version` to `backend/tests/ingest/test_store.py`.

**Test specs:**
- Unchanged, changed and removed sections.
- A nested `section_path` with " > ".
- Diff output is capped.
- A → B → A produces 3 versions with contiguous windows, and the last version is current.

### Task 2: the drift engine
**Files:**
- Create `backend/src/driftline/drift/engine.py`:
  - `class DriftEngine(pool, router, clock, settings)` with `async def handle_version_created(event: dict) -> list[DriftVerdict]`;
  - `DriftVerdict {answer_id, claim_idx, verdict, old_version_id, new_version_id, before, after}`.

**Algorithm:**
1. Load the new version and the previous (just-closed) version of the same document.
2. Find watched answers with a citation whose chunk belongs to **any** version of this document other than the latest. This covers skipped intermediate versions.
3. For each claim, run `section_status`:
   - **unchanged:** re-point `answer_citations.chunk_id` to the same-`section_path`, same-`ord` chunk in the new version; verdict `still_valid`.
   - **changed:** build `Evidence` from the new version's chunks for that section and run `verify_claim`. Supported means re-point, `still_valid`. Unsupported means `changed`, with `before`/`after` from `section_text_diff`.
   - **removed:** `broken`.
4. Write `drift_events` with `INSERT ... ON CONFLICT DO NOTHING` (idempotent), plus an outbox row `drift.alert` per inserted event, all in one transaction.
5. For a `broken` answer, call `regenerate_hook(answer_id)`, which T5 wires to the review queue. Default: insert a `review_items(kind='broken_answer')`.

- Test: `backend/tests/drift/test_engine.py`, using real Postgres plus `DeterministicAdapter` for the judge.

**Test specs:**
- `test_unchanged_section_repoints_silently`
- `test_changed_section_still_supported_is_still_valid`
- `test_changed_section_unsupported_is_changed_with_diff`
- `test_removed_section_is_broken_and_queued_for_review`
- `test_unwatched_answers_are_ignored`
- `test_redelivered_event_creates_one_drift_event`
- `test_skipped_intermediate_version_evaluates_against_latest`
- `test_other_tenants_answers_untouched`

### Task 3: alert delivery
**Files:**
- Create `backend/src/driftline/drift/alerts.py`:
  - `alert_stream_key(tenant_id) -> "events:alerts:{tenant_id}"`;
  - `class AlertLog`, which reuses the `AskEventLog` design (append/read/replay, MAXLEN, TTL; composition, not copy-paste).
- Modify `backend/src/driftline/ingest/outbox.py` so `drift.alert` rows publish to `alert_stream_key(payload.tenant_id)` as an `AlertEvent` (this is the outbox's per-tenant routing hook).
- Test: `backend/tests/drift/test_alerts.py`.

**Test specs:**
- `test_alert_published_to_tenant_stream_only`
- `test_alert_replay_from_last_event_id`
- `test_alert_stream_trimmed_to_maxlen`

**Wave 1 gate:** merge T1, T2, T3 in order; full suite, ruff and the no-mock grep.

---

## Wave 2 (3 agents in parallel)

### Task 4: watch and alerts API
**Files:**
- Create `backend/src/driftline/gateway/drift.py`:
  - `POST /v1/answers/{id}/watch` (sets `watched=true` and `watched_at`, returns 200 `{answer_id, watched: true}`; 404 for an unknown answer or another tenant);
  - `DELETE /v1/answers/{id}/watch`;
  - `GET /v1/alerts/stream?tenant=` (SSE via `gateway.sse`, with heartbeat, `Last-Event-ID` replay and the `sse_max_connections` limit);
  - `GET /v1/drift/events?tenant=&limit=` (latest first);
  - `GET /v1/documents/{id}/timeline` (versions with windows, `diff_from_prev` and relations in and out).
- Modify `backend/src/driftline/gateway/app.py` to include the router.
- Regenerate the SSE contract with `contracts/sse/alert-events.v1.json` (extend `gateway/contract.py`).
- Test: `backend/tests/gateway/test_drift_api.py`, using a real server via `livesrv.serve` and real Redis/Postgres.

**Test specs:**
- watch and unwatch;
- 404 across tenants;
- an alert published after connecting arrives live;
- reconnecting with `Last-Event-ID` replays only the missed alerts;
- a tenant-B client never sees a tenant-A alert;
- the timeline lists versions in order with contiguous windows.

### Task 5: review queue and human-in-the-loop
**Files:**
- Create `backend/src/driftline/review/queue.py`:
  - `class ReviewQueue(pool)` with `open(kind, ref_id, tenant_id, payload) -> UUID | None`, which is idempotent through the partial unique index;
  - `list(tenant_id, status='open', kind=None)`;
  - `resolve(item_id, action: Literal['approve','edit','reject'], edit: dict|None, by: str) -> ReviewItem`, which raises `AlreadyResolved` (mapped to 409).
- Modify `backend/src/driftline/agents/graph.py`: after `verify`, if the ask is for a watched answer (or `confidence < review_confidence_threshold`), call LangGraph `interrupt({...})` and open a `review_items(kind='low_confidence_answer')`. Resolving resumes the graph with `Command(resume=...)` through the Postgres checkpointer.
- Kind-specific resolution:
  - `relation`: approve sets `relations.status='applied'`; reject sets it to `'rejected'`.
  - `broken_answer`: approve regenerates the answer through `run_ask`.
  - Every resolution with an `edit` inserts an `eval_cases` row.
- Create `backend/src/driftline/gateway/review.py` with `GET /v1/review?tenant=&kind=` and `POST /v1/review/{id}/resolve`.
- Tests: `backend/tests/review/test_queue.py`, `backend/tests/gateway/test_review_api.py`, and `backend/tests/agents/test_interrupt_resume.py`.

**Test specs:**
- opening the same item twice gives one row;
- resolving twice: the second call gets 409;
- concurrent resolve (two tasks with `asyncio.gather`): exactly one succeeds;
- approving a relation applies it, and retrieval then hides the superseded document (re-use the P3 hybrid test pattern);
- `interrupt` then resume produces the final answer with the reviewer's edit, and the checkpoint survives a new graph instance (simulated worker restart);
- an edit creates an eval case.

### Task 6: drift worker and scheduler
**Files:**
- Create `backend/src/driftline/drift/worker.py`: `class DriftWorker(bus, engine, clock)` consuming stream `drift` with consumer group `drift`, plus XAUTOCLAIM, the DLQ after 3 deliveries and the heartbeat, mirroring the ingest worker.
- Create `backend/src/driftline/drift/__main__.py` with `worker` and `poll` subcommands. `poll` enqueues ingest jobs for every source whose `schedule` is due (`last_polled_at + interval <= now`) and updates `last_polled_at`; a source that keeps failing is marked `stale_source`.
- Tests: `backend/tests/drift/test_worker.py` and `backend/tests/drift/test_poll.py`.

**Test specs:**
- an event on `drift` produces a drift event, and the message is acked;
- a message whose handler raises 3 times goes to `dlq:drift`;
- a message stalled on a dead consumer is reclaimed;
- `poll` enqueues only due sources (using `ManualClock`);
- repeated fetch failures mark the source `stale_source`.

**Wave 2 gate:** merge T4, T5, T6; full suite, ruff and the no-mock grep.

---

## Wave 3 (2 agents in parallel)

### Task 7: end-to-end drift test
- Create `backend/tests/integration/test_drift_e2e.py`:
  1. ingest v1 through the P2 pipeline;
  2. ask through the P3 graph (DeterministicAdapter), then watch the answer;
  3. connect the alert SSE;
  4. ingest v2 with the cited section changed;
  5. assert the alert arrives with the `changed` verdict and a diff;
  6. ingest v3 with the section removed: assert `broken`, a review item is opened, and resolving it regenerates the answer citing v3.
- Then run a Compose smoke test with `--scale drift-worker=2`, and report what you observed.

### Task 8: nightly drift-watch GitHub Action
- Create `.github/workflows/drift-watch.yml`:
  - triggers: `schedule: cron "30 2 * * *"` plus `workflow_dispatch`;
  - steps: Postgres and Redis service containers and a TEI container, then `python -m driftline.ingest` for a pinned small set (5 openFDA labels, the Kubernetes docs for the last 2 releases), then `python -m driftline.drift report` (add a `report` subcommand in `drift/__main__.py`, owned by this task) to write `reports/drift-log.md` and `reports/drift-latest.json`;
  - commit back only when changed, using `GITHUB_TOKEN` with `contents: write`, as the user's identity via `git config user.name/email` taken from the repo's last commit author, **with no AI attribution**.
- Test: `backend/tests/drift/test_report.py`: the report renders from real DB rows deterministically.
- Use the latest major versions of every action (verify with `gh api repos/<o>/<r>/releases/latest`).

**Final P4 gate:** the full suite; ruff; the no-mock grep; `git log --format=%B | grep -ci co-authored` = 0; push; CI green; trigger `drift-watch.yml` once with `gh workflow run` and report the result.

## Follow-ups from Wave 0

- **T5:** `ingest/supersession.py` inserts `review_items` without `tenant_id`, so the column is nullable for now. Set `tenant_id` there (from the source of the new version), add a test, then add migration `0006` (down_revision "0005"; 0005 is the revert migration) making `review_items.tenant_id` NOT NULL.
- **T2 and T5:** nothing on main writes `answers`/`answer_citations` until P3 T9 (the agent worker persists the final answer). Until then, tests use `dbseed.seed_watched_answer(conn, tenant_id, version_id, chunk_ids, claims, *, question, as_of, confidence)`, where `claims` is a list of `(text, quote)` pairs and claim i cites `chunk_ids[i]`.
- `AlertEvent` lives in `ALERT_EVENT_ADAPTER = AlertEvent | ErrorEvent`, not in `ASK_EVENT_ADAPTER`.
- **T6:** `OutboxRelay` builds `AlertLog(bus._redis)` when no `alerts` is passed (private-attribute access). Make `ingest/__main__.py` pass `alerts=AlertLog(redis, maxlen=settings.alert_events_maxlen, ttl_s=settings.alert_events_ttl_s)` explicitly (add those two settings), and remove the fallback.
- **T2:** the `drift.alert` outbox payload contract is `AlertEvent.model_dump(mode="json") | {"tenant_id": str}`. Invalid payloads are dead-lettered to `dlq:drift.alert`.
- **T5:** the 0001 CHECK on `review_items.kind` only allows `('answer','relation')`. The drift engine's default `queue_broken_answer` hook therefore inserts `kind='answer'` with payload `{"reason": "broken", ...}`. In migration `0006`, widen the CHECK to `('answer','relation','broken_answer','low_confidence_answer')`, switch the hook to `broken_answer`, and keep reading old `kind='answer'` rows. The hook signature on main is `regenerate_hook(conn, tenant_id, answer_id, payload)`, and it runs inside the drift event's transaction.
- **T7:** add a `drift-poll` Compose service (`python -m driftline.drift poll`, heartbeat healthcheck, a single replica is fine because claims are CAS) and include it in the Compose smoke test.
- **T7 (consistency):** the ingest worker marks a source `stale_source` on the **first** `SourceFetchError`, while the poller uses `source_stale_after_failures=3`. Make the ingest worker leave `status` alone and report fetch failures through the same Redis streak (`poll:failures:{source}`), so there's one rule for "stale". Pin it with a test.
- `still_valid` verdicts write a `drift_events` row but **no** alert (spec §7: "re-point silently"). Alerts go out only for `changed` and `broken`.
- **T5b (fix task):**
  - **Stranded paused asks.** After a review resolve, the follow-up `agent` job is published only after commit. If that publish fails, the ask stays paused forever (the item is resolved, so a retry gets 409). Route the follow-up through the transactional outbox (topic `ask.resume` → stream `agent`).
  - **Regenerated answers lose their job link.** A regeneration job doesn't move `answers.job_id`, so `GET /v1/jobs/{regen_job}` shows no answer. Point `answers.job_id` at the latest job.
  - **Stale cache after a relation approval.** Approving a relation doesn't invalidate the semantic cache. Invalidate entries citing the superseded document's versions.
- **T7:** the end-to-end flow needs **two** resolves for a broken answer. Resolve `broken_answer`, run the worker (it pauses for review), resolve `low_confidence_answer`, run the worker; the answer then cites v3.
