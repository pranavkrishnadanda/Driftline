"""POST /v1/ask, GET /v1/jobs/{id}, and the SSE event stream (spec sections 3 and 8)."""

import json
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from driftline.agents.events import ErrorEvent, FinalEvent
from driftline.agents.schemas import AGENT_GROUP, AGENT_STREAM, AnswerSchema, AskJob, AskRequest
from driftline.gateway.sse import (
    ask_event_stream,
    check_stream_slot,
    open_stream,
    resume_point,
    sse_responses,
)

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


async def _job_row(request: Request, job_id: UUID):
    async with request.app.state.pg.acquire() as conn:
        return await conn.fetchrow(
            "SELECT j.id, j.status, j.error, a.body, a.id AS answer_id, "
            "(SELECT coalesce(sum(cost_usd), 0) FROM llm_calls WHERE job_id = j.id) AS cost "
            "FROM jobs j LEFT JOIN answers a ON a.job_id = j.id "
            "WHERE j.id = $1 AND j.kind = 'ask'",
            job_id,
        )


def build_ask_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["ask"])

    @router.post(
        "/ask",
        status_code=202,
        response_model=AskAccepted,
        responses={404: {"description": "unknown tenant"}, 429: {"description": "backpressure"}},
    )
    async def ask(body: AskRequest, request: Request) -> AskAccepted:
        state = request.app.state
        settings = state.settings
        backlog = await agent_backlog(state.redis)
        if backlog > settings.ask_max_pending:
            raise HTTPException(
                status_code=429,
                detail={"code": "backpressure", "backlog": backlog},
                headers={"Retry-After": str(settings.ask_retry_after_s)},
            )
        async with state.pg.acquire() as conn:
            tenant_id = await conn.fetchval("SELECT id FROM tenants WHERE name = $1", body.tenant)
            if tenant_id is None:
                raise HTTPException(status_code=404, detail={"code": "unknown_tenant"})
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

    @router.get("/jobs/{job_id}", response_model=JobStatus, responses={404: {}})
    async def job_status(job_id: UUID, request: Request) -> JobStatus:
        row = await _job_row(request, job_id)
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "unknown_job"})
        return JobStatus(
            job_id=job_id,
            status=row["status"],
            error=row["error"],
            answer=_answer(row) if row["body"] else None,
            cost_usd=float(Decimal(row["cost"])),
        )

    async def events(
        job_id: UUID,
        request: Request,
        last_event_id: str | None = Header(default=None),
        last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
    ) -> StreamingResponse:
        state = request.app.state
        if await _job_row(request, job_id) is None:
            raise HTTPException(status_code=404, detail={"code": "unknown_job"})
        check_stream_slot(state.sse_slots, state.settings.ask_retry_after_s)
        after = await resume_point(state.events, job_id, last_event_id or last_event_id_query)

        async def finished():
            row = await _job_row(request, job_id)
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
