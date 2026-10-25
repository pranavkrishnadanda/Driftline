from contextlib import asynccontextmanager

import httpx

from driftline.config import Settings
from driftline.gateway.app import create_app


@asynccontextmanager
async def client_for(settings: Settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_healthz(pg_dsn, redis_url):
    async with client_for(Settings(_env_file=None, database_url=pg_dsn, redis_url=redis_url)) as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readyz_when_dependencies_are_up(pg_dsn, redis_url):
    async with client_for(Settings(_env_file=None, database_url=pg_dsn, redis_url=redis_url)) as c:
        r = await c.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"postgres": "ok", "redis": "ok"}


async def test_readyz_reports_unreachable_redis(pg_dsn):
    settings = Settings(_env_file=None, database_url=pg_dsn, redis_url="redis://127.0.0.1:1/0")
    async with client_for(settings) as c:
        r = await c.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"postgres": "ok", "redis": "error"}
