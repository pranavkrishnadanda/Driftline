"""Content hashing and section-level diff between consecutive versions."""

import hashlib
from collections.abc import Mapping, Sequence
from typing import TypedDict

from driftline.ingest.types import Section, normalize_text


class SectionDiff(TypedDict):
    added: list[str]
    removed: list[str]
    changed: list[str]
    unchanged: list[str]


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def section_hashes(sections: Sequence[Section]) -> dict[str, str]:
    """`section_path -> sha256(normalised text)`, in document order."""
    return {s.path: _sha256(normalize_text(s.text)) for s in sections}


def content_hash(sections: Sequence[Section]) -> str:
    """Hash of the whole version: ordered section paths plus their normalised text."""
    joined = "\x1e".join(
        f"{normalize_text(s.path)}\x1f{_sha256(normalize_text(s.text))}" for s in sections
    )
    return _sha256(joined)


def diff_sections(prev: Mapping[str, str] | None, new: Mapping[str, str]) -> SectionDiff:
    """Classify every section path of `prev` and `new`. Lists are sorted for stable JSON."""
    old = dict(prev or {})
    return SectionDiff(
        added=sorted(p for p in new if p not in old),
        removed=sorted(p for p in old if p not in new),
        changed=sorted(p for p in new if p in old and old[p] != new[p]),
        unchanged=sorted(p for p in new if p in old and old[p] == new[p]),
    )
