import asyncpg
import pytest

from driftline.db.migrate import run_migrations


@pytest.fixture(scope="session")
def migrated_dsn(pg_dsn):
    run_migrations(pg_dsn)
    return pg_dsn


@pytest.fixture
async def conn(migrated_dsn):
    c = await asyncpg.connect(migrated_dsn)
    yield c
    await c.close()
