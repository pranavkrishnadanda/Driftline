from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from driftline.agents.events import (
    ASK_EVENT_ADAPTER,
    ErrorEvent,
    FinalEvent,
    StepEvent,
    TokenEvent,
    is_terminal,
)
from driftline.agents.schemas import AnswerSchema, AskJob, AskRequest, DraftOutput, PlanOutput
from driftline.retrieval.types import Evidence, RetrievalQuery

AS_OF = datetime(2024, 6, 1, tzinfo=UTC)


def evidence(**overrides) -> Evidence:
    values = {
        "chunk_id": uuid4(),
        "version_id": uuid4(),
        "document_id": uuid4(),
        "external_id": "doc",
        "title": "Doc",
        "section_path": "A",
        "text": "alpha",
        "version_no": 1,
        "valid_from": datetime(2024, 1, 1, tzinfo=UTC),
        "valid_to": datetime(2024, 7, 1, tzinfo=UTC),
        "retrieved_as_of": AS_OF,
    }
    return Evidence(**(values | overrides))


def test_evidence_window_is_half_open():
    e = evidence()
    assert e.in_force_at(datetime(2024, 1, 1, tzinfo=UTC))
    assert e.in_force_at(datetime(2024, 6, 30, tzinfo=UTC))
    assert not e.in_force_at(datetime(2024, 7, 1, tzinfo=UTC))
    assert evidence(valid_to=None).in_force_at(datetime(2099, 1, 1, tzinfo=UTC))


def test_evidence_round_trips_through_json():
    e = evidence(tags=["instruction_like"], rerank_score=0.9)
    assert Evidence.model_validate_json(e.model_dump_json()) == e


def test_retrieval_query_requires_aware_as_of():
    with pytest.raises(ValueError, match="timezone-aware"):
        RetrievalQuery(tenant_id=uuid4(), text="q", as_of=datetime(2024, 1, 1))


def test_events_parse_by_type_and_terminal_rules():
    answer = AnswerSchema(status="answered", answer="x", as_of=AS_OF, confidence=1.0)
    parsed = [
        ASK_EVENT_ADAPTER.validate_python(e.model_dump(mode="json"))
        for e in (
            StepEvent(node="plan", status="started"),
            TokenEvent(text="Hel"),
            FinalEvent(answer=answer),
            ErrorEvent(code="llm_unavailable", retryable=False),
        )
    ]
    assert [type(p).__name__ for p in parsed] == [
        "StepEvent",
        "TokenEvent",
        "FinalEvent",
        "ErrorEvent",
    ]
    assert [is_terminal(p) for p in parsed] == [False, False, True, True]
    assert is_terminal(ErrorEvent(code="internal", retryable=True)) is False
    with pytest.raises(ValidationError):
        ASK_EVENT_ADAPTER.validate_python({"type": "nope"})


def test_ask_request_validation():
    ok = AskRequest(question="What changed?", tenant="pharma", source_kinds=["openfda"])
    assert ok.as_of is None
    with pytest.raises(ValidationError):
        AskRequest(question="", tenant="pharma")
    with pytest.raises(ValidationError):
        AskRequest(question="q", tenant="pharma", source_kinds=["wiki"])
    with pytest.raises(ValidationError):
        AskRequest(question="q", tenant="pharma", unknown=1)
    job = AskJob(job_id=uuid4(), tenant_id=uuid4(), question="q", as_of=AS_OF)
    assert AskJob.model_validate_json(job.model_dump_json()) == job


def test_llm_facing_schemas_have_no_optional_fields():
    for model in (PlanOutput, DraftOutput):
        schema = model.model_json_schema()
        assert set(schema["required"]) == set(schema["properties"])
    assert next(iter(DraftOutput.model_json_schema()["properties"])) == "answer"
