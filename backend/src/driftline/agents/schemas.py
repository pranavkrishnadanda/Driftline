"""Answer contract (spec section 5 `AnswerSchema`), ask job payloads, and the strict
structured-output models the LLM fills in (no defaults, every field required)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AGENT_STREAM = "agent"
AGENT_GROUP = "agent-workers"
SourceKind = Literal["openfda", "git_docs", "upload"]
AnswerStatus = Literal["answered", "insufficient_evidence", "refused"]


class Citation(BaseModel):
    chunk_id: UUID
    version_id: UUID
    quote: str


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
    tenant: str = Field(min_length=1)
    as_of: datetime | None = None
    source_kinds: list[SourceKind] | None = None


class AskJob(BaseModel):
    """Payload on the `agent` stream: one ask, already validated by the gateway."""

    job_id: UUID
    tenant_id: UUID
    question: str
    as_of: datetime | None = None
    source_kinds: list[SourceKind] | None = None


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
