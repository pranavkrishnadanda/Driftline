"""Connector contract shared by every ingestion source."""

import re
import unicodedata
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

# Chunk tag for text that reads like an instruction to a model (spec section 5 injection guard).
INSTRUCTION_LIKE = "instruction_like"
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Section:
    """One addressable part of a document. `path` is stable across versions."""

    path: str
    text: str


@dataclass(frozen=True)
class RawDocument:
    """One version of one document, exactly as a connector fetched it."""

    external_id: str
    title: str
    version_key: str
    valid_from: datetime
    content: str
    sections: tuple[Section, ...]
    raw_uri: str
    source_meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.valid_from.tzinfo is None:
            raise ValueError("valid_from must be timezone-aware")
        paths = [s.path for s in self.sections]
        if len(paths) != len(set(paths)):
            raise ValueError("section paths must be unique within a version")


class SourceFetchError(Exception):
    """A source could not be fetched or parsed. `retryable` drives redelivery."""

    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class Connector(Protocol):
    kind: str

    async def list_external_ids(self) -> list[str]: ...

    def fetch(self, external_id: str, *, since: str | None = None) -> AsyncIterator[RawDocument]:
        """Yield versions newer than the `since` cursor, oldest first."""
        ...


def unique_sections(pairs: Iterable[tuple[str, str]]) -> tuple[Section, ...]:
    """Build sections in order, suffixing repeated paths with ` [2]`, ` [3]`, ..."""
    seen: dict[str, int] = {}
    out: list[Section] = []
    for path, text in pairs:
        n = seen.get(path, 0) + 1
        seen[path] = n
        out.append(Section(path=path if n == 1 else f"{path} [{n}]", text=text))
    return tuple(out)


def render_content(sections: Iterable[Section]) -> str:
    """Plain-text rendering of a version, used for prompts and full-text display."""
    parts = []
    for s in sections:
        parts.append(f"{s.path}\n{s.text}".strip() if s.path else s.text.strip())
    return "\n\n".join(p for p in parts if p)


def normalize_text(text: str) -> str:
    """NFC-normalise and collapse all whitespace, so layout-only edits compare equal."""
    return _WS.sub(" ", unicodedata.normalize("NFC", text)).strip()
