"""Database fixtures: a migrated shared database, and a fresh database per test.

`fresh_dsn` clones a migrated template database (CREATE DATABASE ... TEMPLATE), so
each ingestion test starts from an empty, fully migrated schema in milliseconds.
"""

import uuid
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import psycopg
import pytest

from driftline.db.migrate import run_migrations

TEMPLATE_DB = "driftline_template"


def dsn_for_database(dsn: str, name: str) -> str:
    return urlunsplit(urlsplit(dsn)._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
def migrated_dsn(pg_dsn):
    run_migrations(pg_dsn)
    return pg_dsn


@pytest.fixture
async def conn(migrated_dsn):
    c = await asyncpg.connect(migrated_dsn)
    yield c
    await c.close()


@pytest.fixture(scope="session")
def template_dsn(pg_dsn):
    with psycopg.connect(pg_dsn, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{TEMPLATE_DB}"')
        admin.execute(f'CREATE DATABASE "{TEMPLATE_DB}"')
    dsn = dsn_for_database(pg_dsn, TEMPLATE_DB)
    run_migrations(dsn)
    return dsn


@pytest.fixture
async def fresh_dsn(pg_dsn, template_dsn):
    name = f"t_{uuid.uuid4().hex[:16]}"
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


@pytest.fixture
async def fresh_conn(fresh_dsn):
    c = await asyncpg.connect(fresh_dsn)
    yield c
    await c.close()


@pytest.fixture
async def fresh_pool(fresh_dsn):
    pool = await asyncpg.create_pool(fresh_dsn, min_size=1, max_size=4)
    yield pool
    await pool.close()
