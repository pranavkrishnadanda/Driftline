# P1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **This plan runs as parallel waves of subagents. See "Execution Waves". Each task runs in its own git worktree.**

**Goal:** Build the Driftline backend foundation: repo scaffold, Compose stack, Postgres schema, Redis Streams work bus, LLM gateway (Gemini live, deterministic adapter, rate limiting, circuit breaking, fallback routing), health API and CI. Every later plan builds on these.

**Architecture:** One Python package `driftline` (src layout, managed by uv) whose modules are deployed as separate processes in later plans. Postgres 16 + pgvector stores everything durable. Redis 7 provides streams (with consumer groups) and the shared LLM quota buckets. All time-dependent code takes an injected `Clock`.

**Tech Stack:**
- Python 3.12, uv, FastAPI, asyncpg, redis-py (asyncio), Alembic (migrations run through psycopg 3), pgvector, google-genai.
- Tests: pytest + pytest-asyncio, testcontainers, pytest-recording (vcrpy).
- Infra: Docker Compose, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-25-driftline-design.md` (sections 3, 4, 6, 10, 12, 13)
**Roadmap:** `docs/superpowers/plans/2026-10-25-driftline-roadmap.md`

## Global Constraints

**Process**
- TDD for every task. Write the failing test, run it and watch it fail, write the minimal code, run it and watch it pass, then commit.
- **No mocking.** Test files must not use `unittest.mock`, `patch`, `MagicMock`, `AsyncMock`, or `monkeypatch` of project code. Instead, use:
  - real Postgres and Redis through testcontainers
  - real FastAPI apps through `httpx.ASGITransport`
  - real Gemini responses recorded by vcrpy cassettes
  - the real in-repo classes `ManualClock` and `DeterministicAdapter`
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Versions and layout**
- Python `>=3.12`, managed with `uv`. All backend commands run from `backend/`.
- Postgres image `pgvector/pgvector:pg16`. Redis image `redis:7-alpine`.
- Package layout `backend/src/driftline/...`. Tests live in `backend/tests/...`, and test file basenames are unique across the repo (no `__init__.py` in tests).

**Configuration**
- Settings come from environment variables with prefix `DRIFTLINE_` (for example `DRIFTLINE_GEMINI_API_KEY`).
- Gemini model IDs live in config only. Defaults: `gemini-3.8-flash` (extract), `gemini-3.1-pro-preview` (answer), fallback `["gemini-3.8-flash", "gemini-3.5-flash-lite"]`, embedding `gemini-embedding-001` (confirmed against a live `models.list()`; `gemini-2.5-flash` is retired for new users). `-latest` aliases are deliberately avoided so eval results stay reproducible. Update the defaults if newer stable IDs exist when you implement; never hard-code them elsewhere.
- Embedding dimension is **768**. `chunks.embedding` is `vector(768)` and `Settings.embed_dim = 768`.

**Fixed parameters from the spec**
- Circuit breaker defaults: open after 5 consecutive failures, or when the error rate is ≥ 50% over 30 s with at least 10 calls in the window. Half-open after a 30 s cooldown, with one probe call at a time.
- Router retries up to 3 attempts per route, only for retryable errors (408, 429, 5xx, transport errors), with exponential backoff and jitter.
- Streams move a message to `dlq:{stream}` once it has been delivered 3 times without success.

**Secrets**
- Never commit secrets. Cassettes must filter the `x-goog-api-key` and `authorization` headers and the `key` query parameter.

## Review Focus

These five input classes and failure modes are implied by the spec but not exercised by the obvious tests. Each one gets a pinned test in the task named below.

1. **Poison stream message**: a stream entry whose `data` is not valid JSON. It must go to the DLQ after the delivery limit and must not crash the consumer. Owner: Task 2, `test_invalid_json_is_dead_lettered`.
2. **Bug-type exceptions inside a provider**: an adapter that raises something other than `ProviderError` (for example `ValueError`). It must propagate immediately, without retries and without silently falling back. Owner: Task 6, `test_non_provider_errors_propagate_without_fallback`.
3. **Empty or safety-blocked Gemini response**: when `response.text` is empty, the adapter raises a non-retryable `ProviderError`, so the router falls back instead of returning `""` as an answer. Owner: Task 5, `test_empty_response_raises_non_retryable`.
4. **Clock skew between workers sharing a bucket**: a worker whose clock is behind the last writer's. It must never add negative tokens or crash. Owner: Task 3, `test_clock_behind_last_writer_does_not_go_negative`.
5. **Version boundary**: a new version whose `valid_from` equals the previous version's `valid_to` must be accepted. Validity ranges are half-open `[from, to)`. Owner: Task 1, `test_adjacent_versions_are_allowed`.

## File Structure

```
.github/workflows/ci.yml                       T8  CI: lint + tests
deploy/compose/docker-compose.yml              T0 (create), T8 (add gateway service)
backend/pyproject.toml, uv.lock                T0  all P1 dependencies declared up front
backend/Dockerfile                             T8
backend/alembic.ini                            T1
backend/migrations/env.py                      T1
backend/migrations/versions/0001_initial.py    T1  full spec §6 schema
backend/src/driftline/__init__.py              T0
backend/src/driftline/config.py                T0  Settings
backend/src/driftline/clock.py                 T0  Clock protocol, SystemClock, ManualClock
backend/src/driftline/db/__init__.py           T0
backend/src/driftline/db/migrate.py            T1  run_migrations(dsn), __main__
backend/src/driftline/streams/__init__.py      T0
backend/src/driftline/streams/bus.py           T2  StreamBus
backend/src/driftline/llm/__init__.py          T0
backend/src/driftline/llm/types.py             T0  shared LLM contract
backend/src/driftline/llm/ratelimit.py         T3  RedisTokenBucket
backend/src/driftline/llm/breaker.py           T4  CircuitBreaker
backend/src/driftline/llm/adapters/__init__.py T0
backend/src/driftline/llm/adapters/deterministic.py T5
backend/src/driftline/llm/adapters/gemini.py   T5
backend/src/driftline/llm/router.py            T6  LLMRouter, build_router
backend/src/driftline/gateway/__init__.py      T0
backend/src/driftline/gateway/app.py           T7  create_app
backend/src/driftline/gateway/main.py          T7  module-level app for uvicorn
backend/tests/conftest.py                      T0  container fixtures
backend/tests/test_config.py, test_clock.py    T0
backend/tests/db/conftest.py, test_schema.py   T1
backend/tests/streams/test_bus.py              T2
backend/tests/llm/test_ratelimit.py            T3
backend/tests/llm/test_breaker.py              T4
backend/tests/llm/test_deterministic_adapter.py T5
backend/tests/llm/test_gemini_adapter.py       T5  + cassettes/ (recorded)
backend/tests/llm/test_router.py               T6
backend/tests/gateway/test_health.py           T7
```

## Execution Waves

| Wave | Tasks (parallel within a wave) | Notes |
|---|---|---|
| 0 | **T0** | A single subagent. Creates every shared file. Merge into `main` before Wave 1. |
| 1 | **T1, T2, T3, T4, T5, T7** | Six parallel subagents, each in its own worktree. Files are disjoint. |
| 2 | **T6, T8** | Two parallel subagents. T6 needs T3, T4 and T5; T8 needs T1 and T7. |

**Orchestrator protocol for each wave:**
1. Dispatch every task in the wave at the same time. Each one uses `isolation: worktree` on branch `p1/tN-<slug>` and is given **this whole plan file plus the spec path**.
2. As each task finishes, dispatch a reviewer subagent for it. The reviewer checks spec compliance and the no-mock rule (it greps the task's tests for `mock`, `patch` and `monkeypatch`).
3. Merge approved branches into `main` in task-number order.
4. Run `cd backend && uv run pytest -q` on `main`. Start the next wave only if everything passes.

---

### Task 0: Scaffold, shared contracts, test fixtures (Wave 0)

**Files:**
- Create: `backend/pyproject.toml`, `backend/src/driftline/__init__.py`, `backend/src/driftline/config.py`, `backend/src/driftline/clock.py`, `backend/src/driftline/llm/types.py`
- Create (empty package markers): `backend/src/driftline/{db,streams,llm,llm/adapters,gateway}/__init__.py`
- Create: `backend/tests/conftest.py`, `backend/tests/test_config.py`, `backend/tests/test_clock.py`
- Create: `deploy/compose/docker-compose.yml`, `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `driftline.config.Settings` (fields listed below)
  - `driftline.clock.Clock` (protocol: `now() -> float` in wall-clock seconds, `async sleep(seconds: float) -> None`), `SystemClock`, and `ManualClock(start: float = 0.0)` with `advance(seconds)`
  - `driftline.llm.types`: `Role`, `Message`, `CompletionRequest`, `Usage`, `CompletionResult`, `ProviderError(message, *, retryable: bool, status: int | None = None)` and `LLMProvider` (protocol: `name: str`; `async complete(model, request) -> CompletionResult`; `async embed(model, texts, dim) -> list[list[float]]`)
  - pytest fixtures: `pg_dsn` (session-scoped `postgresql://` DSN), `redis_url` (session-scoped), `redis_client` (per test: a flushed `redis.asyncio.Redis` with `decode_responses=True`)

- [ ] **Step 1: Create `backend/pyproject.toml`**

```toml
[project]
name = "driftline"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "asyncpg>=0.29",
  "redis>=5.0",
  "alembic>=1.13",
  "sqlalchemy>=2.0",
  "psycopg[binary]>=3.2",
  "pgvector>=0.3",
  "google-genai>=1.0",
  "httpx>=0.27",
]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "testcontainers[postgres,redis]>=4.8",
  "pytest-recording>=0.13",
  "vcrpy>=6.0",
  "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/driftline"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

Run: `cd backend && uv sync`
Expected: creates `.venv` and `uv.lock` with no errors.

- [ ] **Step 2: Write the failing tests for config and clock**

`backend/tests/test_config.py`:
```python
from driftline.config import Settings


def test_defaults_without_env_file():
    s = Settings(_env_file=None)
    assert s.embed_dim == 768
    assert s.model_answer
    assert s.model_extract
    assert s.model_embed
    assert s.database_url.startswith("postgresql://")
    assert s.redis_url.startswith("redis://")


def test_explicit_values_override_defaults():
    s = Settings(_env_file=None, model_answer="custom-pro", embed_dim=768)
    assert s.model_answer == "custom-pro"
```

`backend/tests/test_clock.py`:
```python
import time

from driftline.clock import ManualClock, SystemClock


async def test_manual_clock_advances_on_sleep_and_advance():
    clock = ManualClock(start=100.0)
    assert clock.now() == 100.0
    clock.advance(2.5)
    assert clock.now() == 102.5
    await clock.sleep(1.5)
    assert clock.now() == 104.0


def test_system_clock_is_wall_clock():
    assert abs(SystemClock().now() - time.time()) < 1.0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_config.py tests/test_clock.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'driftline.config'`

- [ ] **Step 4: Implement config, clock and the LLM types contract**

`backend/src/driftline/__init__.py`:
```python
"""Driftline: version-aware knowledge engine."""
```

`backend/src/driftline/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRIFTLINE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://driftline:driftline@localhost:5432/driftline"
    redis_url: str = "redis://localhost:6379/0"

    gemini_api_key: str | None = None
    model_extract: str = "gemini-2.5-flash"
    model_answer: str = "gemini-2.5-pro"
    model_fallback: list[str] = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    model_embed: str = "gemini-embedding-001"
    embed_dim: int = 768
```

`backend/src/driftline/clock.py`:
```python
import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    """Wall-clock time; comparable across processes sharing Redis state."""

    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class ManualClock:
    """Deterministic clock for tests and simulations; sleep advances time instantly."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds

    async def sleep(self, seconds: float) -> None:
        self._t += seconds
```

`backend/src/driftline/llm/types.py`:
```python
from enum import Enum
from typing import Protocol

from pydantic import BaseModel


class Role(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"


class Message(BaseModel):
    role: Role
    content: str


class CompletionRequest(BaseModel):
    messages: list[Message]
    temperature: float = 0.0
    max_output_tokens: int = 1024


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class CompletionResult(BaseModel):
    text: str
    model: str
    provider: str
    usage: Usage
    latency_ms: float
    degraded: bool = False


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class LLMProvider(Protocol):
    name: str

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult: ...

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]: ...
```

Create these empty files: `backend/src/driftline/db/__init__.py`, `backend/src/driftline/streams/__init__.py`, `backend/src/driftline/llm/__init__.py`, `backend/src/driftline/llm/adapters/__init__.py`, `backend/src/driftline/gateway/__init__.py`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_config.py tests/test_clock.py -v`
Expected: 4 passed.

- [ ] **Step 6: Add the container fixtures, Compose file and `.gitignore`**

`backend/tests/conftest.py`:
```python
import pytest
import redis.asyncio as aioredis
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def pg_dsn():
    with PostgresContainer(
        "pgvector/pgvector:pg16", username="test", password="test", dbname="test", driver=None
    ) as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def redis_url():
    with RedisContainer("redis:7-alpine") as r:
        yield f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"


@pytest.fixture
async def redis_client(redis_url):
    client = aioredis.from_url(redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()
```

`deploy/compose/docker-compose.yml`:
```yaml
name: driftline
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: driftline
      POSTGRES_PASSWORD: driftline
      POSTGRES_DB: driftline
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U driftline"]
      interval: 5s
      retries: 10
    volumes: [pgdata:/var/lib/postgresql/data]
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 10
volumes:
  pgdata: {}
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
.ruff_cache/
node_modules/
.next/
```

Run: `docker compose -f deploy/compose/docker-compose.yml config -q`
Expected: no output (the file is valid).

Run: `cd backend && uv run pytest -q && uv run ruff check .`
Expected: 4 passed, and ruff reports no errors.

- [ ] **Step 7: Commit**

```bash
git add .gitignore deploy backend
git commit -m "feat(p1): scaffold backend, shared LLM contract, clock, test fixtures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 1: Database schema and migrations (Wave 1)

**Files:**
- Create: `backend/alembic.ini`, `backend/migrations/env.py`, `backend/migrations/versions/0001_initial.py`, `backend/src/driftline/db/migrate.py`
- Test: `backend/tests/db/conftest.py`, `backend/tests/db/test_schema.py`

**Interfaces:**
- Consumes: fixture `pg_dsn`, and `Settings.database_url`.
- Produces:
  - `driftline.db.migrate.run_migrations(dsn: str, revision: str = "head") -> None`, which takes a plain `postgresql://` DSN and is idempotent
  - `python -m driftline.db.migrate`, which migrates `Settings().database_url`
  - every table in spec §6 under the column names used below
  - fixtures `migrated_dsn` and `conn` (an asyncpg connection) in `tests/db/conftest.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/db/conftest.py`:
```python
import asyncpg
import pytest

from driftline.db.migrate import run_migrations


@pytest.fixture(scope="session")
def migrated_dsn(pg_dsn):
    run_migrations(pg_dsn)
    return pg_dsn


@pytest.fixture
async def conn(migrated_dsn):
    c = await asyncpg.connect(migrated_dsn)
    yield c
    await c.close()
```

`backend/tests/db/test_schema.py`:
```python
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

from driftline.db.migrate import run_migrations

EXPECTED_TABLES = {
    "tenants", "sources", "documents", "doc_versions", "chunks", "relations",
    "answers", "answer_citations", "drift_events", "review_items", "jobs",
    "outbox", "eval_runs",
}

INSERT_VERSION = (
    "INSERT INTO doc_versions (document_id, version_no, content_hash, valid_from, valid_to) "
    "VALUES ($1, $2, $3, $4, $5)"
)


def ts(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


async def seed_document(conn) -> uuid.UUID:
    tenant = await conn.fetchval(
        "INSERT INTO tenants (name, api_key_hash) VALUES ($1, 'x') RETURNING id",
        f"t-{uuid.uuid4()}",
    )
    source = await conn.fetchval(
        "INSERT INTO sources (tenant_id, kind) VALUES ($1, 'upload') RETURNING id", tenant
    )
    return await conn.fetchval(
        "INSERT INTO documents (source_id, external_id) VALUES ($1, 'doc-1') RETURNING id", source
    )


async def test_all_spec_tables_exist(conn):
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    assert EXPECTED_TABLES <= {r["table_name"] for r in rows}


async def test_extensions_installed(conn):
    rows = await conn.fetch("SELECT extname FROM pg_extension")
    assert {"vector", "btree_gist"} <= {r["extname"] for r in rows}


def test_migrations_are_idempotent(migrated_dsn):
    run_migrations(migrated_dsn)


async def test_overlapping_versions_are_rejected(conn):
    doc = await seed_document(conn)
    await conn.execute(INSERT_VERSION, doc, 1, "h1", ts(2024), None)
    with pytest.raises(asyncpg.exceptions.ExclusionViolationError):
        await conn.execute(INSERT_VERSION, doc, 2, "h2", ts(2025), None)


async def test_adjacent_versions_are_allowed(conn):
    doc = await seed_document(conn)
    await conn.execute(INSERT_VERSION, doc, 1, "h1", ts(2024), None)
    async with conn.transaction():
        await conn.execute(
            "UPDATE doc_versions SET valid_to = $2 WHERE document_id = $1 AND version_no = 1",
            doc, ts(2025),
        )
        await conn.execute(INSERT_VERSION, doc, 2, "h2", ts(2025), None)
    count = await conn.fetchval("SELECT count(*) FROM doc_versions WHERE document_id = $1", doc)
    assert count == 2


async def test_duplicate_content_hash_is_rejected(conn):
    doc = await seed_document(conn)
    await conn.execute(INSERT_VERSION, doc, 1, "same", ts(2020), ts(2021))
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await conn.execute(INSERT_VERSION, doc, 2, "same", ts(2022), None)


async def test_chunk_tsv_is_generated_and_embedding_is_768(conn):
    doc = await seed_document(conn)
    version = await conn.fetchval(INSERT_VERSION + " RETURNING id", doc, 1, "h", ts(2024), None)
    vec = "[" + ",".join(["0.1"] * 768) + "]"
    await conn.execute(
        "INSERT INTO chunks (version_id, ord, text, embedding, embed_model) "
        "VALUES ($1, 0, 'Boxed warning: hepatotoxicity', $2::vector, 'm')",
        version, vec,
    )
    hit = await conn.fetchval(
        "SELECT count(*) FROM chunks WHERE version_id = $1 AND tsv @@ plainto_tsquery('english', 'warning')",
        version,
    )
    assert hit == 1
    with pytest.raises(asyncpg.exceptions.DataError):
        await conn.execute(
            "INSERT INTO chunks (version_id, ord, text, embedding) VALUES ($1, 1, 'x', '[0.1,0.2]'::vector)",
            version,
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/db -v`
Expected: ERROR at collection with `ModuleNotFoundError: No module named 'driftline.db.migrate'`

- [ ] **Step 3: Implement the migrations**

`backend/alembic.ini`:
```ini
[alembic]
script_location = migrations
sqlalchemy.url = postgresql+psycopg://driftline:driftline@localhost:5432/driftline
```

`backend/migrations/env.py`:
```python
from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
```

`backend/migrations/versions/0001_initial.py`:
```python
"""initial schema (spec section 6)"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  skill_pack text,
  api_key_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('openfda', 'git_docs', 'upload')),
  config jsonb NOT NULL DEFAULT '{}',
  schedule text,
  last_polled_at timestamptz,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'stale_source', 'paused'))
);

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  external_id text NOT NULL,
  title text,
  UNIQUE (source_id, external_id)
);

CREATE TABLE doc_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_no int NOT NULL,
  content_hash text NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  raw_uri text,
  diff_from_prev jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, content_hash),
  UNIQUE (document_id, version_no),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  EXCLUDE USING gist (document_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)
);
CREATE INDEX doc_versions_doc_from ON doc_versions (document_id, valid_from);

CREATE TABLE chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES doc_versions(id) ON DELETE CASCADE,
  ord int NOT NULL,
  section_path text NOT NULL DEFAULT '',
  text text NOT NULL,
  embedding vector(768),
  embed_model text,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
  UNIQUE (version_id, ord)
);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE relations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  src_version_id uuid NOT NULL REFERENCES doc_versions(id) ON DELETE CASCADE,
  dst_document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('supersedes', 'amends', 'deprecates')),
  evidence_chunk_id uuid REFERENCES chunks(id) ON DELETE SET NULL,
  confidence real NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  status text NOT NULL DEFAULT 'applied' CHECK (status IN ('applied', 'pending_review', 'rejected'))
);

CREATE TABLE answers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  question text NOT NULL,
  as_of timestamptz NOT NULL,
  body jsonb NOT NULL,
  confidence real,
  watched boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE answer_citations (
  answer_id uuid NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  claim_idx int NOT NULL,
  chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  PRIMARY KEY (answer_id, claim_idx, chunk_id)
);

CREATE TABLE drift_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id uuid NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  old_version_id uuid REFERENCES doc_versions(id) ON DELETE SET NULL,
  new_version_id uuid REFERENCES doc_versions(id) ON DELETE SET NULL,
  verdict text NOT NULL CHECK (verdict IN ('still_valid', 'changed', 'broken')),
  detail jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE review_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL CHECK (kind IN ('answer', 'relation')),
  ref_id uuid NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid REFERENCES tenants(id) ON DELETE CASCADE,
  kind text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);

CREATE TABLE outbox (
  id bigserial PRIMARY KEY,
  topic text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX outbox_unpublished ON outbox (id) WHERE published_at IS NULL;

CREATE TABLE eval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  git_sha text NOT NULL,
  corpus text NOT NULL,
  metrics jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
```

`backend/src/driftline/db/migrate.py`:
```python
from pathlib import Path

from alembic import command
from alembic.config import Config

from driftline.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[3]


def _sqlalchemy_url(dsn: str) -> str:
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations(dsn: str, revision: str = "head") -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _sqlalchemy_url(dsn))
    command.upgrade(cfg, revision)


if __name__ == "__main__":
    run_migrations(Settings().database_url)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/db -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic.ini backend/migrations backend/src/driftline/db/migrate.py backend/tests/db
git commit -m "feat(p1): initial schema with versioned documents and pgvector

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Redis Streams work bus (Wave 1)

**Files:**
- Create: `backend/src/driftline/streams/bus.py`
- Test: `backend/tests/streams/test_bus.py`

**Interfaces:**
- Consumes: fixture `redis_client`.
- Produces `driftline.streams.bus`:
  - `Handler = Callable[[str, dict], Awaitable[None]]`, called as `(message_id, payload)`
  - `ConsumeResult(processed: int, failed: int, dead_lettered: int)`, a frozen dataclass
  - `StreamBus(redis, *, max_deliveries: int = 3, dlq_prefix: str = "dlq:")` with these methods:
    - `async publish(stream: str, payload: dict) -> str`: stores the payload as JSON in field `data`
    - `async ensure_group(stream: str, group: str) -> None`: idempotent
    - `async consume_once(stream, group, consumer, handler, *, count=10, block_ms=100) -> ConsumeResult`
    - `async reclaim_once(stream, group, consumer, handler, *, min_idle_ms: int, count=10) -> ConsumeResult`: takes over stalled messages via `XAUTOCLAIM`
  - DLQ entries go to stream `f"{dlq_prefix}{stream}"` with fields `data`, `source_id` and `error`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/streams/test_bus.py`:
```python
import pytest

from driftline.streams.bus import StreamBus

STREAM, GROUP = "jobs", "workers"


@pytest.fixture
async def bus(redis_client):
    b = StreamBus(redis_client, max_deliveries=3)
    await b.ensure_group(STREAM, GROUP)
    return b


async def test_publish_consume_acks(bus, redis_client):
    seen = []

    async def handler(msg_id, payload):
        seen.append(payload)

    await bus.publish(STREAM, {"job": 1})
    result = await bus.consume_once(STREAM, GROUP, "c1", handler)
    assert result.processed == 1
    assert seen == [{"job": 1}]
    summary = await redis_client.xpending(STREAM, GROUP)
    assert summary["pending"] == 0


async def test_ensure_group_is_idempotent(bus):
    await bus.ensure_group(STREAM, GROUP)


async def test_consumers_in_group_split_work(bus):
    got_a, got_b = [], []

    async def a(_, p):
        got_a.append(p["n"])

    async def b(_, p):
        got_b.append(p["n"])

    for n in range(10):
        await bus.publish(STREAM, {"n": n})
    await bus.consume_once(STREAM, GROUP, "a", a, count=5)
    await bus.consume_once(STREAM, GROUP, "b", b, count=5)
    assert len(got_a) == 5 and len(got_b) == 5
    assert set(got_a).isdisjoint(got_b)
    assert sorted(got_a + got_b) == list(range(10))


async def test_failed_message_stays_pending(bus, redis_client):
    async def boom(_, __):
        raise RuntimeError("handler failed")

    await bus.publish(STREAM, {"x": 1})
    result = await bus.consume_once(STREAM, GROUP, "c1", boom)
    assert result.failed == 1
    summary = await redis_client.xpending(STREAM, GROUP)
    assert summary["pending"] == 1


async def test_stalled_message_is_reclaimed_by_another_consumer(bus, redis_client):
    # consumer "crashed" reads the message and never acks (real XREADGROUP, no handler)
    await bus.publish(STREAM, {"job": "stalled"})
    await redis_client.xreadgroup(GROUP, "crashed", {STREAM: ">"}, count=1)

    seen = []

    async def handler(_, payload):
        seen.append(payload)

    result = await bus.reclaim_once(STREAM, GROUP, "rescuer", handler, min_idle_ms=0)
    assert result.processed == 1
    assert seen == [{"job": "stalled"}]
    assert (await redis_client.xpending(STREAM, GROUP))["pending"] == 0


async def test_message_is_dead_lettered_after_max_deliveries(bus, redis_client):
    async def boom(_, __):
        raise RuntimeError("always fails")

    await bus.publish(STREAM, {"x": 1})
    await bus.consume_once(STREAM, GROUP, "c1", boom)                  # delivery 1
    await bus.reclaim_once(STREAM, GROUP, "c1", boom, min_idle_ms=0)   # delivery 2
    result = await bus.reclaim_once(STREAM, GROUP, "c1", boom, min_idle_ms=0)  # delivery 3
    assert result.dead_lettered == 1
    dlq = await redis_client.xrange(f"dlq:{STREAM}")
    assert len(dlq) == 1
    assert "always fails" in dlq[0][1]["error"]
    assert (await redis_client.xpending(STREAM, GROUP))["pending"] == 0


async def test_invalid_json_is_dead_lettered(bus, redis_client):
    seen = []

    async def handler(_, payload):
        seen.append(payload)

    await redis_client.xadd(STREAM, {"data": "not json{"})
    await bus.consume_once(STREAM, GROUP, "c1", handler)
    await bus.reclaim_once(STREAM, GROUP, "c1", handler, min_idle_ms=0)
    result = await bus.reclaim_once(STREAM, GROUP, "c1", handler, min_idle_ms=0)
    assert seen == []
    assert result.dead_lettered == 1
    assert len(await redis_client.xrange(f"dlq:{STREAM}")) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/streams -v`
Expected: ERROR at collection with `ModuleNotFoundError: No module named 'driftline.streams.bus'`

- [ ] **Step 3: Implement the bus**

`backend/src/driftline/streams/bus.py`:
```python
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ConsumeResult:
    processed: int = 0
    failed: int = 0
    dead_lettered: int = 0


class StreamBus:
    """At-least-once work distribution over Redis Streams consumer groups."""

    def __init__(self, redis: Redis, *, max_deliveries: int = 3, dlq_prefix: str = "dlq:") -> None:
        self._redis = redis
        self._max_deliveries = max_deliveries
        self._dlq_prefix = dlq_prefix

    async def publish(self, stream: str, payload: dict[str, Any]) -> str:
        return await self._redis.xadd(stream, {"data": json.dumps(payload)})

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_once(
        self, stream: str, group: str, consumer: str, handler: Handler,
        *, count: int = 10, block_ms: int = 100,
    ) -> ConsumeResult:
        resp = await self._redis.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        entries = resp[0][1] if resp else []
        return await self._process(stream, group, entries, handler)

    async def reclaim_once(
        self, stream: str, group: str, consumer: str, handler: Handler,
        *, min_idle_ms: int, count: int = 10,
    ) -> ConsumeResult:
        resp = await self._redis.xautoclaim(
            stream, group, consumer, min_idle_time=min_idle_ms, start_id="0-0", count=count
        )
        return await self._process(stream, group, resp[1], handler)

    async def _process(self, stream, group, entries, handler) -> ConsumeResult:
        processed = failed = dead = 0
        for msg_id, fields in entries:
            if fields is None:  # entry was deleted from the stream while pending
                await self._redis.xack(stream, group, msg_id)
                continue
            try:
                payload = json.loads(fields["data"])
                await handler(msg_id, payload)
            except Exception as exc:  # noqa: BLE001 - any handler failure counts as a failed delivery
                if await self._delivery_count(stream, group, msg_id) >= self._max_deliveries:
                    await self._redis.xadd(
                        f"{self._dlq_prefix}{stream}",
                        {"data": fields.get("data", ""), "source_id": msg_id, "error": repr(exc)},
                    )
                    await self._redis.xack(stream, group, msg_id)
                    dead += 1
                else:
                    failed += 1
                continue
            await self._redis.xack(stream, group, msg_id)
            processed += 1
        return ConsumeResult(processed=processed, failed=failed, dead_lettered=dead)

    async def _delivery_count(self, stream: str, group: str, msg_id: str) -> int:
        info = await self._redis.xpending_range(stream, group, min=msg_id, max=msg_id, count=1)
        return int(info[0]["times_delivered"]) if info else 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/streams -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/driftline/streams/bus.py backend/tests/streams
git commit -m "feat(p1): Redis Streams bus with consumer groups, reclaim and DLQ

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Distributed token bucket for LLM quota (Wave 1)

**Files:**
- Create: `backend/src/driftline/llm/ratelimit.py`
- Test: `backend/tests/llm/test_ratelimit.py`

**Interfaces:**
- Consumes: `driftline.clock.ManualClock` and `Clock`, and fixture `redis_client`.
- Produces `driftline.llm.ratelimit`:
  - `RateLimitTimeout(Exception)`
  - `RedisTokenBucket(redis, key: str, *, capacity: float, refill_per_sec: float, clock: Clock)` with these methods:
    - `async try_acquire(cost: float = 1.0) -> tuple[bool, float]`: returns `(allowed, wait_seconds_if_denied)`
    - `async acquire(cost: float = 1.0, *, timeout: float) -> None`: raises `RateLimitTimeout` when the wait would exceed `timeout`, and raises `ValueError` if `cost > capacity`
  - All state lives in the Redis hash `key`, so every worker using the same key shares one quota.

- [ ] **Step 1: Write the failing tests**

`backend/tests/llm/test_ratelimit.py`:
```python
import pytest

from driftline.clock import ManualClock
from driftline.llm.ratelimit import RateLimitTimeout, RedisTokenBucket


def bucket(redis_client, clock, capacity=2, rate=1.0, key="rl:test"):
    return RedisTokenBucket(redis_client, key, capacity=capacity, refill_per_sec=rate, clock=clock)


async def test_allows_up_to_capacity_then_denies_with_wait(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=2, rate=0.5)
    assert (await b.try_acquire())[0] is True
    assert (await b.try_acquire())[0] is True
    allowed, wait = await b.try_acquire()
    assert allowed is False
    assert wait == pytest.approx(2.0)


async def test_refills_over_time(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=1, rate=1.0)
    assert (await b.try_acquire())[0]
    assert not (await b.try_acquire())[0]
    clock.advance(1.0)
    assert (await b.try_acquire())[0]


async def test_two_instances_share_one_quota(redis_client):
    clock = ManualClock(1000.0)
    worker_a = bucket(redis_client, clock, capacity=2)
    worker_b = bucket(redis_client, clock, capacity=2)
    assert (await worker_a.try_acquire())[0]
    assert (await worker_b.try_acquire())[0]
    assert not (await worker_a.try_acquire())[0]


async def test_acquire_waits_for_refill(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=1, rate=1.0)
    await b.acquire(timeout=5)
    await b.acquire(timeout=5)
    assert clock.now() == pytest.approx(1001.0)


async def test_acquire_times_out(redis_client):
    clock = ManualClock(1000.0)
    b = bucket(redis_client, clock, capacity=1, rate=0.1)
    await b.acquire(timeout=1)
    with pytest.raises(RateLimitTimeout):
        await b.acquire(timeout=1)


async def test_cost_above_capacity_is_rejected(redis_client):
    b = bucket(redis_client, ManualClock(0.0), capacity=2)
    with pytest.raises(ValueError):
        await b.acquire(cost=3, timeout=10)


async def test_clock_behind_last_writer_does_not_go_negative(redis_client):
    ahead, behind = ManualClock(2000.0), ManualClock(1990.0)
    b_ahead = bucket(redis_client, ahead, capacity=2, rate=1.0)
    b_behind = bucket(redis_client, behind, capacity=2, rate=1.0)
    assert (await b_ahead.try_acquire())[0]
    allowed, _ = await b_behind.try_acquire()
    assert allowed is True
    tokens = float(await redis_client.hget("rl:test", "tokens"))
    assert 0.0 <= tokens <= 2.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/llm/test_ratelimit.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'driftline.llm.ratelimit'`

- [ ] **Step 3: Implement the bucket**

`backend/src/driftline/llm/ratelimit.py`:
```python
from redis.asyncio import Redis

from driftline.clock import Clock

# KEYS[1] bucket hash; ARGV: capacity, refill_per_sec, cost, now
_LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  ts = now
end
local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * rate)
local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(math.max(now, ts)))
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 60)
local wait = 0
if allowed == 0 then
  wait = (cost - tokens) / rate
end
return {allowed, tostring(wait)}
"""


class RateLimitTimeout(Exception):
    pass


class RedisTokenBucket:
    """Token bucket shared by every worker that uses the same Redis key."""

    def __init__(
        self, redis: Redis, key: str, *, capacity: float, refill_per_sec: float, clock: Clock
    ) -> None:
        self.key = key
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._clock = clock
        self._script = redis.register_script(_LUA)

    async def try_acquire(self, cost: float = 1.0) -> tuple[bool, float]:
        allowed, wait = await self._script(
            keys=[self.key], args=[self.capacity, self.refill_per_sec, cost, self._clock.now()]
        )
        return bool(int(allowed)), float(wait)

    async def acquire(self, cost: float = 1.0, *, timeout: float) -> None:
        if cost > self.capacity:
            raise ValueError(f"cost {cost} exceeds bucket capacity {self.capacity}")
        deadline = self._clock.now() + timeout
        while True:
            allowed, wait = await self.try_acquire(cost)
            if allowed:
                return
            if self._clock.now() + wait > deadline:
                raise RateLimitTimeout(f"{self.key}: needs {wait:.2f}s, timeout {timeout}s")
            await self._clock.sleep(wait)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/llm/test_ratelimit.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/driftline/llm/ratelimit.py backend/tests/llm/test_ratelimit.py
git commit -m "feat(p1): Redis token bucket shared across workers for LLM quota

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Circuit breaker (Wave 1)

**Files:**
- Create: `backend/src/driftline/llm/breaker.py`
- Test: `backend/tests/llm/test_breaker.py`

**Interfaces:**
- Consumes: `driftline.clock.ManualClock` and `Clock`.
- Produces `driftline.llm.breaker`:
  - `BreakerState` (enum: `closed`, `open`, `half_open`)
  - `CircuitBreaker(*, clock, failure_threshold=5, error_rate_threshold=0.5, window_seconds=30.0, min_calls_in_window=10, cooldown_seconds=30.0)` with:
    - property `state`
    - `allow() -> bool`: in half-open, returns `True` for exactly one probe until that probe is recorded
    - `record_success()` and `record_failure()`

- [ ] **Step 1: Write the failing tests**

`backend/tests/llm/test_breaker.py`:
```python
from driftline.clock import ManualClock
from driftline.llm.breaker import BreakerState, CircuitBreaker


def make(clock=None, **kw):
    return CircuitBreaker(clock=clock or ManualClock(0.0), **kw)


def test_starts_closed_and_allows():
    b = make()
    assert b.state is BreakerState.closed
    assert b.allow()


def test_opens_after_consecutive_failures():
    b = make(failure_threshold=5)
    for _ in range(4):
        b.record_failure()
    assert b.state is BreakerState.closed
    b.record_failure()
    assert b.state is BreakerState.open
    assert not b.allow()


def test_success_resets_consecutive_count():
    b = make(failure_threshold=3, min_calls_in_window=100)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.state is BreakerState.closed


def test_opens_on_error_rate_in_window():
    b = make(failure_threshold=100, error_rate_threshold=0.5, min_calls_in_window=10)
    for _ in range(5):
        b.record_success()
        b.record_failure()
    assert b.state is BreakerState.open


def test_old_calls_leave_the_window():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=100, min_calls_in_window=10, window_seconds=30)
    for _ in range(9):
        b.record_failure()
    clock.advance(31)
    b.record_failure()
    assert b.state is BreakerState.closed


def test_half_open_after_cooldown_allows_single_probe():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=1, cooldown_seconds=30)
    b.record_failure()
    assert not b.allow()
    clock.advance(30)
    assert b.state is BreakerState.half_open
    assert b.allow() is True
    assert b.allow() is False


def test_probe_success_closes():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=1, cooldown_seconds=30)
    b.record_failure()
    clock.advance(30)
    assert b.allow()
    b.record_success()
    assert b.state is BreakerState.closed
    assert b.allow()


def test_probe_failure_reopens_for_another_cooldown():
    clock = ManualClock(0.0)
    b = make(clock, failure_threshold=1, cooldown_seconds=30)
    b.record_failure()
    clock.advance(30)
    assert b.allow()
    b.record_failure()
    assert b.state is BreakerState.open
    clock.advance(29)
    assert not b.allow()
    clock.advance(1)
    assert b.allow()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/llm/test_breaker.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'driftline.llm.breaker'`

- [ ] **Step 3: Implement the breaker**

`backend/src/driftline/llm/breaker.py`:
```python
from collections import deque
from enum import Enum

from driftline.clock import Clock


class BreakerState(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        clock: Clock,
        failure_threshold: int = 5,
        error_rate_threshold: float = 0.5,
        window_seconds: float = 30.0,
        min_calls_in_window: int = 10,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._clock = clock
        self._failure_threshold = failure_threshold
        self._error_rate_threshold = error_rate_threshold
        self._window_seconds = window_seconds
        self._min_calls = min_calls_in_window
        self._cooldown = cooldown_seconds
        self._calls: deque[tuple[float, bool]] = deque()
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.closed
        if self._clock.now() - self._opened_at >= self._cooldown:
            return BreakerState.half_open
        return BreakerState.open

    def allow(self) -> bool:
        state = self.state
        if state is BreakerState.closed:
            return True
        if state is BreakerState.half_open and not self._probe_in_flight:
            self._probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        if self.state is BreakerState.half_open:
            self._reset()
        self._consecutive_failures = 0
        self._record(True)

    def record_failure(self) -> None:
        if self.state is BreakerState.half_open:
            self._open()
            return
        self._consecutive_failures += 1
        self._record(False)
        if self._consecutive_failures >= self._failure_threshold or self._error_rate_exceeded():
            self._open()

    def _record(self, ok: bool) -> None:
        now = self._clock.now()
        self._calls.append((now, ok))
        while self._calls and now - self._calls[0][0] > self._window_seconds:
            self._calls.popleft()

    def _error_rate_exceeded(self) -> bool:
        if len(self._calls) < self._min_calls:
            return False
        failures = sum(1 for _, ok in self._calls if not ok)
        return failures / len(self._calls) >= self._error_rate_threshold

    def _open(self) -> None:
        self._opened_at = self._clock.now()
        self._probe_in_flight = False

    def _reset(self) -> None:
        self._opened_at = None
        self._probe_in_flight = False
        self._calls.clear()
        self._consecutive_failures = 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/llm/test_breaker.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/driftline/llm/breaker.py backend/tests/llm/test_breaker.py
git commit -m "feat(p1): circuit breaker with consecutive and error-rate tripping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Provider adapters: Deterministic and Gemini (Wave 1)

**Files:**
- Create: `backend/src/driftline/llm/adapters/deterministic.py`, `backend/src/driftline/llm/adapters/gemini.py`
- Test: `backend/tests/llm/test_deterministic_adapter.py`, `backend/tests/llm/test_gemini_adapter.py`, `backend/tests/llm/cassettes/test_gemini_adapter/*.yaml` (recorded)

**Interfaces:**
- Consumes: `driftline.llm.types` (from T0) and `driftline.clock`.
- Produces:
  - `DeterministicAdapter(name: str = "deterministic", *, latency_ms: float = 0.0, script: list[Exception | None] | None = None, clock: Clock | None = None)`. It implements `LLMProvider`. Each call pops the next `script` entry; an exception entry is raised. `calls: list[str]` records the model names used. Completion text is `f"[{model}] {last user message}"`. `embed` returns stable, unit-norm vectors of length `dim`.
  - `GeminiAdapter(api_key: str, *, clock: Clock | None = None)`. It implements `LLMProvider` with `name = "gemini"`. It maps SDK errors to `ProviderError` (retryable for 408, 429 and 5xx, and for transport errors).
  - `driftline.llm.adapters.gemini._result_text(response) -> str`, which raises a non-retryable `ProviderError` when the response text is empty.

- [ ] **Step 1: Write the failing tests**

`backend/tests/llm/test_deterministic_adapter.py`:
```python
import math

import pytest

from driftline.clock import ManualClock
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role


def req(text):
    return CompletionRequest(messages=[Message(role=Role.user, content=text)])


async def test_completion_is_deterministic():
    a = DeterministicAdapter("p")
    r1 = await a.complete("m1", req("hello world"))
    r2 = await a.complete("m1", req("hello world"))
    assert r1.text == r2.text == "[m1] hello world"
    assert r1.provider == "p"
    assert r1.usage.input_tokens == 2
    assert a.calls == ["m1", "m1"]


async def test_script_raises_in_order_then_succeeds():
    err = ProviderError("rate limited", retryable=True, status=429)
    a = DeterministicAdapter("p", script=[err, None])
    with pytest.raises(ProviderError):
        await a.complete("m", req("x"))
    assert (await a.complete("m", req("x"))).text == "[m] x"
    assert (await a.complete("m", req("x"))).text == "[m] x"


async def test_latency_uses_clock():
    clock = ManualClock(0.0)
    a = DeterministicAdapter("p", latency_ms=250, clock=clock)
    r = await a.complete("m", req("x"))
    assert clock.now() == pytest.approx(0.25)
    assert r.latency_ms == pytest.approx(250)


async def test_embed_is_stable_and_unit_norm():
    a = DeterministicAdapter("p")
    v1, v2 = await a.embed("e", ["alpha", "beta"], 768)
    assert len(v1) == 768
    assert math.isclose(math.sqrt(sum(x * x for x in v1)), 1.0, rel_tol=1e-9)
    assert v1 != v2
    assert (await a.embed("e", ["alpha"], 768))[0] == v1
```

`backend/tests/llm/test_gemini_adapter.py`:
```python
import os

import pytest
from google.genai import types as gtypes

from driftline.llm.adapters.gemini import GeminiAdapter, _result_text
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role

API_KEY = os.environ.get("DRIFTLINE_GEMINI_API_KEY", "replay-only")
MODEL = os.environ.get("DRIFTLINE_MODEL_EXTRACT", "gemini-2.5-flash")
EMBED_MODEL = os.environ.get("DRIFTLINE_MODEL_EMBED", "gemini-embedding-001")


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": ["x-goog-api-key", "authorization"],
        "filter_query_parameters": ["key"],
        "match_on": ["method", "scheme", "host", "path"],
    }


@pytest.mark.vcr
async def test_complete_returns_text_and_usage():
    adapter = GeminiAdapter(API_KEY)
    result = await adapter.complete(
        MODEL,
        CompletionRequest(
            messages=[
                Message(role=Role.system, content="You answer with one word."),
                Message(role=Role.user, content="Reply with exactly the word PONG."),
            ],
            max_output_tokens=512,
        ),
    )
    assert "PONG" in result.text.upper()
    assert result.provider == "gemini"
    assert result.model == MODEL
    assert result.usage.input_tokens > 0


@pytest.mark.vcr
async def test_embed_returns_vectors_of_requested_dim():
    vectors = await GeminiAdapter(API_KEY).embed(EMBED_MODEL, ["boxed warning", "kubectl"], 768)
    assert len(vectors) == 2
    assert all(len(v) == 768 for v in vectors)


@pytest.mark.vcr
async def test_unknown_model_is_non_retryable_provider_error():
    with pytest.raises(ProviderError) as exc_info:
        await GeminiAdapter(API_KEY).complete(
            "gemini-does-not-exist-xyz",
            CompletionRequest(messages=[Message(role=Role.user, content="hi")]),
        )
    assert exc_info.value.retryable is False
    assert exc_info.value.status == 404


def test_empty_response_raises_non_retryable():
    blocked = gtypes.GenerateContentResponse(
        candidates=[gtypes.Candidate(finish_reason=gtypes.FinishReason.SAFETY)]
    )
    with pytest.raises(ProviderError) as exc_info:
        _result_text(blocked)
    assert exc_info.value.retryable is False
    assert "SAFETY" in str(exc_info.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/llm/test_deterministic_adapter.py tests/llm/test_gemini_adapter.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'driftline.llm.adapters.deterministic'`

- [ ] **Step 3: Implement the adapters**

`backend/src/driftline/llm/adapters/deterministic.py`:
```python
import hashlib
import math

from driftline.clock import Clock, SystemClock
from driftline.llm.types import CompletionRequest, CompletionResult, Role, Usage


class DeterministicAdapter:
    """A real in-process provider with deterministic output and scriptable failures.

    Used by benchmarks (to measure the system, not provider quota) and to exercise
    routing failure paths. It is product code, not a test double.
    """

    def __init__(
        self,
        name: str = "deterministic",
        *,
        latency_ms: float = 0.0,
        script: list[Exception | None] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.name = name
        self.latency_ms = latency_ms
        self.calls: list[str] = []
        self._script = list(script or [])
        self._clock = clock or SystemClock()

    async def _step(self, model: str) -> None:
        self.calls.append(model)
        if self._script:
            outcome = self._script.pop(0)
            if outcome is not None:
                raise outcome
        if self.latency_ms:
            await self._clock.sleep(self.latency_ms / 1000)

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        await self._step(model)
        prompt = next(
            (m.content for m in reversed(request.messages) if m.role is Role.user), ""
        )
        text = f"[{model}] {prompt}"
        return CompletionResult(
            text=text,
            model=model,
            provider=self.name,
            usage=Usage(input_tokens=len(prompt.split()), output_tokens=len(text.split())),
            latency_ms=self.latency_ms,
        )

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        await self._step(model)
        return [_vector(t, dim) for t in texts]


def _vector(text: str, dim: int) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    values = [(digest[i % len(digest)] ^ (i * 31 % 256)) / 255.0 - 0.5 for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
```

`backend/src/driftline/llm/adapters/gemini.py`:
```python
import httpx
from google import genai
from google.genai import errors
from google.genai import types as gtypes

from driftline.clock import Clock, SystemClock
from driftline.llm.types import CompletionRequest, CompletionResult, ProviderError, Role, Usage

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _result_text(response: gtypes.GenerateContentResponse) -> str:
    text = response.text
    if not text:
        reason = response.candidates[0].finish_reason if response.candidates else None
        reason_name = getattr(reason, "name", reason)
        raise ProviderError(
            f"empty response from gemini (finish_reason={reason_name})", retryable=False
        )
    return text


class GeminiAdapter:
    name = "gemini"

    def __init__(self, api_key: str, *, clock: Clock | None = None) -> None:
        self._client = genai.Client(api_key=api_key)
        self._clock = clock or SystemClock()

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        system = "\n".join(m.content for m in request.messages if m.role is Role.system) or None
        contents = [
            gtypes.Content(
                role="user" if m.role is Role.user else "model",
                parts=[gtypes.Part(text=m.content)],
            )
            for m in request.messages
            if m.role is not Role.system
        ]
        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
        )
        start = self._clock.now()
        try:
            response = await self._client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.APIError as exc:
            raise ProviderError(
                str(exc), retryable=exc.code in RETRYABLE_STATUS, status=exc.code
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"transport error: {exc}", retryable=True) from exc
        usage = response.usage_metadata
        return CompletionResult(
            text=_result_text(response),
            model=model,
            provider=self.name,
            usage=Usage(
                input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                output_tokens=(usage.candidates_token_count or 0) if usage else 0,
            ),
            latency_ms=(self._clock.now() - start) * 1000,
        )

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        try:
            response = await self._client.aio.models.embed_content(
                model=model,
                contents=texts,
                config=gtypes.EmbedContentConfig(output_dimensionality=dim),
            )
        except errors.APIError as exc:
            raise ProviderError(
                str(exc), retryable=exc.code in RETRYABLE_STATUS, status=exc.code
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(f"transport error: {exc}", retryable=True) from exc
        return [list(e.values) for e in response.embeddings]
```

- [ ] **Step 4: Run the deterministic tests and the offline Gemini test**

Run: `cd backend && uv run pytest tests/llm/test_deterministic_adapter.py "tests/llm/test_gemini_adapter.py::test_empty_response_raises_non_retryable" -v`
Expected: 5 passed.

- [ ] **Step 5: Record the Gemini cassettes once, using the real API key**

Run: `cd backend && DRIFTLINE_GEMINI_API_KEY=<your key> uv run pytest tests/llm/test_gemini_adapter.py --record-mode=once -v`
Expected: 4 passed. Cassettes are written under `tests/llm/cassettes/test_gemini_adapter/`.

Run: `grep -ri "x-goog-api-key\|key=" backend/tests/llm/cassettes || echo "clean"`
Expected: `clean` (if the key appears anywhere, fix `vcr_config` and re-record before committing).

If `DRIFTLINE_GEMINI_API_KEY` is not available to the subagent, stop and report **BLOCKED: need Gemini key to record cassettes**. Do not hand-write cassettes.

- [ ] **Step 6: Verify replay works without a key**

Run: `cd backend && env -u DRIFTLINE_GEMINI_API_KEY uv run pytest tests/llm/test_gemini_adapter.py -v`
Expected: 4 passed, with no network access (record mode defaults to `none`).

- [ ] **Step 7: Commit**

```bash
git add backend/src/driftline/llm/adapters backend/tests/llm/test_deterministic_adapter.py backend/tests/llm/test_gemini_adapter.py backend/tests/llm/cassettes
git commit -m "feat(p1): Gemini and deterministic provider adapters with recorded tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: LLM router: retries, fallback chain, breakers, quota (Wave 2)

**Files:**
- Create: `backend/src/driftline/llm/router.py`
- Test: `backend/tests/llm/test_router.py`

**Interfaces:**
- Consumes:
  - `CircuitBreaker` (T4), `RedisTokenBucket` and `RateLimitTimeout` (T3)
  - `DeterministicAdapter` and `GeminiAdapter` (T5)
  - `driftline.llm.types` (T0) and `Settings` (T0)
- Produces `driftline.llm.router`:
  - `Route(provider: str, model: str)`, a frozen dataclass
  - `AllRoutesFailed(Exception)` with `.errors: list[tuple[Route, Exception]]`
  - `LLMRouter(providers: dict[str, LLMProvider], chains: dict[str, list[Route]], *, clock: Clock, buckets: dict[str, RedisTokenBucket] | None = None, breaker_factory: Callable[[], CircuitBreaker] | None = None, max_attempts: int = 3, base_backoff_s: float = 0.5, bucket_timeout_s: float = 30.0)` with:
    - `async complete(tier: str, request: CompletionRequest) -> CompletionResult`: sets `degraded=True` when a non-first route served the request
    - `async embed(tier: str, texts: list[str], dim: int) -> list[list[float]]`
    - `breaker(route: Route) -> CircuitBreaker`
  - `build_router(settings: Settings, redis, *, clock: Clock) -> LLMRouter`: builds the tiers `extract`, `answer` and `embed` from settings
  - Buckets are keyed by **model name**.

- [ ] **Step 1: Write the failing tests**

`backend/tests/llm/test_router.py`:
```python
import pytest

from driftline.clock import ManualClock
from driftline.config import Settings
from driftline.llm.adapters.deterministic import DeterministicAdapter
from driftline.llm.breaker import CircuitBreaker
from driftline.llm.ratelimit import RedisTokenBucket
from driftline.llm.router import AllRoutesFailed, LLMRouter, Route, build_router
from driftline.llm.types import CompletionRequest, Message, ProviderError, Role


def req(text="hello"):
    return CompletionRequest(messages=[Message(role=Role.user, content=text)])


def retryable():
    return ProviderError("rate limited", retryable=True, status=429)


def fatal():
    return ProviderError("bad request", retryable=False, status=400)


def router(primary, secondary, clock, **kw):
    return LLMRouter(
        providers={"p": primary, "s": secondary},
        chains={"answer": [Route("p", "pro"), Route("s", "flash")]},
        clock=clock,
        **kw,
    )


async def test_primary_success_is_not_degraded():
    clock = ManualClock()
    p, s = DeterministicAdapter("p"), DeterministicAdapter("s")
    result = await router(p, s, clock).complete("answer", req())
    assert result.provider == "p"
    assert result.degraded is False
    assert s.calls == []


async def test_retryable_errors_are_retried_with_backoff_on_same_route():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[retryable(), retryable(), None])
    s = DeterministicAdapter("s")
    result = await router(p, s, clock).complete("answer", req())
    assert result.provider == "p"
    assert p.calls == ["pro", "pro", "pro"]
    assert s.calls == []
    assert clock.now() > 0


async def test_non_retryable_error_falls_back_immediately_and_marks_degraded():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal()])
    s = DeterministicAdapter("s")
    result = await router(p, s, clock).complete("answer", req())
    assert result.provider == "s"
    assert result.model == "flash"
    assert result.degraded is True
    assert p.calls == ["pro"]


async def test_all_routes_failing_raises_with_every_error():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal()])
    s = DeterministicAdapter("s", script=[fatal()])
    with pytest.raises(AllRoutesFailed) as exc_info:
        await router(p, s, clock).complete("answer", req())
    assert [r.provider for r, _ in exc_info.value.errors] == ["p", "s"]


async def test_open_breaker_skips_provider_without_calling_it():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal(), fatal()])
    s = DeterministicAdapter("s")
    r = router(p, s, clock, breaker_factory=lambda: CircuitBreaker(clock=clock, failure_threshold=2))
    await r.complete("answer", req())
    await r.complete("answer", req())
    third = await r.complete("answer", req())
    assert third.provider == "s"
    assert p.calls == ["pro", "pro"]


async def test_quota_bucket_makes_caller_wait(redis_client):
    clock = ManualClock(1000.0)
    bucket = RedisTokenBucket(redis_client, "rl:pro", capacity=1, refill_per_sec=1.0, clock=clock)
    p, s = DeterministicAdapter("p"), DeterministicAdapter("s")
    r = router(p, s, clock, buckets={"pro": bucket})
    await r.complete("answer", req())
    await r.complete("answer", req())
    assert clock.now() == pytest.approx(1001.0)
    assert p.calls == ["pro", "pro"]


async def test_quota_timeout_falls_back_to_next_route(redis_client):
    clock = ManualClock(1000.0)
    bucket = RedisTokenBucket(redis_client, "rl:pro", capacity=1, refill_per_sec=0.01, clock=clock)
    p, s = DeterministicAdapter("p"), DeterministicAdapter("s")
    r = router(p, s, clock, buckets={"pro": bucket}, bucket_timeout_s=5)
    await r.complete("answer", req())
    second = await r.complete("answer", req())
    assert second.provider == "s"
    assert second.degraded is True


async def test_non_provider_errors_propagate_without_fallback():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[ValueError("bug in adapter")])
    s = DeterministicAdapter("s")
    with pytest.raises(ValueError):
        await router(p, s, clock).complete("answer", req())
    assert s.calls == []


async def test_embed_uses_tier_chain_with_fallback():
    clock = ManualClock()
    p = DeterministicAdapter("p", script=[fatal()])
    s = DeterministicAdapter("s")
    r = LLMRouter(
        providers={"p": p, "s": s},
        chains={"embed": [Route("p", "e1"), Route("s", "e2")]},
        clock=clock,
    )
    vectors = await r.embed("embed", ["a", "b"], 768)
    assert len(vectors) == 2 and len(vectors[0]) == 768
    assert s.calls == ["e2"]


async def test_build_router_tiers_follow_settings(redis_client):
    settings = Settings(
        _env_file=None,
        gemini_api_key="unused-in-this-test",
        model_extract="fx",
        model_answer="px",
        model_fallback=["f1", "f2"],
        model_embed="ex",
    )
    r = build_router(settings, redis_client, clock=ManualClock())
    assert [x.model for x in r.chains["answer"]] == ["px", "f1", "f2"]
    assert [x.model for x in r.chains["extract"]] == ["fx", "f1", "f2"]
    assert [x.model for x in r.chains["embed"]] == ["ex"]
    assert {x.provider for c in r.chains.values() for x in c} == {"gemini"}


def test_build_router_requires_gemini_key(redis_client):
    with pytest.raises(ValueError):
        build_router(Settings(_env_file=None, gemini_api_key=None), redis_client, clock=ManualClock())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/llm/test_router.py -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'driftline.llm.router'`

- [ ] **Step 3: Implement the router**

`backend/src/driftline/llm/router.py`:
```python
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from redis.asyncio import Redis

from driftline.clock import Clock
from driftline.config import Settings
from driftline.llm.adapters.gemini import GeminiAdapter
from driftline.llm.breaker import CircuitBreaker
from driftline.llm.ratelimit import RateLimitTimeout, RedisTokenBucket
from driftline.llm.types import CompletionRequest, CompletionResult, LLMProvider, ProviderError

T = TypeVar("T")


@dataclass(frozen=True)
class Route:
    provider: str
    model: str


class CircuitOpenError(Exception):
    pass


class AllRoutesFailed(Exception):
    def __init__(self, errors: list[tuple[Route, Exception]]) -> None:
        summary = "; ".join(f"{r.provider}/{r.model}: {e}" for r, e in errors)
        super().__init__(f"all routes failed: {summary}")
        self.errors = errors


class LLMRouter:
    def __init__(
        self,
        providers: dict[str, LLMProvider],
        chains: dict[str, list[Route]],
        *,
        clock: Clock,
        buckets: dict[str, RedisTokenBucket] | None = None,
        breaker_factory: Callable[[], CircuitBreaker] | None = None,
        max_attempts: int = 3,
        base_backoff_s: float = 0.5,
        bucket_timeout_s: float = 30.0,
    ) -> None:
        self.providers = providers
        self.chains = chains
        self._clock = clock
        self._buckets = buckets or {}
        self._breaker_factory = breaker_factory or (lambda: CircuitBreaker(clock=clock))
        self._breakers: dict[Route, CircuitBreaker] = {}
        self._max_attempts = max_attempts
        self._base_backoff_s = base_backoff_s
        self._bucket_timeout_s = bucket_timeout_s

    def breaker(self, route: Route) -> CircuitBreaker:
        if route not in self._breakers:
            self._breakers[route] = self._breaker_factory()
        return self._breakers[route]

    async def complete(self, tier: str, request: CompletionRequest) -> CompletionResult:
        result, index = await self._run(tier, lambda p, m: p.complete(m, request))
        return result.model_copy(update={"degraded": index > 0})

    async def embed(self, tier: str, texts: list[str], dim: int) -> list[list[float]]:
        vectors, _ = await self._run(tier, lambda p, m: p.embed(m, texts, dim))
        return vectors

    async def _run(
        self, tier: str, call: Callable[[LLMProvider, str], Awaitable[T]]
    ) -> tuple[T, int]:
        errors: list[tuple[Route, Exception]] = []
        for index, route in enumerate(self.chains[tier]):
            breaker = self.breaker(route)
            if not breaker.allow():
                errors.append((route, CircuitOpenError(f"{route.provider}/{route.model} open")))
                continue
            provider = self.providers[route.provider]
            for attempt in range(self._max_attempts):
                bucket = self._buckets.get(route.model)
                if bucket is not None:
                    try:
                        await bucket.acquire(1.0, timeout=self._bucket_timeout_s)
                    except RateLimitTimeout as exc:
                        errors.append((route, exc))
                        break
                try:
                    result = await call(provider, route.model)
                except ProviderError as exc:
                    breaker.record_failure()
                    errors.append((route, exc))
                    last = attempt == self._max_attempts - 1
                    if not exc.retryable or last or not breaker.allow():
                        break
                    await self._clock.sleep(self._backoff(attempt))
                    continue
                breaker.record_success()
                return result, index
        raise AllRoutesFailed(errors)

    def _backoff(self, attempt: int) -> float:
        return self._base_backoff_s * (2**attempt) * random.uniform(0.5, 1.5)


def build_router(settings: Settings, redis: Redis, *, clock: Clock) -> LLMRouter:
    if not settings.gemini_api_key:
        raise ValueError("DRIFTLINE_GEMINI_API_KEY is required to build the LLM router")
    fallbacks = [Route("gemini", m) for m in settings.model_fallback]
    chains = {
        "extract": [Route("gemini", settings.model_extract), *fallbacks],
        "answer": [Route("gemini", settings.model_answer), *fallbacks],
        "embed": [Route("gemini", settings.model_embed)],
    }
    return LLMRouter(
        providers={"gemini": GeminiAdapter(settings.gemini_api_key, clock=clock)},
        chains=chains,
        clock=clock,
    )
```

Note: `chains["extract"]` may list the same model twice when `model_extract` is also in `model_fallback`. That's harmless, because both entries share one breaker (the `Route` is equal), so an open breaker skips both.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/llm -v`
Expected: every LLM test passes (router: 11 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/src/driftline/llm/router.py backend/tests/llm/test_router.py
git commit -m "feat(p1): LLM router with retries, fallback chain, breakers and shared quota

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Gateway health API (Wave 1)

**Files:**
- Create: `backend/src/driftline/gateway/app.py`, `backend/src/driftline/gateway/main.py`
- Test: `backend/tests/gateway/test_health.py`

**Interfaces:**
- Consumes: `Settings` (T0) and fixtures `pg_dsn` and `redis_url`.
- Produces:
  - `driftline.gateway.app.create_app(settings: Settings) -> FastAPI`, whose lifespan creates `app.state.pg` (an asyncpg pool) and `app.state.redis`
  - `GET /healthz` → `200 {"status": "ok"}`
  - `GET /readyz` → `200 {"postgres": "ok", "redis": "ok"}`, or `503` with the failing component set to `"error"`
  - `driftline.gateway.main:app`, a module-level app for uvicorn

- [ ] **Step 1: Write the failing tests**

`backend/tests/gateway/test_health.py`:
```python
from contextlib import asynccontextmanager

import httpx

from driftline.config import Settings
from driftline.gateway.app import create_app


@asynccontextmanager
async def client_for(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_healthz(pg_dsn, redis_url):
    async with client_for(Settings(_env_file=None, database_url=pg_dsn, redis_url=redis_url)) as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_when_dependencies_are_up(pg_dsn, redis_url):
    async with client_for(Settings(_env_file=None, database_url=pg_dsn, redis_url=redis_url)) as c:
        r = await c.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"postgres": "ok", "redis": "ok"}


async def test_readyz_reports_unreachable_redis(pg_dsn):
    settings = Settings(_env_file=None, database_url=pg_dsn, redis_url="redis://127.0.0.1:1/0")
    async with client_for(settings) as c:
        r = await c.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"postgres": "ok", "redis": "error"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/gateway -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'driftline.gateway.app'`

- [ ] **Step 3: Implement the gateway**

`backend/src/driftline/gateway/app.py`:
```python
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from driftline.config import Settings


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pg = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
        app.state.redis = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
        )
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.pg.close()

    app = FastAPI(title="Driftline", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        status = {"postgres": "ok", "redis": "ok"}
        try:
            async with app.state.pg.acquire() as conn:
                await conn.fetchval("SELECT 1")
        except Exception:  # noqa: BLE001 - readiness reports any failure
            status["postgres"] = "error"
        try:
            await app.state.redis.ping()
        except Exception:  # noqa: BLE001
            status["redis"] = "error"
        code = 200 if all(v == "ok" for v in status.values()) else 503
        return JSONResponse(status, status_code=code)

    return app
```

`backend/src/driftline/gateway/main.py`:
```python
from driftline.config import Settings
from driftline.gateway.app import create_app

app = create_app(Settings())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/gateway -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/driftline/gateway/app.py backend/src/driftline/gateway/main.py backend/tests/gateway
git commit -m "feat(p1): gateway with health and readiness endpoints

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Container image, Compose gateway service, CI (Wave 2)

**Files:**
- Create: `backend/Dockerfile`, `backend/.dockerignore`, `.github/workflows/ci.yml`
- Modify: `deploy/compose/docker-compose.yml` (add the `gateway` service)

**Interfaces:**
- Consumes: `python -m driftline.db.migrate` (T1) and `driftline.gateway.main:app` (T7).
- Produces: `docker compose -f deploy/compose/docker-compose.yml up -d --build`, which serves the gateway on `localhost:8000` with migrations applied, and CI that runs ruff and the full test suite on every push and PR.

- [ ] **Step 1: Write the failing check**

Run: `docker compose -f deploy/compose/docker-compose.yml up -d --build && sleep 5 && curl -fsS localhost:8000/readyz`
Expected: FAIL. `curl: (7) Failed to connect to localhost port 8000` (there is no gateway service yet).

- [ ] **Step 2: Add the Dockerfile, the Compose service and the CI workflow**

`backend/.dockerignore`:
```
.venv
.pytest_cache
.ruff_cache
tests
**/__pycache__
```

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "python -m driftline.db.migrate && uvicorn driftline.gateway.main:app --host 0.0.0.0 --port 8000"]
```

Add this under `services:` in `deploy/compose/docker-compose.yml`:
```yaml
  gateway:
    build: ../../backend
    environment:
      DRIFTLINE_DATABASE_URL: postgresql://driftline:driftline@postgres:5432/driftline
      DRIFTLINE_REDIS_URL: redis://redis:6379/0
      DRIFTLINE_GEMINI_API_KEY: ${DRIFTLINE_GEMINI_API_KEY:-}
    ports: ["8000:8000"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}
```

`.github/workflows/ci.yml`:
```yaml
name: ci
on:
  push:
  pull_request:
jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run pytest -q
```

- [ ] **Step 3: Run the check to verify it passes**

Run: `docker compose -f deploy/compose/docker-compose.yml up -d --build && sleep 8 && curl -fsS localhost:8000/readyz`
Expected: `{"postgres":"ok","redis":"ok"}`

Run: `docker compose -f deploy/compose/docker-compose.yml exec postgres psql -U driftline -c "\dt"`
Expected: a list that includes `doc_versions`, `chunks` and `outbox`.

Run: `docker compose -f deploy/compose/docker-compose.yml down`

Run: `cd backend && uv run ruff check . && uv run pytest -q`
Expected: ruff clean, and every test passes (this is what CI runs).

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile backend/.dockerignore deploy/compose/docker-compose.yml .github/workflows/ci.yml
git commit -m "feat(p1): gateway container, compose service and CI workflow

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## P1 Done Criteria

- On `main`, `cd backend && uv run pytest -q` passes. That covers T0 (4), T1 (7), T2 (7), T3 (7), T4 (8), T5 (8), T6 (11) and T7 (3), 55 tests in total.
- `grep -rnE "unittest.mock|MagicMock|AsyncMock|mock\.patch|monkeypatch" backend/tests` returns nothing.
- `docker compose ... up` serves `/readyz` with 200.
- Gemini cassettes are committed and contain no secrets.
- The orchestrator then writes `docs/superpowers/plans/<date>-p2-ingestion.md` against the merged interfaces.
