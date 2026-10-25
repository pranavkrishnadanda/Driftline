"""The human review queue over HTTP (spec section 8): list a tenant's items, resolve one.

Scoped to the caller's tenant (`require_tenant`). An item of another tenant is reported
as unknown (404), never as forbidden. A second or concurrent resolve gets 409, and only
the one successful resolution has any effect (`ReviewQueue.resolve`).
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from driftline.agents.schemas import ReviewAction
from driftline.auth import TenantRow
from driftline.gateway.auth import AUTH_RESPONSES, CallerTenant
from driftline.review.queue import (
    AlreadyResolved,
    InvalidResolution,
    ReviewItem,
    ReviewKind,
    ReviewNotFound,
    ReviewQueue,
    ReviewStatus,
)

LimitQuery = Query(default=100, ge=1, le=500)


class ReviewItemList(BaseModel):
    items: list[ReviewItem]


class ResolveRequest(BaseModel):
    """`edit` goes with action `edit` only: `{"kind": ...}` for a relation, or
    `{"answer": "..."}` for an answer item."""

    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    edit: dict[str, Any] | None = None
    by: str = Field(min_length=1, max_length=200, description="who resolved it")


def build_review_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["review"])
    not_found = {**AUTH_RESPONSES, 404: {"description": "unknown tenant or review item"}}

    def queue(request: Request) -> ReviewQueue:
        return ReviewQueue(request.app.state.pg)

    @router.get("/review", response_model=ReviewItemList, responses=not_found)
    async def list_review(
        request: Request,
        caller: TenantRow = CallerTenant,
        kind: ReviewKind | None = None,
        status: ReviewStatus = "open",
        limit: int = LimitQuery,
    ) -> ReviewItemList:
        """This tenant's review items, oldest first."""
        items = await queue(request).list(caller.id, status=status, kind=kind, limit=limit)
        return ReviewItemList(items=items)

    @router.post(
        "/review/{item_id}/resolve",
        response_model=ReviewItem,
        responses={
            **not_found,
            409: {"description": "already resolved"},
            422: {"description": "the action or edit does not fit this item"},
        },
    )
    async def resolve(
        item_id: UUID, body: ResolveRequest, request: Request, caller: TenantRow = CallerTenant
    ) -> ReviewItem:
        """Approve, edit or reject an item. Resolving a paused answer resumes its ask; an
        approved broken answer is regenerated; an edit becomes an eval case."""
        try:
            return await queue(request).resolve(
                item_id, body.action, body.edit, by=body.by, tenant_id=caller.id
            )
        except ReviewNotFound:
            raise HTTPException(status_code=404, detail={"code": "unknown_review_item"}) from None
        except AlreadyResolved:
            raise HTTPException(status_code=409, detail={"code": "already_resolved"}) from None
        except InvalidResolution as exc:
            raise HTTPException(
                status_code=422, detail={"code": "invalid_resolution", "message": str(exc)}
            ) from None

    return router
