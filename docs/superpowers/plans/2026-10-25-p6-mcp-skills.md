# P6 MCP + Skills Implementation Plan

> **For agentic workers:** executed by parallel subagents, one per task, each in its own git worktree. Follow the P3 Implementer protocol (`docs/superpowers/plans/2026-10-25-p3-retrieval-agent.md`): TDD; no mocks; unexpected errors are reported after one fix attempt of at most 15 minutes; **no Co-Authored-By or AI attribution in commits**; never read `.env`; latest stable versions, checked on PyPI or npm before pinning.

**Goal:** make Driftline usable by other agents and adaptable per domain:
- an MCP server mounted on the gateway at `/mcp` (Streamable HTTP), so Claude Code and Cursor can ask version-aware questions;
- versioned domain skill packs that tune retrieval and prompts per tenant;
- a Claude Code Skill that teaches an agent to use the MCP tools.

**Architecture:**
- **MCP server:** uses the official MCP Python SDK (`mcp`, latest), with `FastMCP` and Streamable HTTP transport, mounted into the FastAPI app.
  - Tools are thin adapters over existing services: `ask` runs the P3 job and waits for `final` through `AskEventLog`, with a timeout; `diff_versions` and `get_timeline` read the P4 timeline/diff; `watch_answer` uses P4; `list_sources` uses the sources table.
  - Auth is the per-tenant API key (`tenants.api_key_hash`) in the `Authorization: Bearer` header, the same check the REST API gets in this plan.
- **Skill packs:** live in `skills/<name>@<semver>/`, containing `config.yaml` (retrieval and chunking parameters), `glossary.yaml`, `prompts/*.md` fragments and `eval.jsonl`.
  - A loader validates them with Pydantic. The planner and draft prompts include the tenant pack's fragments and glossary, and retrieval reads its parameters.
  - `tenants.skill_pack` selects `name@version`.
- **Claude Code Skill:** `.claude/skills/driftline/SKILL.md`.

**Spec:** `docs/superpowers/specs/2026-10-25-driftline-design.md` §5 (Skills, MCP server), §8.

**Depends on:** P3 merged; P4 merged for `diff_versions`, `get_timeline` and `watch_answer`. Wave 1b (T3) waits for P4.

## Global Constraints
Same as P3, plus:
- MCP tests use the **real MCP client** from the SDK (`mcp.client.streamable_http`) against a real server started with `livesrv.serve`. They don't stub the protocol.

## Review Focus
1. **An MCP `ask` whose job takes longer than the tool timeout** returns a structured "still running" result with `job_id`, never hangs the client. Owner: T2.
2. **A wrong or missing API key** returns an MCP auth error, and one tenant's key never reads another tenant's data. Owner: T1, T2.
3. **A malformed skill pack** (bad YAML, unknown keys, missing fragment file) fails at load time with a clear error naming the file, never at question time. Owner: T1.
4. **An `as_of` passed as a free-form string** ("2023", "v1.28") goes through the P3 `extract_as_of_hint` path, and the result matches the REST API. Owner: T2.
5. **A large `diff_versions` output** is capped, with an explicit truncation marker. Owner: T3.

---

## Wave 0 (1 agent): Task 0, foundation
- Add the dependency `mcp` (latest) and `uv lock`.
- Create `backend/src/driftline/auth.py`:
  - `hash_api_key(key) -> str` (sha256 hex);
  - `async resolve_tenant(pool, bearer: str | None) -> TenantRow`, which raises `Unauthorized`.
- Gateway dependency `require_tenant`. REST endpoints accept either the existing `tenant` field (dev mode, `settings.auth_required=False`, the default) or a bearer key. When `auth_required=True`, the bearer is mandatory and must match the tenant.
- `backend/tests/dbseed.py`: `seed_tenant(..., api_key="test-key")` stores the hash.
- Tests: `backend/tests/test_auth.py` covers a correct key, a wrong key, a missing key with `auth_required`, and a cross-tenant mismatch giving 403.
- Commit `feat(p6): tenant API-key auth`.

## Wave 1 (2 agents in parallel: T1, T2)

### Task 1: skill packs
**Files:**
- `backend/src/driftline/skills/{__init__,pack.py}`:
  - `SkillPack` (Pydantic: `name`, `version`, `retrieval: {candidates, rerank_top_n, rrf_k}`, `chunking`, `glossary: dict[str,str]`, `prompts: dict[str,str]`, `eval_path`);
  - `load_pack(path) -> SkillPack` (strict, `extra="forbid"`);
  - `resolve_pack(root, "name@1.2.0")`.
- Packs:
  - `skills/pharma@1.0.0/` (glossary: boxed warning, contraindication, REMS, …; prompt fragments on label sections);
  - `skills/k8s@1.0.0/` (glossary: deprecation, GA, feature gate, …);
  - `skills/generic@1.0.0/`.
  Each has 10 `eval.jsonl` seed cases.
- Wiring:
  - `agents/prompts.py` takes an optional `SkillPack` and appends its fragments and glossary inside a fenced `<domain_notes>` block;
  - `retrieval/hybrid.py` takes the pack's retrieval parameters;
  - `agents/worker.py` loads the tenant's pack once per job, with an LRU cache.
- Tests: `backend/tests/skills/test_pack.py` covers:
  - all 3 shipped packs load;
  - a bad pack fails, naming the file;
  - prompts include the glossary inside the fence;
  - retrieval honours the pack's `rerank_top_n`;
  - an unknown pack falls back to `generic` with a warning log.

### Task 2: MCP server, with `ask` and `list_sources`
**Files:**
- `backend/src/driftline/mcp/{__init__,server.py}`: `build_mcp(deps) -> FastMCP`. Tools:
  - `ask(question, as_of?: str, source_kinds?: list[str], timeout_s: int = 60)`, which returns an `AnswerSchema` dict or `{status: "running", job_id}`;
  - `list_sources()`.
  Bearer auth uses `resolve_tenant`.
- Mount at `/mcp` in `gateway/app.py`, with the lifespan wired correctly per the SDK docs. Fetch the current MCP Python SDK docs first.
- Tests: `backend/tests/mcp/test_mcp_server.py`, using the real SDK client over Streamable HTTP against `livesrv.serve(app)` with an agent worker running in-process (DeterministicAdapter). They cover:
  - `list_tools` shows the tools with schemas;
  - `ask` returns cited in-force answers;
  - a timeout returns `running` with `job_id`;
  - a bad key gives an auth error;
  - a free-form `as_of` "2023" matches the REST result.

## Wave 1b (1 agent; needs T2 merged, because it edits `mcp/server.py`, and needs P4 merged)

### Task 3: MCP version tools
- `diff_versions(document_id, from_version?, to_version?)`, with output capped at 16 KB and a marker;
- `get_timeline(document_id)`;
- `watch_answer(answer_id)`.
- Tests are in the same test file style: real client, seeded data, cap marker.

## Wave 2 (1 agent): Task 4, Claude Code Skill and docs
- `.claude/skills/driftline/SKILL.md`, with frontmatter `name`, `description`. It covers when to use Driftline (version- or date-sensitive questions), how to connect (`claude mcp add --transport http driftline http://localhost:8010/mcp --header "Authorization: Bearer $DRIFTLINE_KEY"`), tool-selection guidance, always passing `as_of` for historical questions, and how to read citations and `insufficient_evidence`.
- `docs/mcp.md` and a README section "Use from Claude Code / Cursor".
- Test: `backend/tests/mcp/test_skill_doc.py` checks that every tool name mentioned in SKILL.md exists in `build_mcp().list_tools()`, so the docs can't drift from the code.
- Manual check, reported: connect Claude Code to the running Compose stack, run `ask` once, and paste the transcript summary in the report.

**Final P6 gate:** full suite, ruff, no-mock grep, no AI attribution, push, CI green.

## Follow-ups from Wave 1

- **T1b:**
  - **Load packs in production.** Add a `DRIFTLINE_SKILLS_DIR` setting (default: repo `skills/`), pass it in `agents/__main__.py` `_run_worker`, and copy `skills/` into the backend Docker image.
  - **Pack-aware cache.** Make the semantic cache key include the pack spec.
  - **Rerank top_n.** It currently narrows only (`min(top_n, pack.rerank_top_n)`); make `graph.py` pass the pack's `rerank_top_n` exactly.
  - **Check time-sensitive k8s glossary facts** against the official Kubernetes docs (beta APIs off by default since v1.24, the patch support window, kubelet skew since v1.28).
- **T2b:** MCP transport security only accepts localhost Host headers by default, so requests through a Compose service name or a real host get 421. Make the allowed hosts configurable (`DRIFTLINE_MCP_ALLOWED_HOSTS`, default localhost and 127.0.0.1), and document it.
- On mcp 2.3.0, the plan's `FastMCP` is named `MCPServer`. `/mcp` is mounted as a Starlette `Route` with `include_in_schema=False`, and MCP always requires a bearer key.
- **T1b (add):** tenant API keys can currently only be created with raw SQL. Add `python -m driftline.auth create-key --tenant NAME` (prints the key once, stores only the hash; `--rotate` replaces it), tested with real Postgres, and switch `docs/mcp.md` to it.
