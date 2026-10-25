"""`python -m driftline.drift report`: the nightly drift log, rendered from real rows.

Versions are written by the real version store (so `diff_from_prev`, section hashes and
chunks are what ingestion produces), drift events are real `drift_events` rows, and the
report must come out byte-identical for identical data: the nightly job commits it only
when it changes.
"""

import json
from datetime import UTC, datetime

from dbseed import seed_source, seed_watched_answer

from driftline.config import Settings
from driftline.drift.__main__ import amain
from driftline.drift.report import build_report, render_json, render_markdown
from driftline.ingest.chunker import chunk_sections
from driftline.ingest.store import upsert_version
from driftline.ingest.types import RawDocument, Section

DOSAGE_V1 = ("Dosage", "Take 10 mg once daily.")
DOSAGE_V2 = ("Dosage", "Take 20 mg once daily.")
LIVER = ("Liver", "Check ALT monthly during therapy.")
WARNINGS = ("Warnings", "Avoid alcohol.")


async def store(conn, source_id, external_id, title, sections, *, valid_from, key):
    raw = RawDocument(
        external_id=external_id,
        title=title,
        version_key=key,
        valid_from=valid_from,
        content="",
        sections=tuple(Section(p, t) for p, t in sections),
        raw_uri=f"file:///{external_id}",
    )
    return await upsert_version(
        conn, source_id=source_id, raw=raw, chunks=chunk_sections(raw.sections)
    )


async def seed_two_documents(conn):
    """Lipitor: v1 (Jan 1) -> v2 (Mar 1, dosage changed) -> v3 (May 1, warnings added).
    Guide: v1 (Feb 1) -> v2 (Apr 1, liver section removed). One watched answer gets a
    `changed` and a `still_valid` verdict on Lipitor v2."""
    tenant, source = await seed_source(conn, kind="openfda", tenant="drift-watch")
    v1 = await store(
        conn, source, "lipitor", "Lipitor label", [DOSAGE_V1, LIVER],
        valid_from=datetime(2024, 1, 1, tzinfo=UTC), key="1",
    )  # fmt: skip
    g1 = await store(
        conn, source, "guide", "Deprecation guide", [("Intro", "APIs move."), LIVER],
        valid_from=datetime(2024, 2, 1, tzinfo=UTC), key="release-1.35",
    )  # fmt: skip
    v2 = await store(
        conn, source, "lipitor", "Lipitor label", [DOSAGE_V2, LIVER],
        valid_from=datetime(2024, 3, 1, tzinfo=UTC), key="2",
    )  # fmt: skip
    g2 = await store(
        conn, source, "guide", "Deprecation guide", [("Intro", "APIs move.")],
        valid_from=datetime(2024, 4, 1, tzinfo=UTC), key="release-1.36",
    )  # fmt: skip
    await store(
        conn, source, "lipitor", "Lipitor label", [DOSAGE_V2, LIVER, WARNINGS],
        valid_from=datetime(2024, 5, 1, tzinfo=UTC), key="3",
    )  # fmt: skip
    chunks = await conn.fetch(
        "SELECT id FROM chunks WHERE version_id = $1 ORDER BY ord", v1.version_id
    )
    answer = await seed_watched_answer(
        conn,
        tenant,
        v1.version_id,
        [chunks[0]["id"], chunks[1]["id"]],
        [("Take 10 mg.", "Take 10 mg once daily."), ("Check ALT.", "Check ALT monthly")],
    )
    for claim_idx, verdict in ((0, "changed"), (1, "still_valid")):
        await conn.execute(
            "INSERT INTO drift_events (answer_id, tenant_id, claim_idx, old_version_id, "
            "new_version_id, verdict, detail) VALUES ($1, $2, $3, $4, $5, $6, '{}')",
            answer,
            tenant,
            claim_idx,
            v1.version_id,
            v2.version_id,
            verdict,
        )
    return {"v2": v2, "g1": g1, "g2": g2}


async def test_report_lists_version_changes_newest_first_with_verdicts_and_diffs(fresh_conn):
    await seed_two_documents(fresh_conn)

    report = await build_report(fresh_conn, llm_offline=True)

    changes = report["changes"]
    assert [(c["document"]["external_id"], c["from"]["version_no"], c["to"]["version_no"])
            for c in changes] == [("lipitor", 2, 3), ("guide", 1, 2), ("lipitor", 1, 2)]  # fmt: skip
    assert [c["date"] for c in changes] == ["2024-05-01", "2024-04-01", "2024-03-01"]
    lipitor_v2 = changes[2]
    assert lipitor_v2["sections"] == {"added": [], "changed": ["Dosage"], "removed": []}
    assert lipitor_v2["verdicts"] == {"broken": 0, "changed": 1, "still_valid": 1}
    assert lipitor_v2["from"]["version_key"] == "1" and lipitor_v2["to"]["version_key"] == "2"
    [diff] = lipitor_v2["diffs"]
    assert diff["section"] == "Dosage"
    assert "-Take 10 mg once daily." in diff["diff"] and "+Take 20 mg once daily." in diff["diff"]
    assert changes[1]["sections"]["removed"] == ["Liver"]
    assert changes[1]["verdicts"] == {"broken": 0, "changed": 0, "still_valid": 0}
    assert changes[0]["sections"]["added"] == ["Warnings"]
    assert report["totals"] == {
        "documents": 2,
        "versions": 5,
        "changes": 3,
        "verdicts": {"broken": 0, "changed": 1, "still_valid": 1},
    }
    assert report["as_of"] == "2024-05-01"
    assert report["llm"]["offline"] is True


async def test_report_renders_markdown_and_json_deterministically(fresh_conn):
    await seed_two_documents(fresh_conn)

    first = await build_report(fresh_conn, llm_offline=True)
    second = await build_report(fresh_conn, llm_offline=True)

    assert render_json(first) == render_json(second)
    assert render_markdown(first) == render_markdown(second)
    assert json.loads(render_json(first)) == first
    md = render_markdown(first)
    assert md.startswith("# Drift log\n")
    assert "DRIFTLINE_LLM_OFFLINE=true" in md
    # Newest change first, then older ones.
    assert md.index("2024-05-01") < md.index("2024-04-01") < md.index("2024-03-01")
    assert "Lipitor label" in md and "v1 → v2" in md
    assert "changed 1" in md and "still valid 1" in md
    assert "+Take 20 mg once daily." in md
    # No ids and no wall-clock timestamps: only dates that come from the data.
    for row in await fresh_conn.fetch("SELECT id FROM doc_versions"):
        assert str(row["id"]) not in md and str(row["id"]) not in render_json(first)
    today = datetime.now(UTC).date().isoformat()
    assert today not in md


async def test_report_without_offline_mode_says_so(fresh_conn):
    await seed_two_documents(fresh_conn)
    md = render_markdown(await build_report(fresh_conn, llm_offline=False))
    assert "DRIFTLINE_LLM_OFFLINE" not in md


async def test_report_filters_by_tenant(fresh_conn):
    await seed_two_documents(fresh_conn)
    _, other = await seed_source(fresh_conn, tenant="other")
    await store(
        fresh_conn, other, "x", "Other doc", [("A", "a")],
        valid_from=datetime(2025, 1, 1, tzinfo=UTC), key="1",
    )  # fmt: skip
    await store(
        fresh_conn, other, "x", "Other doc", [("A", "b")],
        valid_from=datetime(2025, 2, 1, tzinfo=UTC), key="2",
    )  # fmt: skip

    everything = await build_report(fresh_conn, llm_offline=True)
    scoped = await build_report(fresh_conn, tenant="drift-watch", llm_offline=True)

    assert everything["totals"]["changes"] == 4
    assert scoped["totals"]["changes"] == 3
    assert "Other doc" not in render_markdown(scoped)


async def test_short_diff_is_capped_and_fenced_safely(fresh_conn):
    _, source = await seed_source(fresh_conn, tenant="drift-watch")
    old = "\n".join(f"line {i} ```" for i in range(200))
    new = "\n".join(f"line {i} changed ```" for i in range(200))
    await store(
        fresh_conn, source, "d", "Doc", [("Body", old)],
        valid_from=datetime(2024, 1, 1, tzinfo=UTC), key="1",
    )  # fmt: skip
    await store(
        fresh_conn, source, "d", "Doc", [("Body", new)],
        valid_from=datetime(2024, 2, 1, tzinfo=UTC), key="2",
    )  # fmt: skip

    report = await build_report(fresh_conn, llm_offline=True)

    [diff] = report["changes"][0]["diffs"]
    assert len(diff["diff"].splitlines()) <= 13  # 12 lines plus the truncation marker
    assert diff["truncated"] is True
    md = render_markdown(report)
    assert "````diff" in md  # the fence is longer than any backtick run in the diff


async def test_empty_database_renders_an_empty_report(fresh_conn):
    report = await build_report(fresh_conn, llm_offline=True)

    assert report["changes"] == [] and report["documents"] == []
    assert report["as_of"] is None
    assert report["totals"]["changes"] == 0
    md = render_markdown(report)
    assert md.startswith("# Drift log\n")
    assert "No version changes recorded yet." in md
    assert json.loads(render_json(report)) == report


async def test_cli_report_writes_both_files(fresh_dsn, fresh_conn, redis_url, tmp_path):
    await seed_two_documents(fresh_conn)
    settings = Settings(
        _env_file=None, database_url=fresh_dsn, redis_url=redis_url, llm_offline=True
    )
    out = tmp_path / "reports"

    assert await amain(["report", "--out", str(out)], settings) == 0
    md = (out / "drift-log.md").read_text()
    latest = json.loads((out / "drift-latest.json").read_text())

    assert latest["totals"]["changes"] == 3
    assert md == render_markdown(latest)
    # Running again over the same rows changes nothing on disk.
    before = (out / "drift-latest.json").read_bytes()
    assert await amain(["report", "--out", str(out)], settings) == 0
    assert (out / "drift-latest.json").read_bytes() == before


async def test_cli_report_on_empty_database(fresh_dsn, redis_url, tmp_path):
    settings = Settings(_env_file=None, database_url=fresh_dsn, redis_url=redis_url)
    assert await amain(["report", "--out", str(tmp_path)], settings) == 0
    assert "No version changes recorded yet." in (tmp_path / "drift-log.md").read_text()
    assert json.loads((tmp_path / "drift-latest.json").read_text())["changes"] == []
