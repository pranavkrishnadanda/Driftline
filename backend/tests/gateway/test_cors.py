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


def _preflight(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,last-event-id",
    }


def test_default_cors_origins_is_the_local_frontend():
    assert Settings(_env_file=None).cors_origins == ["http://localhost:3000"]


async def test_preflight_from_local_frontend_is_allowed(pg_dsn, redis_url):
    settings = Settings(_env_file=None, database_url=pg_dsn, redis_url=redis_url)
    async with client_for(settings) as c:
        r = await c.options("/healthz", headers=_preflight("http://localhost:3000"))
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "last-event-id" in r.headers["access-control-allow-headers"].lower()


async def test_simple_request_from_local_frontend_gets_cors_header(pg_dsn, redis_url):
    settings = Settings(_env_file=None, database_url=pg_dsn, redis_url=redis_url)
    async with client_for(settings) as c:
        r = await c.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_preflight_from_random_origin_is_rejected(pg_dsn, redis_url):
    settings = Settings(_env_file=None, database_url=pg_dsn, redis_url=redis_url)
    async with client_for(settings) as c:
        r = await c.options("/healthz", headers=_preflight("https://evil.example"))
        g = await c.get("/healthz", headers={"Origin": "https://evil.example"})
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-origin" not in g.headers
