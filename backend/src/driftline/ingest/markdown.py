"""Heading-aware Markdown splitting shared by the git-docs and upload connectors."""

import re
from dataclasses import dataclass
from typing import Any

import yaml

from driftline.ingest.types import Section, unique_sections

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_ANCHOR = re.compile(r"\s*\{#[^}]*\}\s*$")
_FENCE = re.compile(r"^[ \t]*(```|~~~)")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class MarkdownDoc:
    front_matter: dict[str, Any]
    title: str | None
    sections: tuple[Section, ...]


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    try:
        data = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        data = {}
    return (data if isinstance(data, dict) else {}), text[end + 5 :]


def parse_markdown(text: str) -> MarkdownDoc:
    """Split Markdown into sections keyed by their heading path (`A > B > C`).

    Text before the first heading is the preamble, with path "". Headings inside
    fenced code blocks are ignored, and Hugo `{#anchor}` suffixes are dropped.
    """
    front, body = _split_front_matter(text.replace("\r\n", "\n"))
    body = _COMMENT.sub("", body)
    stack: list[tuple[int, str]] = []
    pairs: list[tuple[str, str]] = []
    current_path, buf = "", []
    first_h1: str | None = None
    in_fence = False
    for line in body.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if m is None:
            buf.append(line)
            continue
        pairs.append((current_path, "\n".join(buf).strip()))
        level, title = len(m.group(1)), _ANCHOR.sub("", m.group(2)).strip()
        if level == 1 and first_h1 is None:
            first_h1 = title
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_path, buf = " > ".join(t for _, t in stack), []
    pairs.append((current_path, "\n".join(buf).strip()))
    pairs = [(p, t) for p, t in pairs if p or t]  # drop an empty preamble
    title = front.get("title") if isinstance(front.get("title"), str) else first_h1
    return MarkdownDoc(front_matter=front, title=title, sections=unique_sections(pairs))
