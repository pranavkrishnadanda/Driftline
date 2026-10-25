"""The eval CI gate (spec section 12): fail if citation precision drops by more than 2
points or the outdated-citation rate rises by more than 1 point vs. the base run."""

from driftline.eval.__main__ import amain
from driftline.eval.metrics import MAX_OUTDATED_RISE, MAX_PRECISION_DROP, gate
from driftline.eval.types import EvalReport

BASE = {"citation_precision": 0.90, "outdated_citation_rate": 0.05}


def test_thresholds_are_the_spec_points():
    assert (MAX_PRECISION_DROP, MAX_OUTDATED_RISE) == (0.02, 0.01)


def test_gate_passes_within_the_thresholds_including_the_exact_boundary():
    assert gate(BASE, BASE) == []
    assert gate(BASE, {"citation_precision": 0.88, "outdated_citation_rate": 0.06}) == []
    assert gate(BASE, {"citation_precision": 0.99, "outdated_citation_rate": 0.0}) == []


def test_gate_fails_on_a_precision_drop_over_two_points():
    [failure] = gate(BASE, {"citation_precision": 0.879, "outdated_citation_rate": 0.05})
    assert "citation_precision" in failure


def test_gate_fails_on_an_outdated_rise_over_one_point():
    [failure] = gate(BASE, {"citation_precision": 0.90, "outdated_citation_rate": 0.0601})
    assert "outdated_citation_rate" in failure
    both = gate(BASE, {"citation_precision": 0.5, "outdated_citation_rate": 0.5})
    assert len(both) == 2


def test_gate_fails_when_head_lost_a_gated_metric_but_not_when_base_never_had_it():
    [failure] = gate(BASE, {"outdated_citation_rate": 0.05})
    assert "citation_precision" in failure and "missing" in failure
    assert gate({}, {"citation_precision": 0.1}) == []


OFFLINE = "offline extractive LLM"


def report(
    metrics: dict, *, sha="a1b2c3d", system="driftline", corpus="pharma", llm=OFFLINE
) -> EvalReport:
    return EvalReport(system=system, corpus=corpus, git_sha=sha, llm=llm, metrics=metrics, cases=[])


def write(tmp_path, rep: EvalReport):
    path = tmp_path / rep.git_sha / f"{rep.corpus}.{rep.system}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rep.model_dump_json())
    return path


async def test_cli_compare_by_sha_and_by_path(tmp_path, capsys):
    base = write(tmp_path, report(BASE, sha="1111111"))
    good = write(tmp_path, report(BASE | {"citation_precision": 0.89}, sha="2222222"))
    bad = write(tmp_path, report(BASE | {"citation_precision": 0.80}, sha="3333333"))
    args = ["compare", "--reports-dir", str(tmp_path), "--head"]
    assert await amain([*args, str(good), "--base", "1111111"]) == 0
    out = capsys.readouterr().out
    assert "citation_precision" in out and "PASS" in out
    assert await amain([*args, str(bad), "--base", str(base)]) == 1
    assert "FAIL" in capsys.readouterr().out


async def test_cli_compare_fails_loudly_without_a_matching_base(tmp_path, capsys):
    head = write(tmp_path, report(BASE, sha="2222222"))
    args = ["compare", "--reports-dir", str(tmp_path), "--head", str(head), "--base"]
    assert await amain([*args, "9999999"]) == 2  # no report for that sha
    assert "no base report" in capsys.readouterr().err
    other = write(tmp_path, report(BASE, sha="1111111", system="plain_rag"))
    assert await amain([*args, str(other)]) == 2  # a different system is no baseline
    assert "same corpus and system" in capsys.readouterr().err


async def test_cli_compare_refuses_a_base_answered_by_another_llm(tmp_path, capsys):
    """An offline run is no baseline for a Claude run (or the reverse): the numbers
    measure different things, so the gate refuses instead of comparing them."""
    head = write(tmp_path, report(BASE, sha="2222222"))
    claude = write(tmp_path, report(BASE, sha="1111111", llm="answer=anthropic/claude-sonnet-5-5"))
    args = ["compare", "--reports-dir", str(tmp_path), "--head", str(head), "--base"]
    assert await amain([*args, str(claude)]) == 2
    assert "same LLM" in capsys.readouterr().err


async def test_cli_compare_names_the_llm_and_shows_every_gated_metric_with_its_change(
    tmp_path, capsys
):
    base = write(tmp_path, report(BASE, sha="1111111"))
    head = write(tmp_path, report(BASE | {"outdated_citation_rate": 0.0}, sha="2222222"))
    args = ["compare", "--reports-dir", str(tmp_path), "--head", str(head), "--base"]
    assert await amain([*args, str(base)]) == 0
    out = capsys.readouterr().out
    assert OFFLINE in out
    assert "| outdated_citation_rate | 0.0500 | 0.0000 | -5.00 |" in out
    assert "| citation_precision | 0.9000 | 0.9000 | +0.00 |" in out


async def test_cli_compare_fails_loudly_when_the_base_report_file_is_missing(tmp_path, capsys):
    """Review Focus 3: a missing baseline must fail the gate, never skip it."""
    head = write(tmp_path, report(BASE, sha="2222222"))
    missing = tmp_path / "base" / "pharma.driftline.json"
    args = ["compare", "--reports-dir", str(tmp_path), "--head", str(head), "--base"]
    assert await amain([*args, str(missing)]) == 2
    assert "no base report" in capsys.readouterr().err
