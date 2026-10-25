"""P7 eval metrics: pure functions over hand-built case outcomes (no I/O)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from driftline.eval.metrics import (
    CaseOutcome,
    ScoredCitation,
    VersionWindow,
    aggregate,
    citation_counts,
    citation_precision,
    cost_per_answer,
    faithfulness,
    insufficient_evidence_accuracy,
    is_outdated,
    latency_p95,
    outdated_citation_rate,
)

V1 = UUID("6f1c2d4e-0000-4000-8000-000000000001")
V2 = UUID("6f1c2d4e-0000-4000-8000-000000000002")
T_OLD, T_NEW = datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 4, 15, tzinfo=UTC)
OLD_RULE = "Check ALT every 12 weeks during therapy."
NEW_RULE = "Check ALT monthly during therapy."
DOSAGE = "Take 10 mg daily with or without food."
OLD = VersionWindow(valid_from=T_OLD, valid_to=T_NEW)
NEW = VersionWindow(valid_from=T_NEW)
JUNE_2023 = datetime(2023, 6, 1, tzinfo=UTC)
JUNE_2024 = datetime(2024, 6, 1, tzinfo=UTC)


def cite(window, text, quote=None, version=V1) -> ScoredCitation:
    return ScoredCitation(version_id=version, quote=quote or text, window=window, chunk_text=text)


def outcome(**fields) -> CaseOutcome:
    return CaseOutcome(**({"as_of": JUNE_2023} | fields))


def test_version_window_is_half_open_and_honours_supersession():
    assert OLD.in_force_at(T_OLD) and OLD.in_force_at(JUNE_2023)
    assert not OLD.in_force_at(T_NEW)  # [from, to): the boundary belongs to the new version
    assert NEW.in_force_at(T_NEW) and NEW.in_force_at(JUNE_2024)
    assert not NEW.in_force_at(JUNE_2023)  # not yet in force
    replaced = VersionWindow(valid_from=T_OLD, superseded_from=T_NEW)
    assert replaced.in_force_at(JUNE_2023) and not replaced.in_force_at(JUNE_2024)


def test_citation_counts_only_when_in_force_and_quote_supported():
    assert citation_counts(cite(OLD, OLD_RULE), JUNE_2023)
    assert not citation_counts(cite(NEW, NEW_RULE), JUNE_2023)  # outdated version
    assert not citation_counts(cite(OLD, OLD_RULE, quote="ALT is checked weekly."), JUNE_2023)
    unknown_version = ScoredCitation(version_id=V1, quote=OLD_RULE, window=None, chunk_text=None)
    assert not citation_counts(unknown_version, JUNE_2023)
    # The chunk is not one of the cited version's chunks (or does not exist).
    wrong_chunk = ScoredCitation(version_id=V1, quote=OLD_RULE, window=OLD, chunk_text=None)
    assert not citation_counts(wrong_chunk, JUNE_2023)
    unparsable = ScoredCitation(version_id=None, quote=OLD_RULE, window=None, chunk_text=None)
    assert not citation_counts(unparsable, JUNE_2023)


def test_tie_at_the_version_boundary_goes_to_the_new_version():
    """as_of exactly at the change: the new version is in force, the old one is outdated."""
    at_change = outcome(
        as_of=T_NEW, citations=[cite(OLD, OLD_RULE), cite(NEW, NEW_RULE, version=V2)]
    )
    assert [citation_counts(c, T_NEW) for c in at_change.citations] == [False, True]
    assert [is_outdated(c, T_NEW) for c in at_change.citations] == [True, False]
    assert citation_precision([at_change]) == 0.5
    assert outdated_citation_rate([at_change]) == 0.5


def test_tie_between_versions_with_identical_text_counts_only_the_in_force_one():
    """Unchanged text appears in both versions: the quote is supported in both, but only
    the version in force at as_of counts."""
    both = outcome(as_of=JUNE_2024, citations=[cite(OLD, DOSAGE), cite(NEW, DOSAGE, version=V2)])
    assert citation_precision([both]) == 0.5
    assert outdated_citation_rate([both]) == 0.5


def test_partial_quote_overlap_does_not_count():
    """Half of the quote is in the chunk, half invented: unsupported, so not counted,
    even though the version is in force (and not outdated either)."""
    partial = cite(OLD, OLD_RULE, quote="Check ALT every 12 weeks, and stop at grade 3 injury.")
    case = outcome(citations=[partial, cite(OLD, OLD_RULE)])
    assert citation_precision([case]) == 0.5
    assert outdated_citation_rate([case]) == 0.0
    too_short = cite(OLD, OLD_RULE, quote="ALT")  # below the guardrail's minimum quote length
    assert not citation_counts(too_short, JUNE_2023)


def test_unknown_versions_are_imprecise_but_not_outdated():
    invented = ScoredCitation(version_id=V2, quote=NEW_RULE, window=None, chunk_text=None)
    case = outcome(citations=[invented, cite(OLD, OLD_RULE)])
    assert not is_outdated(invented, JUNE_2023)
    assert citation_precision([case]) == 0.5
    assert outdated_citation_rate([case]) == 0.0


def test_citation_metrics_pool_citations_across_cases_and_skip_uncited_cases():
    one = outcome(citations=[cite(OLD, OLD_RULE)])
    three = outcome(
        as_of=JUNE_2024,
        citations=[cite(NEW, NEW_RULE), cite(OLD, OLD_RULE), cite(OLD, DOSAGE)],
    )
    uncited = outcome(citations=[])
    # 2 of 4 citations count; 2 of 4 are outdated.
    assert citation_precision([one, three, uncited]) == 0.5
    assert outdated_citation_rate([one, three, uncited]) == 0.5
    assert citation_precision([uncited]) is None
    assert outdated_citation_rate([]) is None


def test_faithfulness_from_claim_results_and_judge_sample():
    a = outcome(claims_supported=[True, True, False])
    b = outcome(claims_supported=[True], judged=[False])
    assert faithfulness([a, b]) == 0.75
    assert faithfulness([a, b], judged=True) == 0.0
    assert faithfulness([outcome()]) is None
    assert faithfulness([a], judged=True) is None  # no judge sample taken


def test_insufficient_evidence_accuracy():
    cases = [
        outcome(expects_insufficient=True, answer_status="insufficient_evidence"),  # right
        outcome(expects_insufficient=True, answer_status="answered"),  # answered anyway
        outcome(expects_insufficient=False, answer_status="insufficient_evidence"),  # gave up
        outcome(expects_insufficient=False, answer_status="answered"),  # right
        outcome(expects_insufficient=False, answer_status="refused"),  # not an answer
    ]
    assert insufficient_evidence_accuracy(cases) == pytest.approx(2 / 5)
    assert insufficient_evidence_accuracy([]) is None


def test_latency_p95_is_nearest_rank():
    assert latency_p95([]) is None
    assert latency_p95([120.0]) == 120.0
    assert latency_p95([float(ms) for ms in range(1, 101)]) == 95.0
    assert latency_p95([float(ms) for ms in range(100, 0, -1)]) == 95.0  # order-free
    assert latency_p95([10.0, 20.0, 30.0]) == 30.0  # ceil(0.95 * 3) = 3rd value
    assert latency_p95([5.0] * 19 + [900.0]) == 5.0  # 19th of 20


def test_cost_per_answer_is_the_mean():
    assert cost_per_answer([]) is None
    assert cost_per_answer([0.002, 0.004, 0.0]) == pytest.approx(0.002)


def test_aggregate_names_every_metric_and_drops_undefined_ones():
    trap = outcome(citations=[cite(NEW, NEW_RULE, version=V2)], trap=True, latency_ms=50.0)
    plain = outcome(
        as_of=JUNE_2024,
        citations=[cite(NEW, NEW_RULE, version=V2)],
        claims_supported=[True],
        answer_status="answered",
        latency_ms=150.0,
        cost_usd=0.01,
    )
    metrics = aggregate([trap, plain])
    assert metrics["citation_precision"] == 0.5
    assert metrics["outdated_citation_rate"] == 0.5
    assert metrics["trap_citation_precision"] == 0.0
    assert metrics["trap_outdated_citation_rate"] == 1.0
    assert metrics["faithfulness"] == 1.0
    assert metrics["latency_p95_ms"] == 150.0
    assert metrics["cost_per_answer_usd"] == pytest.approx(0.005)
    assert metrics["scored"] == 2.0 and metrics["citations"] == 2.0
    assert "faithfulness_judge" not in metrics  # undefined metrics are left out
    assert all(isinstance(v, float) for v in metrics.values())
    assert "citation_precision" not in aggregate([outcome()])
