"""Answer contract (spec section 5 `AnswerSchema`), ask job payloads, and the strict
structured-output models the LLM fills in (no defaults, every field required)."""

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from driftline.retrieval.types import Evidence

AGENT_STREAM = "agent"
AGENT_GROUP = "agent-workers"
SourceKind = Literal["openfda", "git_docs", "upload"]
AnswerStatus = Literal["answered", "insufficient_evidence", "refused"]


class Citation(BaseModel):
    """A cited chunk, with the metadata of the version it belongs to (for the UI).

    New citations are built with `from_evidence`, which fills every metadata field.
    The fields are optional only so answer bodies stored before they existed (in
    `answers.body` and the semantic cache) still load; the validator keeps them
    all-or-nothing, so a citation is either fully described or a legacy one."""

    chunk_id: UUID
    version_id: UUID
    quote: str
    document_id: UUID | None = None
    title: str | None = None
    external_id: str | None = None
    version_no: int | None = None
    section_path: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None  # None also means "still in force"

    @model_validator(mode="after")
    def _metadata_all_or_nothing(self) -> Self:
        meta = (
            self.document_id,
            self.title,
            self.external_id,
            self.version_no,
            self.section_path,
            self.valid_from,
        )
        missing = sum(v is None for v in meta)
        if missing not in (0, len(meta)) or (missing and self.valid_to is not None):
            raise ValueError("citation metadata must be complete or absent (legacy body)")
        return self

    @classmethod
    def from_evidence(cls, item: "Evidence", quote: str) -> "Citation":
        return cls(
            chunk_id=item.chunk_id,
            version_id=item.version_id,
            quote=quote,
            document_id=item.document_id,
            title=item.title,
            external_id=item.external_id,
            version_no=item.version_no,
            section_path=item.section_path,
            valid_from=item.valid_from,
            valid_to=item.valid_to,
        )


class Claim(BaseModel):
    idx: int
    text: str
    citations: list[Citation]
    verified: bool = False
    reason: str | None = None  # why verification failed, when it did


class NearestSource(BaseModel):
    document_id: UUID
    external_id: str
    title: str
    version_id: UUID
    version_no: int
    section_path: str
    valid_from: datetime
    valid_to: datetime | None = None


class AnswerSchema(BaseModel):
    status: AnswerStatus
    answer: str
    claims: list[Claim] = []
    citations: list[Citation] = []
    dropped_claims: list[Claim] = []  # unsupported after the verifier's retries
    nearest_sources: list[NearestSource] = []  # filled for insufficient_evidence
    as_of: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    degraded: bool = False  # a fallback model was used somewhere
    cached: bool = False  # served from the semantic cache
    answer_id: UUID | None = None
    cost_usd: float = 0.0


class AskRequest(BaseModel):
    """Body of POST /v1/ask."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    # Optional with a bearer API key (which must then be this tenant's key).
    tenant: str | None = Field(default=None, min_length=1)
    as_of: datetime | None = None
    source_kinds: list[SourceKind] | None = None


ReviewAction = Literal["approve", "edit", "reject"]


class ReviewDecision(BaseModel):
    """A reviewer's resolution of a paused ask; the graph resumes with it (`Command`)."""

    review_id: UUID
    action: ReviewAction
    edit: dict | None = None
    by: str


class AskJob(BaseModel):
    """Payload on the `agent` stream: one ask, already validated by the gateway.

    `answer_id` marks a regeneration of that (watched) answer: the result replaces it in
    place and always goes to human review first. `resume` carries a reviewer's decision
    for an ask paused at the review step; the worker resumes the same graph thread."""

    job_id: UUID
    tenant_id: UUID
    question: str
    as_of: datetime | None = None
    source_kinds: list[SourceKind] | None = None
    answer_id: UUID | None = None
    resume: ReviewDecision | None = None


# --- LLM-facing structured outputs -------------------------------------------------


class SubQuestion(BaseModel):
    question: str
    as_of: str | None  # ISO date (YYYY-MM-DD) or null for the ask's as_of


class PlanOutput(BaseModel):
    mode: Literal["single", "fan_out"]
    sub_questions: list[SubQuestion]


class DraftCitation(BaseModel):
    chunk_id: str
    version_id: str
    quote: str


class DraftClaim(BaseModel):
    text: str
    citations: list[DraftCitation]


class DraftOutput(BaseModel):
    answer: str  # first property on purpose: it streams as `token` events
    claims: list[DraftClaim]


class JudgeOutput(BaseModel):
    entailed: bool
    reason: str
