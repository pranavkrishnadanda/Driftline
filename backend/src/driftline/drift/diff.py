"""Section-level change classification and a bounded text diff for drift alerts."""

import difflib
from collections.abc import Mapping
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


def section_text_diff(old_text: str, new_text: str) -> str:
    """Unified diff of `old_text` -> `new_text`, at most `DIFF_CAP_BYTES` UTF-8 bytes."""
    lines = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(), "before", "after", lineterm=""
    )
    out: list[str] = []
    size = 0
    budget = DIFF_CAP_BYTES - len(TRUNCATED.encode("utf-8"))
    for line in lines:
        piece = line + "\n"
        n = len(piece.encode("utf-8"))
        if size + n > budget:
            out.append(TRUNCATED)
            break
        out.append(piece)
        size += n
    return "".join(out)
