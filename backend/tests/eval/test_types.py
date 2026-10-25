"""P7 eval types: golden cases, per-case results and reports. Pure Pydantic, no I/O."""

from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from driftline.eval.types import CaseResult, EvalReport, GoldenCase, golden_from_seed
from driftline.skills.pack import EvalCase

V1 = UUID("6f1c2d4e-0000-4000-8000-000000000001")
V2 = UUID("6f1c2d4e-0000-4000-8000-000000000002")
REPO = Path(__file__).resolve().parents[3]


def golden(**overrides) -> GoldenCase:
    fields = {
        "id": "pharma-001",
        "corpus": "pharma",
        "question": "What did the boxed warning on the Zolpidem label say as of 2021-03-01?",
        "as_of": date(2021, 3, 1),
        "kind": "point_in_time",
        "expected_answer": "Complex sleep behaviors may occur.",
        "expected_version_ids": [V1],
        "expected_quotes": ["Complex sleep behaviors including sleep-walking"],
        "trap": True,
    }
    fields.update(overrides)
    return GoldenCase(**fields)


def result(**overrides) -> CaseResult:
    fields = {
        "case_id": "pharma-001",
        "status": "scored",
        "answer_status": "answered",
        "answer": "Complex sleep behaviors may occur [1].",
        "cited_version_ids": [V1],
        "scores": {"citation_precision": 1.0, "outdated_citation_rate": 0.0},
        "latency_ms": 812.5,
        "cost_usd": 0.0031,
    }
    fields.update(overrides)
    return CaseResult(**fields)


def test_golden_case_round_trips_through_jsonl():
    case = golden()
    line = case.model_dump_json()
    assert "\n" not in line
    assert GoldenCase.model_validate_json(line) == case


def test_golden_case_is_strict_and_frozen():
    with pytest.raises(ValidationError):
        golden(unexpected="x")
    with pytest.raises(ValidationError):
        golden(trap="yes")  # strict: no str -> bool coercion
    with pytest.raises(ValidationError):
        golden().question = "changed"


def test_golden_case_needs_real_version_ids_unless_not_in_corpus():
    with pytest.raises(ValidationError, match="expected_version_ids"):
        golden(expected_version_ids=[])
    with pytest.raises(ValidationError):
        GoldenCase.model_validate_json(golden().model_dump_json().replace(str(V1), "v1"))
    with pytest.raises(ValidationError, match="duplicate"):
        golden(expected_version_ids=[V1, V1])
    absent = golden(
        kind="not_in_corpus",
        trap=False,
        expected_version_ids=[],
        expected_quotes=[],
        expected_answer="insufficient evidence",
    )
    assert absent.expected_version_ids == []


def test_not_in_corpus_case_cannot_expect_versions_or_be_a_trap():
    with pytest.raises(ValidationError, match="not_in_corpus"):
        golden(kind="not_in_corpus", trap=False, expected_quotes=[])
    with pytest.raises(ValidationError, match="trap"):
        golden(kind="not_in_corpus", expected_version_ids=[], expected_quotes=[])


def test_golden_case_rejects_blank_fields_and_unfilled_templates():
    with pytest.raises(ValidationError):
        golden(question="")
    with pytest.raises(ValidationError):
        golden(expected_answer="  ")
    with pytest.raises(ValidationError):
        golden(expected_quotes=[""])
    with pytest.raises(ValidationError, match="placeholder"):
        golden(question="What does the boxed warning on the {drug} label say?")
    with pytest.raises(ValidationError):
        golden(corpus="Pharma Labels")


def test_case_result_round_trips_and_validates():
    r = result()
    assert CaseResult.model_validate_json(r.model_dump_json()) == r
    with pytest.raises(ValidationError):
        result(latency_ms=-1.0)
    with pytest.raises(ValidationError):
        result(cost_usd=-0.01)
    with pytest.raises(ValidationError, match="error"):
        result(status="error", scores={}, error=None)
    with pytest.raises(ValidationError, match="scores"):
        result(status="stale_case")  # a stale case is excluded, never scored
    stale = result(status="stale_case", scores={}, error="version gone after re-ingest")
    assert stale.status == "stale_case"


def test_eval_report_round_trips_and_counts_stale_cases():
    report = EvalReport(
        system="driftline",
        corpus="pharma",
        git_sha="14e550a",
        llm="offline extractive LLM",
        metrics={"citation_precision": 0.93, "outdated_citation_rate": 0.02},
        cases=[
            result(),
            result(case_id="pharma-002", status="stale_case", scores={}, error="gone"),
        ],
    )
    assert EvalReport.model_validate_json(report.model_dump_json()) == report
    assert report.stale_case_count == 1


def test_eval_report_validates_system_sha_and_unique_cases():
    base = {"corpus": "pharma", "llm": "offline extractive LLM", "metrics": {}, "cases": [result()]}
    with pytest.raises(ValidationError):
        EvalReport(system="gpt_only", git_sha="14e550a", **base)
    with pytest.raises(ValidationError):
        EvalReport(system="plain_rag", git_sha="not-a-sha", **base)
    with pytest.raises(ValidationError, match="duplicate"):
        EvalReport(
            system="no_retrieval",
            git_sha="14e550a",
            corpus="pharma",
            llm="offline extractive LLM",
            metrics={},
            cases=[result(), result()],
        )
    with pytest.raises(ValidationError, match="llm"):  # every report says what answered
        EvalReport(system="plain_rag", git_sha="14e550a", **(base | {"llm": " "}))


def seed(**overrides) -> EvalCase:
    fields = {
        "id": "pharma-002",
        "kind": "point_in_time",
        "question": "What did the boxed warning on the {drug} label say as of {date}?",
        "as_of": None,
        "expected_version_ids": [],
        "status": "seed",
        "notes": "Template.",
    }
    fields.update(overrides)
    return EvalCase(**fields)


def test_seed_converts_to_golden_with_real_version_ids():
    case = golden_from_seed(
        seed(),
        corpus="pharma",
        question="What did the boxed warning on the Zolpidem label say as of 2021-03-01?",
        as_of=date(2021, 3, 1),
        expected_answer="Complex sleep behaviors may occur.",
        expected_version_ids=[str(V1), V2],
        expected_quotes=["Complex sleep behaviors including sleep-walking"],
        trap=True,
    )
    assert case.id == "pharma-002" and case.kind == "point_in_time"
    assert case.expected_version_ids == [V1, V2]


def test_seed_conversion_rejects_missing_or_fake_version_ids():
    common = {
        "corpus": "pharma",
        "question": "What did the boxed warning on the Zolpidem label say as of 2021-03-01?",
        "as_of": date(2021, 3, 1),
        "expected_answer": "Complex sleep behaviors may occur.",
        "expected_quotes": ["Complex sleep behaviors"],
        "trap": True,
    }
    with pytest.raises(ValueError, match="expected_version_ids"):
        golden_from_seed(seed(), expected_version_ids=[], **common)
    with pytest.raises(ValueError, match="version id"):
        golden_from_seed(seed(), expected_version_ids=["v1-placeholder"], **common)


def test_seed_conversion_keeps_the_template_question_only_when_filled():
    common = {
        "corpus": "pharma",
        "as_of": date(2021, 3, 1),
        "expected_answer": "x",
        "expected_version_ids": [uuid4()],
        "expected_quotes": ["x"],
        "trap": False,
    }
    with pytest.raises(ValueError, match="placeholder"):
        golden_from_seed(seed(), **common)  # the seed's question is still a template
    filled = golden_from_seed(seed(question="What did the label say in 2021?"), **common)
    assert filled.question == "What did the label say in 2021?"


def test_every_shipped_seed_is_rejected_until_filled_in():
    """The P6 seed files are templates: none that expects a version can become a golden
    case without real version ids (not_in_corpus seeds expect none by design)."""
    seeds = [
        EvalCase.model_validate_json(line)
        for path in sorted(REPO.glob("skills/*/eval.jsonl"))
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    assert seeds, "expected the P6 seed files under skills/*/eval.jsonl"
    for s in (s for s in seeds if s.kind != "not_in_corpus"):
        assert s.status == "seed"
        with pytest.raises(ValueError):
            golden_from_seed(
                s,
                corpus="generic",
                as_of=date(2021, 3, 1),
                expected_answer="x",
                expected_version_ids=list(s.expected_version_ids),
                expected_quotes=["x"],
                trap=False,
            )
