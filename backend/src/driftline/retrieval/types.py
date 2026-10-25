"""Retrieval contract shared by the retriever, the reranker, the cache and the agent."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


@dataclass(frozen=True)
class RetrievalQuery:
    """One hybrid search, restricted to what was in force for `tenant_id` at `as_of`.

    `in_force_only=False` drops the temporal filter (the as-of window and supersession)
    and searches every version of the tenant's documents. Only the plain-RAG eval
    baseline (P7) uses it; the answer graph never does."""

    tenant_id: UUID
    text: str
    as_of: datetime
    source_kinds: tuple[str, ...] | None = None  # corpus filter: sources.kind values
    document_ids: tuple[UUID, ...] | None = None
    exclude_tags: tuple[str, ...] = ()
    in_force_only: bool = True

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")


class Evidence(BaseModel):
    """One retrieved chunk with the provenance a citation needs. JSON-serialisable, so it
    can live in LangGraph state and in the semantic cache."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    version_id: UUID
    document_id: UUID
    external_id: str
    title: str
    section_path: str
    text: str
    tags: list[str] = []
    version_no: int
    valid_from: datetime
    valid_to: datetime | None = None
    retrieved_as_of: datetime  # the as_of this chunk was retrieved for
    score: float = 0.0  # RRF score
    rerank_score: float | None = None
    sub_question: str | None = None

    def in_force_at(self, when: datetime) -> bool:
        return self.valid_from <= when and (self.valid_to is None or when < self.valid_to)
