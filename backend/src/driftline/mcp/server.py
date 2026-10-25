"""The MCP server (spec section 5): Driftline's tools for agents (Claude Code, Cursor).

Built with the official MCP Python SDK (`mcp` 2.x, where FastMCP is `MCPServer`) and
served over Streamable HTTP from the gateway at `/mcp`. The tools are thin adapters over
the gateway's own services, read from the gateway's `app.state` at call time:

- `ask` creates the job through the same path as `POST /v1/ask` (`submit_ask`) and waits
  for its `final` event on the per-ask event log, up to `timeout_s`; past that it returns
  `{status: "running", job_id}` so the client is never left hanging.
- `list_sources` lists the caller's sources.
- `diff_versions`, `get_timeline` and `watch_answer` read and write the same rows as the
  P4 drift routes, through the query helpers in `driftline.gateway.drift`.

Auth: the per-tenant API key in `Authorization: Bearer`, checked by the SDK's bearer
middleware with `resolve_tenant` as its token verifier. A missing or unknown key is a 401
before any MCP message is handled; tools only ever see the key's own tenant, and an id of
another tenant's row is reported as not found, exactly like an unknown id.
"""

import asyncio
import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, Field
from starlette.datastructures import State

from driftline.agents.events import ErrorEvent, FinalEvent
from driftline.agents.graph import VERSION_START
from driftline.agents.guardrails import extract_as_of_hint
from driftline.agents.schemas import AskRequest, SourceKind
from driftline.auth import TenantRow, Unauthorized, resolve_tenant
from driftline.drift.diff import sections_text_diff
from driftline.gateway.ask import Backpressure, submit_ask
from driftline.gateway.drift import load_timeline, set_answer_watch, tenant_document

# Driftline issues its API keys itself; with no `resource_server_url` the SDK publishes no
# OAuth metadata, so this URL is never advertised. AuthSettings requires one.
KEY_ISSUER = AnyHttpUrl("http://localhost:8010")
_ISO_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}.*")

INSTRUCTIONS = (
    "Driftline answers questions from versioned documents as of a point in time, citing "
    "exact quotes from the versions in force then. Pass `as_of` for any historical or "
    "version-specific question."
)

LIST_SOURCES = (
    "SELECT s.id, s.kind, s.status, s.schedule, s.last_polled_at, count(d.id) AS documents "
    "FROM sources s LEFT JOIN documents d ON d.source_id = s.id "
    "WHERE s.tenant_id = $1 GROUP BY s.id ORDER BY s.kind, s.id"
)


# Review focus 5: a large diff is capped, with an explicit truncation marker.
DIFF_VERSIONS_CAP_BYTES = 16 * 1024

VERSION_NOS = "SELECT version_no FROM doc_versions WHERE document_id = $1 ORDER BY version_no"
VERSION_ID = "SELECT id FROM doc_versions WHERE document_id = $1 AND version_no = $2"
# A section's text is its chunks in order, as the drift engine reads it.
SECTION_CHUNKS = "SELECT section_path, text FROM chunks WHERE version_id = $1 ORDER BY ord"


def transport_security(allowed_hosts: list[str]) -> TransportSecuritySettings:
    """The SDK's DNS rebinding protection for `/mcp`: only these Host headers (`name:*`
    for any port) are served, others get 421; a browser Origin must be one of the same
    hosts over http or https, or it gets 403."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(allowed_hosts),
        allowed_origins=[f"{scheme}://{h}" for h in allowed_hosts for scheme in ("http", "https")],
    )


class TenantKeyVerifier:
    """SDK `TokenVerifier`: a bearer token is valid when it is a tenant's API key."""

    def __init__(self, state: State) -> None:
        self._state = state

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            tenant = await resolve_tenant(self._state.pg, token)
        except Unauthorized:
            return None
        return AccessToken(token=token, client_id=str(tenant.id), subject=tenant.name, scopes=[])


def _caller() -> TenantRow:
    token = get_access_token()
    if token is None:  # the bearer middleware guards every request; never expected
        raise ToolError("not authenticated")
    return TenantRow(id=UUID(token.client_id), name=token.subject or "")


async def resolve_as_of(state: State, tenant_id: UUID, text: str) -> datetime:
    """A free-form `as_of` ("2023", "June 2023", "2024-03-01", "v1.28", or an ISO
    timestamp) as the datetime the REST API would use for it: everything but a full
    timestamp goes through the same `extract_as_of_hint` as a hint in the question."""
    text = text.strip()
    if _ISO_DATETIME.fullmatch(text):
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            pass
        else:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    hint = extract_as_of_hint(f"as of {text}")
    if hint.as_of is not None:
        return hint.as_of
    if hint.version_key is not None:
        async with state.pg.acquire() as conn:
            start = await conn.fetchval(VERSION_START, tenant_id, hint.version_key)
        if start is None:
            raise ToolError(f"as_of {text!r}: no document has version {hint.version_key!r}")
        return start
    raise ToolError(
        f"as_of {text!r} is not a date, year, month or version "
        "(try '2023', 'June 2023', '2023-06-01' or 'v1.28')"
    )


async def wait_for_answer(state: State, job_id: UUID, timeout_s: float) -> dict[str, Any] | None:
    """The job's final answer, read from its event log; None if not done by the timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    after = 0
    # Each read blocks for at most a heartbeat: the event-log client's socket timeout is
    # a few seconds longer than that.
    max_block_s = max(state.settings.sse_heartbeat_s, 0.1)
    while (remaining := deadline - loop.time()) > 0:
        block_ms = max(1, int(min(remaining, max_block_s) * 1000))
        for event_id, event in await state.events.read(job_id, after=after, block_ms=block_ms):
            after = event_id
            if isinstance(event, FinalEvent):
                return event.answer.model_dump(mode="json")
            if isinstance(event, ErrorEvent) and not event.retryable:
                raise ToolError(f"ask {job_id} failed: {event.code} {event.message}".strip())
    return None


async def section_texts(conn: asyncpg.Connection, version_id: UUID) -> dict[str, str]:
    """The version's sections in document order: path -> text (its chunks joined)."""
    grouped: dict[str, list[str]] = {}
    for row in await conn.fetch(SECTION_CHUNKS, version_id):
        grouped.setdefault(row["section_path"], []).append(row["text"])
    return {path: "\n".join(texts) for path, texts in grouped.items()}


def pick_versions(
    document_id: UUID, existing: list[int], from_no: int | None, to_no: int | None
) -> tuple[int, int]:
    """The (from, to) version numbers to diff: by default the latest version and the one
    before it; `to` alone diffs it against its predecessor, `from` alone against latest."""
    for n in (from_no, to_no):
        if n is not None and n not in existing:
            raise ToolError(f"document {document_id}: version {n} not found")
    if len(existing) < 2:
        raise ToolError(f"document {document_id} has only one version; nothing to diff")
    to = to_no if to_no is not None else existing[-1]
    if from_no is None:
        earlier = [n for n in existing if n < to]
        if not earlier:
            raise ToolError(f"version {to} is the first version; pass from_version")
        from_no = earlier[-1]
    if from_no == to:
        raise ToolError("from_version and to_version must differ")
    return from_no, to


def diff_sections_texts(
    old: dict[str, str], new: dict[str, str]
) -> tuple[list[dict[str, str]], list[tuple[str, str | None, str | None]]]:
    """Each section's status in document order (the new version's sections, then the
    ones it removed), and the (path, before, after) of every section that is not
    unchanged."""
    statuses: list[dict[str, str]] = []
    differing: list[tuple[str, str | None, str | None]] = []
    for path in [*new, *(p for p in old if p not in new)]:
        before, after = old.get(path), new.get(path)
        if before is None:
            status = "added"
        elif after is None:
            status = "removed"
        else:
            status = "unchanged" if before == after else "changed"
        statuses.append({"section_path": path, "status": status})
        if status != "unchanged":
            differing.append((path, before, after))
    return statuses, differing


def build_mcp(state: State) -> MCPServer:
    """The MCP server over the gateway's services (`state` is the gateway's `app.state`,
    filled in by its lifespan before the first request)."""
    mcp = MCPServer(
        "driftline",
        instructions=INSTRUCTIONS,
        token_verifier=TenantKeyVerifier(state),
        auth=AuthSettings(issuer_url=KEY_ISSUER, resource_server_url=None),
    )

    @mcp.tool()
    async def ask(
        question: Annotated[str, Field(min_length=1, max_length=2000)],
        as_of: Annotated[
            str | None,
            Field(
                description="When to answer for: an ISO date or timestamp, a year ('2023'), "
                "a month ('June 2023') or a release ('v1.28'). Default: now."
            ),
        ] = None,
        source_kinds: Annotated[
            list[SourceKind] | None, Field(description="Only search these source kinds.")
        ] = None,
        timeout_s: Annotated[
            int, Field(ge=1, le=300, description="Seconds to wait for the answer.")
        ] = 60,
    ) -> dict[str, Any]:
        """Answer a question from the documents in force at `as_of`, with verified
        exact-quote citations. Returns the answer (status, answer, claims, citations,
        as_of, confidence), or {status: "running", job_id} when it takes longer than
        `timeout_s`."""
        caller = _caller()
        when = await resolve_as_of(state, caller.id, as_of) if as_of else None
        body = AskRequest(question=question, as_of=when, source_kinds=source_kinds)
        try:
            job_id = await submit_ask(state, caller, body)
        except Backpressure:
            raise ToolError(
                f"Driftline is busy; retry in {state.settings.ask_retry_after_s} s"
            ) from None
        answer = await wait_for_answer(state, job_id, timeout_s)
        if answer is None:
            return {"status": "running", "job_id": str(job_id)}
        return answer

    @mcp.tool()
    async def list_sources() -> dict[str, Any]:
        """List the document sources Driftline answers from for this API key's tenant:
        id, kind (openfda, git_docs, upload), status, schedule, last poll time and the
        number of documents."""
        caller = _caller()
        async with state.pg.acquire() as conn:
            rows = await conn.fetch(LIST_SOURCES, caller.id)
        return {
            "sources": [
                {
                    "id": str(r["id"]),
                    "kind": r["kind"],
                    "status": r["status"],
                    "schedule": r["schedule"],
                    "last_polled_at": r["last_polled_at"].isoformat()
                    if r["last_polled_at"]
                    else None,
                    "documents": r["documents"],
                }
                for r in rows
            ]
        }

    @mcp.tool()
    async def diff_versions(
        document_id: UUID,
        from_version: Annotated[
            int | None,
            Field(ge=1, description="Version number to diff from. Default: the one before."),
        ] = None,
        to_version: Annotated[
            int | None, Field(ge=1, description="Version number to diff to. Default: latest.")
        ] = None,
    ) -> dict[str, Any]:
        """What changed in a document between two of its versions (default: the previous
        version vs the latest). Version numbers are the `version_no`s from `get_timeline`.
        Returns each section's status (added, removed, changed, unchanged) and one unified
        diff of the sections that differ, capped at 16 KB: when cut, `truncated` is true
        and the diff ends with a "... diff truncated" line."""
        caller = _caller()
        async with state.pg.acquire() as conn:
            if await tenant_document(conn, caller.id, document_id) is None:
                raise ToolError(f"document {document_id} not found")
            existing = [r["version_no"] for r in await conn.fetch(VERSION_NOS, document_id)]
            from_no, to_no = pick_versions(document_id, existing, from_version, to_version)
            from_id = await conn.fetchval(VERSION_ID, document_id, from_no)
            to_id = await conn.fetchval(VERSION_ID, document_id, to_no)
            old = await section_texts(conn, from_id)
            new = await section_texts(conn, to_id)
        sections, differing = diff_sections_texts(old, new)
        diff, truncated = sections_text_diff(differing, DIFF_VERSIONS_CAP_BYTES)
        return {
            "document_id": str(document_id),
            "from_version": from_no,
            "to_version": to_no,
            "from_version_id": str(from_id),
            "to_version_id": str(to_id),
            "sections": sections,
            "diff": diff,
            "truncated": truncated,
        }

    @mcp.tool()
    async def get_timeline(document_id: UUID) -> dict[str, Any]:
        """A document's history: every version (version_no, version_key, its validity
        window valid_from..valid_to, where a null valid_to means in force now, and the
        sections changed from the previous version), plus the relations it declares
        (outgoing, e.g. supersedes) and receives (incoming)."""
        caller = _caller()
        async with state.pg.acquire() as conn:
            timeline = await load_timeline(conn, caller.id, document_id)
        if timeline is None:
            raise ToolError(f"document {document_id} not found")
        return timeline.model_dump(mode="json")

    @mcp.tool()
    async def watch_answer(answer_id: UUID) -> dict[str, Any]:
        """Watch an answer (the `answer_id` that `ask` returned): Driftline re-checks its
        claims whenever a document it cites changes, and raises a drift alert when one
        no longer holds."""
        caller = _caller()
        async with state.pg.acquire() as conn:
            found = await set_answer_watch(conn, caller.id, answer_id, True)
        if not found:
            raise ToolError(f"answer {answer_id} not found")
        return {"answer_id": str(answer_id), "watched": True}

    return mcp
