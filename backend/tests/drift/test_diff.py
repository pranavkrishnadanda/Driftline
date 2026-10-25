from driftline.drift.diff import DIFF_CAP_BYTES, section_status, section_text_diff
from driftline.ingest.hashing import section_hashes
from driftline.ingest.types import Section


def hashes(*sections: tuple[str, str]) -> dict[str, str]:
    return section_hashes([Section(p, t) for p, t in sections])


def test_unchanged_section():
    old = hashes(("A", "alpha"), ("B", "beta"))
    new = hashes(("A", "alpha"), ("B", "beta two"))
    assert section_status(old, new, "A") == "unchanged"


def test_whitespace_only_edit_is_unchanged():
    old = hashes(("A", "alpha  beta"))
    new = hashes(("A", "alpha\nbeta "))
    assert section_status(old, new, "A") == "unchanged"


def test_changed_section():
    old = hashes(("A", "alpha"), ("B", "beta"))
    new = hashes(("A", "alpha"), ("B", "beta two"))
    assert section_status(old, new, "B") == "changed"


def test_removed_section():
    old = hashes(("A", "alpha"), ("B", "beta"))
    new = hashes(("A", "alpha"))
    assert section_status(old, new, "B") == "removed"


def test_section_missing_from_old_but_present_in_new_is_changed():
    # Unchanged cannot be proven, and text exists to re-verify against.
    assert section_status(hashes(("A", "alpha")), hashes(("B", "beta")), "B") == "changed"


def test_nested_section_path_matches_the_full_path_only():
    old = hashes(
        ("Warnings", "intro"),
        ("Warnings > Hepatotoxicity", "monitor liver"),
        ("Dosage > Hepatotoxicity", "reduce dose"),
    )
    new = hashes(
        ("Warnings", "intro rewritten"),
        ("Warnings > Hepatotoxicity", "monitor liver"),
        ("Dosage > Hepatotoxicity", "stop the drug"),
    )
    assert section_status(old, new, "Warnings > Hepatotoxicity") == "unchanged"
    assert section_status(old, new, "Warnings") == "changed"
    assert section_status(old, new, "Dosage > Hepatotoxicity") == "changed"
    assert section_status(old, new, "Hepatotoxicity") == "removed"
    gone = hashes(("Warnings", "intro"))
    assert section_status(old, gone, "Warnings > Hepatotoxicity") == "removed"


def test_text_diff_is_unified():
    out = section_text_diff("line one\nline two\n", "line one\nline 2\n")
    assert out.startswith("--- before\n+++ after\n")
    assert "-line two\n" in out and "+line 2\n" in out and " line one\n" in out


def test_text_diff_of_identical_text_is_empty():
    assert section_text_diff("same\n", "same\n") == ""


def test_text_diff_handles_missing_trailing_newline():
    out = section_text_diff("a\nb", "a\nc")
    assert "-b\n" in out and "+c\n" in out


def test_text_diff_is_capped_at_4kb():
    old = "\n".join(f"old line {i} ünïcödé" for i in range(2000))
    new = "\n".join(f"new line {i} ünïcödé" for i in range(2000))
    out = section_text_diff(old, new)
    assert DIFF_CAP_BYTES == 4096
    assert len(out.encode("utf-8")) <= DIFF_CAP_BYTES
    assert out.startswith("--- before\n+++ after\n")
    assert out.endswith("\n... diff truncated\n")


def test_small_diff_is_not_truncated():
    assert "truncated" not in section_text_diff("a\n", "b\n")
