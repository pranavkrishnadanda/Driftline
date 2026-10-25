"""The drift log: every document version change, newest first, as Markdown and JSON.

`python -m driftline.drift report` writes `drift-log.md` and `drift-latest.json`. The
nightly drift-watch workflow commits them only when they change, so the output is a pure
function of the rows: stable ordering, no row ids (they differ per ingest), and no
wall-clock times. The only dates are the versions' own `valid_from` days.

A change is one version against its predecessor: the sections added, changed and removed
(from `diff_from_prev`), a short text diff of the first few changed sections, and the
drift verdicts recorded for watched answers against the new version.
"""

import json
import re
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

import asyncpg

from driftline.drift.diff import section_text_diff

VERDICTS = ("broken", "changed", "still_valid")
MAX_DIFF_SECTIONS = 3  # short diffs for at most this many changed sections per change
SHORT_DIFF_LINES = 12  # diff lines kept per section
MAX_LISTED_SECTIONS = 10  # section names listed per kind in the Markdown
DIFF_TRUNCATED = "... diff truncated"

Report = dict[str, Any]

_VERSIONS_SQL = """
SELECT t.name AS tenant, s.kind AS source_kind, d.id AS document_id, d.external_id,
       coalesce(d.title, d.external_id) AS title, v.id AS version_id, v.version_no,
       v.version_key, v.valid_from, v.diff_from_prev
FROM doc_versions v
JOIN documents d ON d.id = v.document_id
JOIN sources s ON s.id = d.source_id
JOIN tenants t ON t.id = s.tenant_id
WHERE $1::text IS NULL OR t.name = $1
ORDER BY t.name, title, d.external_id, v.version_no
"""

_VERDICTS_SQL = """
SELECT new_version_id, verdict, count(*) AS n FROM drift_events
WHERE new_version_id = ANY($1::uuid[]) GROUP BY new_version_id, verdict
"""

_SECTION_TEXT_SQL = """
SELECT version_id, section_path, string_agg(text, E'\\n' ORDER BY ord) AS text
FROM chunks WHERE version_id = ANY($1::uuid[]) AND section_path = ANY($2::text[])
GROUP BY version_id, section_path
"""


def _day(value) -> str:
    return value.date().isoformat()


def _version(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "version_no": row["version_no"],
        "version_key": row["version_key"],
        "valid_from": _day(row["valid_from"]),
    }


def _short_diff(old: str, new: str) -> tuple[str, bool]:
    lines = section_text_diff(old, new).splitlines()[2:]  # drop the ---/+++ header
    truncated = len(lines) > SHORT_DIFF_LINES
    if truncated:
        lines = [*lines[:SHORT_DIFF_LINES], DIFF_TRUNCATED]
    return "\n".join(lines), truncated


async def build_report(
    conn: asyncpg.Connection, *, tenant: str | None = None, llm_offline: bool
) -> Report:
    """The report as plain JSON types, for all tenants or the one named `tenant`."""
    rows = await conn.fetch(_VERSIONS_SQL, tenant)
    by_doc: dict[Any, list[asyncpg.Record]] = {}
    for row in rows:
        by_doc.setdefault(row["document_id"], []).append(row)

    pairs = [pair for versions in by_doc.values() for pair in pairwise(versions)]
    counts: dict[Any, dict[str, int]] = {}
    for r in await conn.fetch(_VERDICTS_SQL, [new["version_id"] for _, new in pairs]):
        counts.setdefault(r["new_version_id"], {})[r["verdict"]] = r["n"]

    changes = []
    for prev, new in pairs:
        diff = json.loads(new["diff_from_prev"]) if new["diff_from_prev"] else {}
        sections = {k: list(diff.get(k, [])) for k in ("added", "changed", "removed")}
        verdicts = {v: counts.get(new["version_id"], {}).get(v, 0) for v in VERDICTS}
        changes.append(
            {
                "date": _day(new["valid_from"]),
                "tenant": new["tenant"],
                "document": {
                    "title": new["title"],
                    "external_id": new["external_id"],
                    "source_kind": new["source_kind"],
                },
                "from": _version(prev),
                "to": _version(new),
                "sections": sections,
                "verdicts": verdicts,
                "diffs": await _diffs(conn, prev, new, sections["changed"]),
            }
        )
    changes.sort(key=lambda c: (c["tenant"], c["document"]["title"], c["document"]["external_id"]))
    changes.sort(key=lambda c: (c["date"], c["to"]["version_no"]), reverse=True)

    documents = [
        {
            "tenant": versions[-1]["tenant"],
            "title": versions[-1]["title"],
            "external_id": versions[-1]["external_id"],
            "source_kind": versions[-1]["source_kind"],
            "versions": len(versions),
            "current": _version(versions[-1]),
        }
        for versions in by_doc.values()
    ]
    return {
        "as_of": max((_day(r["valid_from"]) for r in rows), default=None),
        "tenant": tenant,
        "llm": {"offline": llm_offline},
        "totals": {
            "documents": len(documents),
            "versions": len(rows),
            "changes": len(changes),
            "verdicts": {v: sum(c["verdicts"][v] for c in changes) for v in VERDICTS},
        },
        "documents": documents,
        "changes": changes,
    }


async def _diffs(
    conn: asyncpg.Connection,
    prev: asyncpg.Record,
    new: asyncpg.Record,
    changed: Sequence[str],
) -> list[dict[str, Any]]:
    paths = sorted(changed)[:MAX_DIFF_SECTIONS]
    if not paths:
        return []
    texts = {
        (r["version_id"], r["section_path"]): r["text"]
        for r in await conn.fetch(_SECTION_TEXT_SQL, [prev["version_id"], new["version_id"]], paths)
    }
    out = []
    for path in paths:
        diff, truncated = _short_diff(
            texts.get((prev["version_id"], path), ""), texts.get((new["version_id"], path), "")
        )
        out.append({"section": path, "diff": diff, "truncated": truncated})
    return out


def render_json(report: Report) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --- Markdown ------------------------------------------------------------------------

_BACKTICKS = re.compile(r"`+")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _fence(body: str) -> str:
    longest = max((len(m) for m in _BACKTICKS.findall(body)), default=0)
    return "`" * max(3, longest + 1)


def _verdict_line(verdicts: dict[str, int]) -> str:
    return (
        f"changed {verdicts['changed']} · broken {verdicts['broken']} · "
        f"still valid {verdicts['still_valid']}"
    )


def _section_list(paths: Sequence[str]) -> str:
    shown = ", ".join(f"`{p}`" for p in paths[:MAX_LISTED_SECTIONS])
    more = len(paths) - MAX_LISTED_SECTIONS
    return f"{shown} (+{more} more)" if more > 0 else shown


def render_markdown(report: Report) -> str:
    totals = report["totals"]
    out = ["# Drift log", ""]
    out.append(
        "Every document version change, newest first. Generated from the Driftline database."
    )
    out.append("")
    if report["as_of"] is not None:
        out.append(f"- Data as of: {report['as_of']} (the newest version's start date)")
    if report["tenant"] is not None:
        out.append(f"- Tenant: {report['tenant']}")
    out.append(
        f"- Documents: {totals['documents']} · versions: {totals['versions']} · "
        f"version changes: {totals['changes']}"
    )
    out.append(f"- Drift verdicts on watched answers: {_verdict_line(totals['verdicts'])}")
    if report["llm"]["offline"]:
        out.append(
            "- LLM: offline (`DRIFTLINE_LLM_OFFLINE=true`). No paid key is used: claim "
            "checks run on the deterministic extractive judge, not Claude, and supersession "
            "extraction is off."
        )
    else:
        out.append("- LLM: the configured provider judges changed claims.")
    out.append("")

    out += ["## Documents", ""]
    if not report["documents"]:
        out += ["No documents ingested yet.", ""]
    else:
        out.append("| Document | Source | Versions | Current | In force since |")
        out.append("|---|---|---|---|---|")
        for doc in report["documents"]:
            cur = doc["current"]
            key = f" (`{cur['version_key']}`)" if cur["version_key"] else ""
            out.append(
                f"| {_cell(doc['title'])}<br>`{_cell(doc['external_id'])}` | "
                f"{doc['source_kind']} | {doc['versions']} | v{cur['version_no']}{key} | "
                f"{cur['valid_from']} |"
            )
        out.append("")

    out += ["## Changes", ""]
    if not report["changes"]:
        out += ["No version changes recorded yet.", ""]
    for change in report["changes"]:
        doc, old, new = change["document"], change["from"], change["to"]
        out.append(
            f"### {change['date']} · {doc['title']} · v{old['version_no']} → v{new['version_no']}"
        )
        out.append("")
        out.append(
            f"`{doc['external_id']}` ({doc['source_kind']}) · version key "
            f"`{old['version_key']}` → `{new['version_key']}`"
        )
        out.append("")
        sections = change["sections"]
        out.append(
            f"- Sections: {len(sections['added'])} added, {len(sections['changed'])} changed, "
            f"{len(sections['removed'])} removed"
        )
        for kind in ("added", "changed", "removed"):
            if sections[kind]:
                out.append(f"  - {kind.capitalize()}: {_section_list(sections[kind])}")
        out.append(f"- Verdicts: {_verdict_line(change['verdicts'])}")
        out.append("")
        for diff in change["diffs"]:
            fence = _fence(diff["diff"])
            out += [f"#### {diff['section']}", "", f"{fence}diff", diff["diff"], fence, ""]
    return "\n".join(out).rstrip("\n") + "\n"
