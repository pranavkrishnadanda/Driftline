"""P7 eval types: golden cases (one JSONL line each), per-case results and run reports.

A golden case must point at real ingested versions: `expected_version_ids` are doc_versions
UUIDs. These types check the shape; the curation tooling checks the ids exist in the DB.
"""

import re
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from driftline.skills.pack import EvalCase

_STRICT = ConfigDict(extra="forbid", frozen=True, strict=True)
_PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]*$")]
# Same kinds as the P6 seed cases (skills/*/eval.jsonl).
CaseKind = Literal["point_in_time", "current", "change", "comparison", "not_in_corpus"]
System = Literal["driftline", "plain_rag", "no_retrieval"]


def _no_duplicates(values: Sequence[object], what: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {what}")


class GoldenCase(BaseModel):
    """One line of evals/golden/<corpus>.jsonl."""

    model_config = _STRICT

    id: Text
    corpus: Slug
    question: Text
    as_of: date
    kind: CaseKind
    expected_answer: Text
    expected_version_ids: list[UUID]
    expected_quotes: list[Text]
    trap: bool  # the answer changed between versions

    @model_validator(mode="after")
    def _consistent(self) -> "GoldenCase":
        if _PLACEHOLDER.search(self.question):
            raise ValueError("question still has a template placeholder")
        _no_duplicates(self.expected_version_ids, "expected_version_ids")
        if self.kind == "not_in_corpus":
            if self.expected_version_ids or self.expected_quotes:
                raise ValueError("a not_in_corpus case expects no versions or quotes")
            if self.trap:
                raise ValueError("a not_in_corpus case cannot be a trap")
        elif not self.expected_version_ids:
            raise ValueError("expected_version_ids must name at least one real version")
        return self


def golden_from_seed(
    seed: EvalCase,
    *,
    corpus: str,
    as_of: date | None = None,
    expected_answer: str,
    expected_version_ids: Sequence[UUID | str],
    expected_quotes: Sequence[str],
    trap: bool,
    question: str | None = None,
) -> GoldenCase:
    """Turn a P6 seed (or ready) EvalCase into a GoldenCase.

    The seed keeps its id and kind; the caller supplies what the seed leaves open. Version
    ids must be real doc_versions UUIDs (a seed's own list is empty by design), so a seed
    with no versions filled in, or with placeholder ids, is rejected with ValueError.
    `question` defaults to the seed's, which must then have no `{placeholder}` left.
    """
    ids: list[UUID] = []
    for raw in expected_version_ids:
        try:
            ids.append(raw if isinstance(raw, UUID) else UUID(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"not a real version id (expected a UUID): {raw!r}") from exc
    when = as_of if as_of is not None else seed.as_of
    if when is None:
        raise ValueError(f"{seed.id}: as_of is required (the seed has none)")
    try:
        return GoldenCase(
            id=seed.id,
            corpus=corpus,
            question=question if question is not None else seed.question,
            as_of=when if isinstance(when, date) else date.fromisoformat(when),
            kind=seed.kind,
            expected_answer=expected_answer,
            expected_version_ids=ids,
            expected_quotes=list(expected_quotes),
            trap=trap,
        )
    except ValidationError as exc:
        raise ValueError(f"{seed.id}: {exc}") from exc


class CaseResult(BaseModel):
    """The outcome of one golden case in one run.

    `stale_case`: an expected version no longer exists (e.g. after re-ingest); the case is
    excluded from metrics and counted, never scored as a model failure. `error`: the system
    failed to produce an answer.
    """

    model_config = _STRICT

    case_id: Text
    status: Literal["scored", "stale_case", "error"]
    answer_status: str | None = None
    answer: str = ""
    cited_version_ids: list[UUID] = []
    scores: dict[str, float] = {}
    latency_ms: float = Field(default=0.0, ge=0.0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    error: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "CaseResult":
        if self.status != "scored" and self.scores:
            raise ValueError(f"a {self.status} result carries no scores")
        if self.status == "error" and not self.error:
            raise ValueError("an error result needs an error message")
        return self


class EvalReport(BaseModel):
    """One eval run: written to eval_runs and evals/reports/<sha>/<corpus>.json."""

    model_config = _STRICT

    system: System
    corpus: Slug
    git_sha: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{7,40}$")]
    llm: Text  # what answered, e.g. "offline extractive LLM (...)" or the Claude models
    metrics: dict[str, float]
    cases: list[CaseResult]

    @model_validator(mode="after")
    def _unique_cases(self) -> "EvalReport":
        _no_duplicates([c.case_id for c in self.cases], "case ids")
        return self

    @property
    def stale_case_count(self) -> int:
        return sum(1 for c in self.cases if c.status == "stale_case")
