"""The eval-gate data: a deterministic gate subset of the golden sets, and a small,
reproducible DB snapshot holding only the versions those cases need (with embeddings),
exported from one real database and loaded into another fresh, migrated one."""

import asyncio
import json
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import asyncpg
import pytest
from conftest_db import TEMPLATE_DB, dsn_for_database
from dbseed import VersionSeed, embed_all, seed_history, seed_source

from driftline.config import Settings
from driftline.eval.__main__ import amain
from driftline.eval.snapshot import (
    SCRUBBED_KEY_HASH,
    SnapshotError,
    export_snapshot,
    gate_subset,
    load_snapshot,
    manifest_path,
    snapshot_versions,
)
from driftline.eval.types import GoldenCase

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO / "evals" / "snapshot" / "build.py"


def golden(n: int, *, kind="point_in_time", trap=False, corpus="pharma") -> GoldenCase:
    grounded = kind != "not_in_corpus"
    return GoldenCase(
        id=f"{corpus}-{n:03d}",
        corpus=corpus,
        question=f"Question {n}?",
        as_of=date(2024, 1, 1),
        kind=kind,
        expected_answer="An answer.",
        expected_version_ids=[uuid.UUID(int=n + 1)] if grounded else [],
        expected_quotes=["A quote."] if grounded else [],
        trap=trap,
    )


def mixed_set() -> list[GoldenCase]:
    """60 traps, 100 stable point-in-time and 20 current cases (like the real sets)."""
    return [
        golden(n, trap=n < 60, kind="current" if n >= 160 else "point_in_time") for n in range(180)
    ]


def test_gate_subset_is_deterministic_sized_and_independent_of_input_order():
    cases = mixed_set()
    picked = gate_subset(cases, 40)
    assert len(picked) == 40
    assert picked == gate_subset(cases, 40)
    assert picked == gate_subset(list(reversed(cases)), 40)  # input order does not matter
    assert [c.id for c in picked] == sorted(c.id for c in picked)  # file order kept
    assert {c.id for c in picked} <= {c.id for c in cases}


def test_gate_subset_covers_every_stratum_in_proportion():
    picked = gate_subset(mixed_set(), 40)
    strata = {(k, t): 0 for k, t in [("point_in_time", True), ("point_in_time", False)]}
    strata[("current", False)] = 0
    for c in picked:
        strata[(c.kind, c.trap)] += 1
    # 60/180, 100/180 and 20/180 of 40, by largest remainder.
    assert strata == {
        ("point_in_time", True): 13,
        ("point_in_time", False): 22,
        ("current", False): 5,
    }
    # A stratum too small for its share still gets one case.
    rare = [*mixed_set()[:170], golden(500, kind="not_in_corpus")]
    assert any(c.kind == "not_in_corpus" for c in gate_subset(rare, 40))
    assert len(gate_subset(rare, 40)) == 40
    assert gate_subset(mixed_set()[:10], 40) == sorted(mixed_set()[:10], key=lambda c: c.id)


T = [datetime(2020 + n, 1, 1, tzinfo=UTC) for n in range(5)]


@pytest.fixture
async def history(fresh_conn, embedder_url):
    """A tenant with one five-version document and one unrelated document."""
    tenant, source = await seed_source(fresh_conn, kind="openfda", tenant="eval-golden")
    _, versions, _ = await seed_history(
        fresh_conn,
        source,
        external_id="label-a",
        title="Label A",
        versions=[
            VersionSeed(t, [("Dosage", f"Take {n + 1} mg daily."), ("Warnings", f"W{n}.")])
            for n, t in enumerate(T)
        ],
    )
    _, other, _ = await seed_history(
        fresh_conn,
        source,
        external_id="label-b",
        title="Label B",
        versions=[VersionSeed(T[0], [("Dosage", "Take 5 mg.")])],
    )
    await embed_all(fresh_conn, embedder_url)
    return {"tenant": tenant, "versions": versions, "other": other}


@pytest.fixture
async def second_dsn(pg_dsn, template_dsn):
    """Another fresh, migrated database to load a snapshot into."""
    name = f"s_{uuid.uuid4().hex[:16]}"
    admin = await asyncpg.connect(pg_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE_DB}"')
    finally:
        await admin.close()
    yield dsn_for_database(pg_dsn, name)
    admin = await asyncpg.connect(pg_dsn)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await admin.close()


async def test_snapshot_versions_are_the_expected_ones_and_their_neighbours(history, fresh_conn):
    v = history["versions"]
    # The version before and the one after: what an as-of filter must reject.
    assert set(await snapshot_versions(fresh_conn, [v[2]])) == {v[1], v[2], v[3]}
    assert set(await snapshot_versions(fresh_conn, [v[0], v[4]])) == {v[0], v[1], v[3], v[4]}
    assert await snapshot_versions(fresh_conn, [v[0]]) == sorted([v[0], v[1]])  # sorted
    assert await snapshot_versions(fresh_conn, [uuid.uuid4()]) == []  # unknown: nothing


ROWS = {
    "tenants": "SELECT * FROM tenants ORDER BY id",
    "sources": "SELECT * FROM sources ORDER BY id",
    "documents": "SELECT * FROM documents ORDER BY id",
    "doc_versions": "SELECT * FROM doc_versions ORDER BY id",
    "chunks": "SELECT id, version_id, ord, section_path, text, embedding::text AS embedding, "
    "embed_model, tsv::text AS tsv, tags FROM chunks ORDER BY id",
}


async def test_export_then_load_reproduces_exactly_the_needed_rows(
    history, fresh_conn, second_dsn, tmp_path
):
    v = history["versions"]
    keep = await snapshot_versions(fresh_conn, [v[1]])
    path = tmp_path / "gate.snapshot.gz"
    manifest = await export_snapshot(fresh_conn, keep, path)
    assert manifest["rows"] == {
        "tenants": 1,
        "sources": 1,
        "documents": 1,  # label-b is not needed
        "doc_versions": 3,
        "chunks": 6,
    }
    assert json.loads(manifest_path(path).read_text()) == manifest

    # Byte-for-byte reproducible from the same database.
    first = path.read_bytes()
    await export_snapshot(fresh_conn, keep, path)
    assert path.read_bytes() == first

    target = await asyncpg.connect(second_dsn)
    try:
        assert await load_snapshot(target, path) == manifest["rows"]
        for table, sql in ROWS.items():
            loaded = [dict(r) for r in await target.fetch(sql)]
            if table == "tenants":
                # The API key hash of the source database never leaves it.
                assert [r["api_key_hash"] for r in loaded] == [SCRUBBED_KEY_HASH]
                loaded = [r | {"api_key_hash": None} for r in loaded]
            expected = [dict(r) for r in await fresh_conn.fetch(sql)]
            if table == "tenants":
                expected = [r | {"api_key_hash": None} for r in expected]
            elif table == "documents":
                expected = [r for r in expected if r["external_id"] == "label-a"]
            elif table == "doc_versions":
                expected = [r for r in expected if r["id"] in set(keep)]
            elif table == "chunks":
                expected = [r for r in expected if r["version_id"] in set(keep)]
            assert loaded == expected, table
        assert await target.fetchval("SELECT count(*) FROM chunks WHERE embedding IS NULL") == 0
    finally:
        await target.close()


async def test_load_refuses_a_tampered_file_and_a_database_that_is_not_empty(
    history, fresh_conn, second_dsn, tmp_path
):
    path = tmp_path / "gate.snapshot.gz"
    await export_snapshot(fresh_conn, [history["versions"][0]], path)
    with pytest.raises(SnapshotError, match="not empty"):
        await load_snapshot(fresh_conn, path)  # the source database still has its rows

    target = await asyncpg.connect(second_dsn)
    try:
        tampered = tmp_path / "tampered.snapshot.gz"
        tampered.write_bytes(path.read_bytes()[:-8] + b"\0" * 8)
        manifest_path(tampered).write_text(manifest_path(path).read_text())
        with pytest.raises(SnapshotError, match="sha256"):
            await load_snapshot(target, tampered)
        with pytest.raises(SnapshotError, match="manifest"):
            await load_snapshot(target, tmp_path / "missing.snapshot.gz")
        assert await target.fetchval("SELECT count(*) FROM tenants") == 0  # nothing loaded
    finally:
        await target.close()


async def test_build_script_writes_gate_cases_and_snapshot_from_a_real_database(
    history, fresh_dsn, second_dsn, tmp_path
):
    v = history["versions"]
    golden_dir, out = tmp_path / "golden", tmp_path / "out"
    golden_dir.mkdir()
    for corpus, versions in (("pharma", v[:3]), ("k8s", v[3:])):
        lines = []
        for n, version in enumerate(versions):
            case = golden(n, corpus=corpus, trap=n == 0)
            lines.append(case.model_copy(update={"expected_version_ids": [version]}))
        (golden_dir / f"{corpus}.jsonl").write_text(
            "".join(c.model_dump_json() + "\n" for c in lines)
        )
    command = [
        sys.executable,
        str(BUILD),
        "--dsn",
        fresh_dsn,
        "--golden-dir",
        str(golden_dir),
        "--out-dir",
        str(out),
        "--per-corpus",
        "2",
    ]
    proc = await asyncio.create_subprocess_exec(*command, stderr=asyncio.subprocess.PIPE)
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    assert proc.returncode == 0, stderr.decode()
    gate = {c: (out / f"{c}.jsonl").read_text().splitlines() for c in ("pharma", "k8s")}
    assert [len(lines) for lines in gate.values()] == [2, 2]
    manifest = json.loads((out / "gate.manifest.json").read_text())
    assert manifest["cases"] == {"pharma": 2, "k8s": 2}
    picked = {
        uuid.UUID(json.loads(line)["expected_version_ids"][0])
        for lines in gate.values()
        for line in lines
    }
    target = await asyncpg.connect(second_dsn)
    try:
        await load_snapshot(target, out / "gate.snapshot.gz")
        loaded = {r["id"] for r in await target.fetch("SELECT id FROM doc_versions")}
    finally:
        await target.close()
    assert picked <= loaded  # every gate case's expected version is in the snapshot


async def test_cli_load_snapshot_loads_into_the_configured_database(
    history, fresh_conn, second_dsn, tmp_path, capsys
):
    path = tmp_path / "gate.snapshot.gz"
    manifest = await export_snapshot(fresh_conn, history["versions"][:2], path)
    settings = Settings(_env_file=None, database_url=second_dsn)
    assert await amain(["load-snapshot", "--path", str(path)], settings) == 0
    assert "loaded" in capsys.readouterr().out
    target = await asyncpg.connect(second_dsn)
    try:
        assert await target.fetchval("SELECT count(*) FROM chunks") == manifest["rows"]["chunks"]
    finally:
        await target.close()
    # Loading twice is refused loudly, never merged.
    assert await amain(["load-snapshot", "--path", str(path)], settings) == 2
    assert "not empty" in capsys.readouterr().err
