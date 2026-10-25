from pathlib import Path

pytest_plugins = ["pytester"]

FIXTURE_SOURCE = Path(__file__).with_name("conftest_cassettes.py")

INNER_TEST = """
import pytest


@pytest.mark.vcr
def test_recorded(require_cassette):
    assert False, "inner test body ran"


@pytest.mark.vcr
def test_recorded_passes(require_cassette):
    pass
"""

REASON = "cassette not recorded: gemini credentials/credits required"


def make_project(pytester):
    # Run against the real fixture module, copied in so each inner run is a fresh process.
    pytester.makepyfile(conftest_cassettes=FIXTURE_SOURCE.read_text())
    pytester.makeconftest('pytest_plugins = ["conftest_cassettes"]')
    pytester.makepyfile(test_gemini_adapter=INNER_TEST)


def test_missing_cassette_with_default_record_mode_is_skipped_with_reason(pytester):
    make_project(pytester)
    result = pytester.runpytest_subprocess("-rs")
    result.assert_outcomes(skipped=2)
    result.stdout.fnmatch_lines([f"*{REASON}*"])


def test_missing_cassette_with_explicit_record_mode_none_is_skipped(pytester):
    make_project(pytester)
    result = pytester.runpytest_subprocess("-rs", "--record-mode=none")
    result.assert_outcomes(skipped=2)


def test_existing_cassette_runs_the_test(pytester):
    make_project(pytester)
    cassettes = pytester.path / "cassettes" / "test_gemini_adapter"
    cassettes.mkdir(parents=True)
    (cassettes / "test_recorded_passes.yaml").write_text("interactions: []\nversion: 1\n")
    result = pytester.runpytest_subprocess("-rs", "-k", "test_recorded_passes")
    result.assert_outcomes(passed=1)


def test_missing_cassette_with_recording_enabled_runs_the_test(pytester):
    make_project(pytester)
    result = pytester.runpytest_subprocess(
        "--record-mode=once", "-k", "test_recorded and not passes"
    )
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(["*inner test body ran*"])
