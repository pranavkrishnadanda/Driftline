"""Watch answers, stream drift alerts, list drift events, and document timelines (P4).

Every route is scoped to the caller's tenant (`require_tenant`: a bearer API key, or in
dev mode the `?tenant=` name, as in `POST /v1/ask`). A row of another tenant is reported
as unknown (404), never as forbidden, so ids do not leak across tenants.
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from driftline.agents.events import DriftVerdict
from driftline.auth import TenantRow
from driftline.gateway.auth import AUTH_RESPONSES, CallerTenant
from driftline.gateway.sse import (
    alert_event_stream,
    check_stream_slot,
    open_stream,
    resume_point,
    sse_responses,
)

ALERTS_SCHEMA_REF = "#/components/schemas/AlertEvents"

Caller = CallerTenant


class WatchState(BaseModel):
    answer_id: UUID
    watched: bool


class DriftEventOut(BaseModel):
    id: UUID
    answer_id: UUID
    claim_idx: int
    verdict: DriftVerdict
    old_version_id: UUID | None
    new_version_id: UUID | None
    document_id: UUID | None
    document_title: str | None
    section_path: str | None = None
    before: str | None = None
    after: str | None = None
    diff: str | None = None
    created_at: datetime


class DriftEventList(BaseModel):
    events: list[DriftEventOut]


class TimelineVersion(BaseModel):
    version_id: UUID
    version_no: int
    version_key: str | None
    valid_from: datetime
    valid_to: datetime | None  # None: the version in force now
    diff_from_prev: dict[str, Any] | None
    created_at: datetime


class TimelineRelation(BaseModel):
    """A relation touching the document. For an outgoing one, `document_*` is the
    document it points at; for an incoming one, the document whose version declared it."""

    id: UUID
    kind: str
    status: str
    confidence: float
    src_version_id: UUID
    document_id: UUID
    document_title: str | None


class TimelineRelations(BaseModel):
    outgoing: list[TimelineRelation]
    incoming: list[TimelineRelation]


class DocumentTimeline(BaseModel):
    document_id: UUID
    external_id: str
    title: str | None
    versions: list[TimelineVersion]
    relations: TimelineRelations


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


# Shared with the MCP tools (`driftline.mcp.server`), so both surfaces read the same rows.


async def set_answer_watch(
    conn: asyncpg.Connection, tenant_id: UUID, answer_id: UUID, on: bool
) -> bool:
    """Watch or unwatch one of the tenant's answers; False if it has no such answer.
    Watching again keeps the original watch time."""
    found = await conn.fetchval(
        "UPDATE answers SET watched = $3, "
        "watched_at = CASE WHEN NOT $3 THEN NULL WHEN watched THEN watched_at "
        "ELSE now() END "
        "WHERE id = $1 AND tenant_id = $2 RETURNING id",
        answer_id,
        tenant_id,
        on,
    )
    return found is not None


async def tenant_document(
    conn: asyncpg.Connection, tenant_id: UUID, document_id: UUID
) -> asyncpg.Record | None:
    """The document (id, external_id, title) if it belongs to the tenant, else None."""
    return await conn.fetchrow(
        "SELECT d.id, d.external_id, d.title FROM documents d "
        "JOIN sources s ON s.id = d.source_id WHERE d.id = $1 AND s.tenant_id = $2",
        document_id,
        tenant_id,
    )


async def load_timeline(
    conn: asyncpg.Connection, tenant_id: UUID, document_id: UUID
) -> DocumentTimeline | None:
    """The document's timeline, or None if the tenant has no such document."""
    doc = await tenant_document(conn, tenant_id, document_id)
    if doc is None:
        return None
    versions = await conn.fetch(
        "SELECT id AS version_id, version_no, version_key, valid_from, valid_to, "
        "diff_from_prev, created_at FROM doc_versions WHERE document_id = $1 "
        "ORDER BY version_no",
        document_id,
    )
    # Both sides of a relation are kept within the tenant.
    outgoing = await conn.fetch(
        "SELECT r.id, r.kind, r.status, r.confidence, r.src_version_id, "
        "o.id AS document_id, o.title AS document_title "
        "FROM relations r JOIN doc_versions v ON v.id = r.src_version_id "
        "JOIN documents o ON o.id = r.dst_document_id "
        "JOIN sources s ON s.id = o.source_id "
        "WHERE v.document_id = $1 AND s.tenant_id = $2 ORDER BY v.version_no, r.id",
        document_id,
        tenant_id,
    )
    incoming = await conn.fetch(
        "SELECT r.id, r.kind, r.status, r.confidence, r.src_version_id, "
        "o.id AS document_id, o.title AS document_title "
        "FROM relations r JOIN doc_versions v ON v.id = r.src_version_id "
        "JOIN documents o ON o.id = v.document_id "
        "JOIN sources s ON s.id = o.source_id "
        "WHERE r.dst_document_id = $1 AND s.tenant_id = $2 "
        "ORDER BY v.valid_from, r.id",
        document_id,
        tenant_id,
    )
    return DocumentTimeline(
        document_id=doc["id"],
        external_id=doc["external_id"],
        title=doc["title"],
        versions=[
            TimelineVersion(**{**dict(v), "diff_from_prev": _json(v["diff_from_prev"])})
            for v in versions
        ],
        relations=TimelineRelations(
            outgoing=[TimelineRelation(**dict(r)) for r in outgoing],
            incoming=[TimelineRelation(**dict(r)) for r in incoming],
        ),
    )


def build_drift_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["drift"])
    not_found = {
        **AUTH_RESPONSES,
        404: {"description": "unknown tenant, or not found in this tenant"},
    }

    async def set_watch(
        request: Request, answer_id: UUID, caller: TenantRow, on: bool
    ) -> WatchState:
        async with request.app.state.pg.acquire() as conn:
            found = await set_answer_watch(conn, caller.id, answer_id, on)
        if not found:
            raise HTTPException(status_code=404, detail={"code": "unknown_answer"})
        return WatchState(answer_id=answer_id, watched=on)

    @router.post("/answers/{answer_id}/watch", response_model=WatchState, responses=not_found)
    async def watch(answer_id: UUID, request: Request, caller: TenantRow = Caller) -> WatchState:
        """Re-check this answer whenever a document it cites changes."""
        return await set_watch(request, answer_id, caller, True)

    @router.delete("/answers/{answer_id}/watch", response_model=WatchState, responses=not_found)
    async def unwatch(answer_id: UUID, request: Request, caller: TenantRow = Caller) -> WatchState:
        return await set_watch(request, answer_id, caller, False)

    async def alerts(
        request: Request,
        caller: TenantRow = Caller,
        last_event_id: str | None = Header(default=None),
        last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
    ) -> StreamingResponse:
        state = request.app.state
        tenant_id = caller.id
        check_stream_slot(state.sse_slots, state.settings.ask_retry_after_s)
        after = await resume_point(state.alerts, tenant_id, last_event_id or last_event_id_query)
        return await open_stream(
            state.sse_slots,
            alert_event_stream(
                state.alerts, tenant_id, after=after, heartbeat_s=state.settings.sse_heartbeat_s
            ),
        )

    router.add_api_route(
        "/alerts/stream",
        alerts,
        methods=["GET"],
        response_class=StreamingResponse,
        responses={
            **AUTH_RESPONSES,
            **sse_responses(
                ALERTS_SCHEMA_REF,
                ends="open-ended: one `alert` per drift verdict on a watched answer.",
                not_found="unknown tenant",
            ),
        },
        summary="Drift alerts for a tenant (SSE)",
    )

    @router.get("/drift/events", response_model=DriftEventList, responses=not_found)
    async def drift_events(
        request: Request,
        caller: TenantRow = Caller,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> DriftEventList:
        """Drift verdicts on this tenant's answers, latest first."""
        tenant_id = caller.id
        async with request.app.state.pg.acquire() as conn:
            rows = await conn.fetch(
                "SELECT e.id, e.answer_id, e.claim_idx, e.verdict, e.old_version_id, "
                "e.new_version_id, e.detail, e.created_at, d.id AS document_id, "
                "d.title AS document_title "
                "FROM drift_events e "
                "LEFT JOIN doc_versions v ON v.id = coalesce(e.new_version_id, e.old_version_id) "
                "LEFT JOIN documents d ON d.id = v.document_id "
                "WHERE e.tenant_id = $1 "
                "ORDER BY e.created_at DESC, e.id DESC LIMIT $2",
                tenant_id,
                limit,
            )
        events = []
        for row in rows:
            detail = _json(row["detail"]) or {}
            events.append(
                DriftEventOut(
                    **{k: v for k, v in row.items() if k != "detail"},
                    section_path=detail.get("section_path"),
                    before=detail.get("before"),
                    after=detail.get("after"),
                    diff=detail.get("diff"),
                )
            )
        return DriftEventList(events=events)

    @router.get(
        "/documents/{document_id}/timeline", response_model=DocumentTimeline, responses=not_found
    )
    async def timeline(
        document_id: UUID, request: Request, caller: TenantRow = Caller
    ) -> DocumentTimeline:
        """Every version of a document with its validity window and diff from the previous
        version, plus the relations it declares (outgoing) and receives (incoming)."""
        async with request.app.state.pg.acquire() as conn:
            found = await load_timeline(conn, caller.id, document_id)
        if found is None:
            raise HTTPException(status_code=404, detail={"code": "unknown_document"})
        return found

    return router
