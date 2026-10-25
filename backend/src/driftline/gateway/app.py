from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from driftline.config import Settings


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pg = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
        app.state.redis = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
        )
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.pg.close()

    app = FastAPI(title="Driftline", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        status = {"postgres": "ok", "redis": "ok"}
        try:
            async with app.state.pg.acquire() as conn:
                await conn.fetchval("SELECT 1")
        except Exception:  # noqa: BLE001 - readiness reports any failure
            status["postgres"] = "error"
        try:
            await app.state.redis.ping()
        except Exception:  # noqa: BLE001
            status["redis"] = "error"
        code = 200 if all(v == "ok" for v in status.values()) else 503
        return JSONResponse(status, status_code=code)

    return app
