"""POST /v1/ask, GET /v1/jobs/{id}, and the SSE event stream (spec sections 3 and 8)."""

import json
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from driftline.agents.events import ErrorEvent, FinalEvent
from driftline.agents.schemas import AGENT_GROUP, AGENT_STREAM, AnswerSchema, AskJob, AskRequest
from driftline.auth import TenantRow
from driftline.gateway.auth import (
    AUTH_RESPONSES,
    BearerKey,
    OptionalCaller,
    caller_tenant,
    unauthorized,
)
from driftline.gateway.sse import (
    ask_event_stream,
    check_stream_slot,
    open_stream,
    resume_point,
    sse_responses,
)
from driftline.obs.cost import job_cost

EVENTS_SCHEMA_REF = "#/components/schemas/AskEvent"


class AskAccepted(BaseModel):
    job_id: UUID
    events_url: str
    status_url: str


class JobStatus(BaseModel):
    job_id: UUID
    status: str
    error: str | None = None
    answer: AnswerSchema | None = None
    cost_usd: float = 0.0


async def agent_backlog(redis: Redis) -> int:
    """Asks queued or in flight: the agent group's pending entries plus its lag."""
    try:
        groups = await redis.xinfo_groups(AGENT_STREAM)
    except ResponseError:  # the stream does not exist yet
        return 0
    group = next((g for g in groups if g["name"] == AGENT_GROUP), None)
    if group is None or group.get("lag") is None:
        # No consumer group yet, or Redis cannot compute the lag: count every entry.
        pending = int(group["pending"]) if group else 0
        return pending + int(await redis.xlen(AGENT_STREAM))
    return int(group["pending"]) + int(group["lag"])


async def _job_row(request: Request, job_id: UUID, caller: TenantRow | None):
    """The ask job with its answer and cost, or None when it is not the caller's.

    `caller` is None only for a dev-mode client that named no tenant: then the job is
    looked up by id alone (and its cost counted for the job's own tenant).
    """
    async with request.app.state.pg.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT j.id, j.tenant_id, j.status, j.error, a.body, a.id AS answer_id "
            "FROM jobs j LEFT JOIN answers a ON a.job_id = j.id AND a.tenant_id = j.tenant_id "
            "WHERE j.id = $1 AND j.kind = 'ask' AND ($2::uuid IS NULL OR j.tenant_id = $2)",
            job_id,
            caller.id if caller is not None else None,
        )
        if row is None:
            return None
        cost = await job_cost(conn, job_id, tenant_id=row["tenant_id"])
    return {**dict(row), "cost": cost.cost_usd}


def build_ask_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["ask"])

    @router.post(
        "/ask",
        status_code=202,
        response_model=AskAccepted,
        responses={
            **AUTH_RESPONSES,
            404: {"description": "unknown tenant"},
            429: {"description": "backpressure"},
        },
    )
    async def ask(
        body: AskRequest,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = BearerKey,
    ) -> AskAccepted:
        state = request.app.state
        settings = state.settings
        # The tenant is named in the body here, so this is `require_tenant` on body.tenant.
        caller = await caller_tenant(request, body.tenant, credentials)
        if caller is None:
            raise unauthorized()
        backlog = await agent_backlog(state.redis)
        if backlog > settings.ask_max_pending:
            raise HTTPException(
                status_code=429,
                detail={"code": "backpressure", "backlog": backlog},
                headers={"Retry-After": str(settings.ask_retry_after_s)},
            )
        tenant_id = caller.id
        async with state.pg.acquire() as conn:
            job_id = await conn.fetchval(
                "INSERT INTO jobs (tenant_id, kind, payload) VALUES ($1, 'ask', $2::jsonb) "
                "RETURNING id",
                tenant_id,
                body.model_dump_json(),
            )
        job = AskJob(
            job_id=job_id,
            tenant_id=tenant_id,
            question=body.question,
            as_of=body.as_of,
            source_kinds=body.source_kinds,
        )
        await state.bus.publish(AGENT_STREAM, job.model_dump(mode="json"))
        return AskAccepted(
            job_id=job_id, events_url=f"/v1/jobs/{job_id}/events", status_url=f"/v1/jobs/{job_id}"
        )

    @router.get("/jobs/{job_id}", response_model=JobStatus, responses={**AUTH_RESPONSES, 404: {}})
    async def job_status(
        job_id: UUID, request: Request, caller: TenantRow | None = OptionalCaller
    ) -> JobStatus:
        row = await _job_row(request, job_id, caller)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "unknown_job"})
        return JobStatus(
            job_id=job_id,
            status=row["status"],
            error=row["error"],
            answer=_answer(row) if row["body"] else None,
            cost_usd=float(row["cost"]),
        )

    async def events(
        job_id: UUID,
        request: Request,
        last_event_id: str | None = Header(default=None),
        last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
        caller: TenantRow | None = OptionalCaller,
    ) -> StreamingResponse:
        state = request.app.state
        if await _job_row(request, job_id, caller) is None:
            raise HTTPException(status_code=404, detail={"code": "unknown_job"})
        check_stream_slot(state.sse_slots, state.settings.ask_retry_after_s)
        after = await resume_point(state.events, job_id, last_event_id or last_event_id_query)

        async def finished():
            row = await _job_row(request, job_id, caller)
            if row is None or row["status"] not in ("succeeded", "failed"):
                return None
            if row["body"]:
                return FinalEvent(answer=_answer(row))
            return ErrorEvent(code="job_failed", retryable=False, message=row["error"] or "")

        return await open_stream(
            state.sse_slots,
            ask_event_stream(
                state.events,
                job_id,
                after=after,
                heartbeat_s=state.settings.sse_heartbeat_s,
                finished=finished,
            ),
        )

    responses = sse_responses(
        EVENTS_SCHEMA_REF,
        ends="ends after `final` or a non-retryable `error`.",
        not_found="unknown job",
    )
    for path in ("/jobs/{job_id}/events", "/ask/{job_id}/events"):
        router.add_api_route(
            path,
            events,
            methods=["GET"],
            response_class=StreamingResponse,
            responses=responses,
            include_in_schema=path.startswith("/jobs"),
        )
    return router


def _answer(row) -> AnswerSchema:
    body = row["body"]
    data = json.loads(body) if isinstance(body, str) else body
    return AnswerSchema.model_validate({**data, "answer_id": row["answer_id"]})
