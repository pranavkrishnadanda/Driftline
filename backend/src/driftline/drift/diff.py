"""Section-level change classification and a bounded text diff for drift alerts."""

import difflib
from collections.abc import Iterable, Iterator, Mapping
from typing import Literal

SectionStatus = Literal["unchanged", "changed", "removed"]

DIFF_CAP_BYTES = 4096
TRUNCATED = "... diff truncated\n"


def section_status(
    old_hashes: Mapping[str, str], new_hashes: Mapping[str, str], section_path: str
) -> SectionStatus:
    """Compare one cited section between two versions' `section_hashes`.

    `section_path` is matched exactly (nested paths are joined with " > "), so a change
    to a parent or a same-named section elsewhere never leaks into this verdict. A path
    absent from `old_hashes` cannot be proven unchanged, so it is `changed` and the
    caller re-verifies against the new text.
    """
    new = new_hashes.get(section_path)
    if new is None:
        return "removed"
    return "unchanged" if old_hashes.get(section_path) == new else "changed"


def capped_lines(lines: Iterable[str], cap_bytes: int) -> tuple[str, bool]:
    """Join `lines` (each gets a newline) into at most `cap_bytes` UTF-8 bytes. When they
    do not all fit, the text ends with the `TRUNCATED` marker (counted in the cap) and
    the flag is True."""
    out: list[str] = []
    size = 0
    budget = cap_bytes - len(TRUNCATED.encode("utf-8"))
    for line in lines:
        piece = line + "\n"
        n = len(piece.encode("utf-8"))
        if size + n > budget:
            out.append(TRUNCATED)
            return "".join(out), True
        out.append(piece)
        size += n
    return "".join(out), False


def section_text_diff(old_text: str, new_text: str) -> str:
    """Unified diff of `old_text` -> `new_text`, at most `DIFF_CAP_BYTES` UTF-8 bytes."""
    lines = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), "before", "after", lineterm=""
    )
    return capped_lines(lines, DIFF_CAP_BYTES)[0]


def sections_text_diff(
    sections: Iterable[tuple[str, str | None, str | None]], cap_bytes: int
) -> tuple[str, bool]:
    """One unified diff over several sections, given as (path, old text, new text) with
    None for a section absent from that side; each section is a file `a/<path>` ->
    `b/<path>` in the diff. The whole diff is capped at `cap_bytes` (see `capped_lines`).
    """

    def lines() -> Iterator[str]:
        for path, old, new in sections:
            yield from difflib.unified_diff(
                (old or "").splitlines(),
                (new or "").splitlines(),
                f"a/{path}" if old is not None else "/dev/null",
                f"b/{path}" if new is not None else "/dev/null",
                lineterm="",
            )

    return capped_lines(lines(), cap_bytes)
