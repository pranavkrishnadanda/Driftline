"""The eval CI gate's data: a gate subset of the golden sets and a small DB snapshot.

The full curation database (the real ingested corpora the golden sets point at) is too
big to commit. The gate instead runs a deterministic, stratified subset of each golden
set against a snapshot holding only the versions those cases need:
- every expected version of a gate case, and
- the version right before and right after it in its document. These are what the
  as-of filter has to reject (for a trap, the next version is the one whose answer
  changed), so the unfiltered baseline still has outdated versions to cite.
Each kept version comes with all its chunks and their embeddings, plus the documents,
sources and tenants above them. Nothing else (no jobs, answers, llm_calls, outbox).

The snapshot is one gzip file of binary COPY sections (exact: embeddings round-trip
bit for bit) and a manifest with its sha256 and row counts. Exporting the same rows
twice gives the same bytes. Tenant API key hashes are replaced by `SCRUBBED_KEY_HASH`.
"""

import gzip
import hashlib
import io
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from uuid import UUID

import asyncpg

from driftline.eval.types import GoldenCase

FORMAT = 1
# Parents first, so foreign keys hold while loading.
TABLES = ("tenants", "sources", "documents", "doc_versions", "chunks")
SCRUBBED_KEY_HASH = "snapshot:no-key"  # no API key hashes to this

_VERSIONS = "SELECT id FROM doc_versions WHERE id = ANY($1::uuid[])"
_DOCS = f"SELECT document_id FROM doc_versions WHERE id IN ({_VERSIONS})"
_SOURCES = f"SELECT source_id FROM documents WHERE id IN ({_DOCS})"
_TENANTS = f"SELECT tenant_id FROM sources WHERE id IN ({_SOURCES})"
_WHERE = {
    "tenants": f"id IN ({_TENANTS})",
    "sources": f"id IN ({_SOURCES})",
    "documents": f"id IN ({_DOCS})",
    "doc_versions": "id = ANY($1::uuid[])",
    "chunks": "version_id = ANY($1::uuid[])",
}
_ORDER = {"chunks": "version_id, ord"}

NEIGHBOURS = """
WITH ordered AS (
  SELECT id,
         lag(id) OVER w AS prev_id,
         lead(id) OVER w AS next_id
  FROM doc_versions
  WINDOW w AS (PARTITION BY document_id ORDER BY valid_from)
)
SELECT DISTINCT unnest(ARRAY[id, prev_id, next_id]) AS id
FROM ordered WHERE id = ANY($1::uuid[])
"""


class SnapshotError(RuntimeError):
    """A snapshot that cannot be loaded: missing, altered, or a target that is not empty."""


def _rank(case: GoldenCase) -> str:
    return hashlib.sha256(case.id.encode()).hexdigest()


def gate_subset(cases: Sequence[GoldenCase], n: int) -> list[GoldenCase]:
    """About `n` cases, the same ones every time, covering every (kind, trap) stratum.

    Each stratum gets one case, then the rest are shared out in proportion to stratum
    size (largest remainder). Within a stratum, cases are taken in sha256(id) order, so
    the choice depends only on the ids, not on file order. Returned sorted by id."""
    if len(cases) <= n:
        return sorted(cases, key=lambda c: c.id)
    strata: dict[tuple[str, bool], list[GoldenCase]] = defaultdict(list)
    for case in sorted(cases, key=_rank):
        strata[(case.kind, case.trap)].append(case)
    keys = sorted(strata)
    take = dict.fromkeys(keys, 0)
    if n >= len(keys):
        take = dict.fromkeys(keys, 1)
    spare = n - sum(take.values())
    total = sum(len(strata[k]) for k in keys)
    shares = {k: spare * len(strata[k]) / total for k in keys}
    for k in keys:
        take[k] += math.floor(shares[k])
    by_remainder = sorted(keys, key=lambda k: (-(shares[k] - math.floor(shares[k])), k))
    for k in by_remainder[: n - sum(take.values())]:
        take[k] += 1
    picked = [c for k in keys for c in strata[k][: take[k]]]
    return sorted(picked, key=lambda c: c.id)


async def snapshot_versions(conn: asyncpg.Connection, expected: Iterable[UUID]) -> list[UUID]:
    """The expected versions that exist, plus each one's previous and next version."""
    rows = await conn.fetch(NEIGHBOURS, list(set(expected)))
    return sorted(r["id"] for r in rows if r["id"] is not None)


async def _columns(conn: asyncpg.Connection, table: str) -> list[str]:
    """The table's stored columns (generated ones, like chunks.tsv, are rebuilt on load)."""
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 AND is_generated = 'NEVER' "
        "ORDER BY ordinal_position",
        table,
    )
    return [r["column_name"] for r in rows]


def _select(table: str, columns: Sequence[str]) -> str:
    def expr(column: str) -> str:
        if table == "tenants" and column == "api_key_hash":
            return f"'{SCRUBBED_KEY_HASH}'::text AS api_key_hash"
        return f'"{column}"'

    order = _ORDER.get(table, "id")
    return (
        f"SELECT {', '.join(expr(c) for c in columns)} FROM {table} "
        f"WHERE {_WHERE[table]} ORDER BY {order}"
    )


def manifest_path(path: Path) -> Path:
    return path.with_name(
        path.name.removesuffix(".gz").removesuffix(".snapshot") + ".manifest.json"
    )


async def export_snapshot(
    conn: asyncpg.Connection, version_ids: Sequence[UUID], path: Path, **extra
) -> dict:
    """Write the snapshot of `version_ids` to `path` and its manifest next to it (see
    `manifest_path`). `extra` is added to the manifest. Returns the manifest."""
    ids = sorted(set(version_ids))
    raw = io.BytesIO()
    rows: dict[str, int] = {}
    columns: dict[str, list[str]] = {}
    for table in TABLES:
        columns[table] = await _columns(conn, table)
        buffer = io.BytesIO()
        status = await conn.copy_from_query(
            _select(table, columns[table]), ids, output=buffer, format="binary"
        )
        rows[table] = int(status.split()[-1])
        data = buffer.getvalue()
        header = {"table": table, "columns": columns[table], "bytes": len(data)}
        raw.write(json.dumps(header).encode() + b"\n")
        raw.write(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0, filename="") as gz:
        gz.write(raw.getvalue())
    path.write_bytes(compressed.getvalue())
    schema = await conn.fetchval("SELECT version_num FROM alembic_version")
    manifest = {
        "format": FORMAT,
        "file": path.name,
        "sha256": hashlib.sha256(compressed.getvalue()).hexdigest(),
        "bytes": len(compressed.getvalue()),
        "schema_version": schema,
        "rows": rows,
        "columns": columns,
        **extra,
    }
    manifest_path(path).write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    return manifest


async def load_snapshot(conn: asyncpg.Connection, path: Path) -> dict[str, int]:
    """Load a snapshot into a fresh, migrated database (every snapshot table empty).
    Verifies the manifest's sha256 first; loads all tables in one transaction."""
    mpath = manifest_path(path)
    if not mpath.is_file() or not path.is_file():
        raise SnapshotError(f"no snapshot or manifest at {path} / {mpath}")
    manifest = json.loads(mpath.read_text())
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != manifest["sha256"]:
        raise SnapshotError(f"sha256 mismatch for {path}: {digest} != {manifest['sha256']}")
    for table in TABLES:
        if await conn.fetchval(f"SELECT EXISTS (SELECT 1 FROM {table})"):
            raise SnapshotError(f"the target database is not empty: {table} has rows")
    raw = io.BytesIO(gzip.decompress(blob))
    loaded: dict[str, int] = {}
    async with conn.transaction():
        for _ in TABLES:
            header = json.loads(raw.readline())
            data = raw.read(header["bytes"])
            status = await conn.copy_to_table(
                header["table"],
                source=io.BytesIO(data),
                columns=header["columns"],
                format="binary",
            )
            loaded[header["table"]] = int(status.split()[-1])
        if loaded != manifest["rows"]:
            raise SnapshotError(f"row counts {loaded} differ from the manifest {manifest['rows']}")
    return loaded
