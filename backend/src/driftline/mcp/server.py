"""The MCP server (spec section 5): Driftline's tools for agents (Claude Code, Cursor).

Built with the official MCP Python SDK (`mcp` 2.x, where FastMCP is `MCPServer`) and
served over Streamable HTTP from the gateway at `/mcp`. The tools are thin adapters over
the gateway's own services, read from the gateway's `app.state` at call time:

- `ask` creates the job through the same path as `POST /v1/ask` (`submit_ask`) and waits
  for its `final` event on the per-ask event log, up to `timeout_s`; past that it returns
  `{status: "running", job_id}` so the client is never left hanging.
- `list_sources` lists the caller's sources.

Auth: the per-tenant API key in `Authorization: Bearer`, checked by the SDK's bearer
middleware with `resolve_tenant` as its token verifier. A missing or unknown key is a 401
before any MCP message is handled; tools only ever see the key's own tenant.
"""

import asyncio
import re
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl, Field
from starlette.datastructures import State

from driftline.agents.events import ErrorEvent, FinalEvent
from driftline.agents.graph import VERSION_START
from driftline.agents.guardrails import extract_as_of_hint
from driftline.agents.schemas import AskRequest, SourceKind
from driftline.auth import TenantRow, Unauthorized, resolve_tenant
from driftline.gateway.ask import Backpressure, submit_ask

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

    return mcp
