"""SSE event contract (spec section 8). Every event carries a monotonically increasing
integer `id` on the wire (the SSE `id:` field); the payloads are these models."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from driftline.agents.schemas import AnswerSchema, Citation

StepStatus = Literal["started", "completed", "skipped", "retry", "hit", "miss", "failed", "waiting"]


class StepEvent(BaseModel):
    type: Literal["step"] = "step"
    node: str
    status: StepStatus
    detail: dict[str, Any] = {}
    t_ms: float = 0.0  # milliseconds since the ask started


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class ClaimEvent(BaseModel):
    type: Literal["claim"] = "claim"
    idx: int
    verified: bool
    citation: Citation | None = None
    reason: str | None = None


class FinalEvent(BaseModel):
    type: Literal["final"] = "final"
    answer: AnswerSchema


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    retryable: bool
    message: str = ""


AskEvent = Annotated[
    StepEvent | TokenEvent | ClaimEvent | FinalEvent | ErrorEvent, Field(discriminator="type")
]
ASK_EVENT_ADAPTER: TypeAdapter[AskEvent] = TypeAdapter(AskEvent)


DriftVerdict = Literal["still_valid", "changed", "broken"]


class AlertEvent(BaseModel):
    """A drift verdict on a watched answer, streamed on `events:alerts:{tenant}` (P4)."""

    type: Literal["alert"] = "alert"
    drift_event_id: UUID
    answer_id: UUID
    verdict: DriftVerdict
    document_title: str
    old_version_id: UUID | None
    new_version_id: UUID
    before: str | None = None  # cited section text in the old version
    after: str | None = None  # the same section in the new version; None when it is gone
    t: datetime


# The alert stream carries alerts, plus `error` (e.g. events_expired on a stale
# Last-Event-ID). It is a separate union so ask streams never parse an alert.
AlertStreamEvent = Annotated[AlertEvent | ErrorEvent, Field(discriminator="type")]
ALERT_EVENT_ADAPTER: TypeAdapter[AlertStreamEvent] = TypeAdapter(AlertStreamEvent)


def is_terminal(event: BaseModel) -> bool:
    """The stream ends after `final`, or after an `error` the worker will not retry."""
    if isinstance(event, FinalEvent):
        return True
    return isinstance(event, ErrorEvent) and not event.retryable
