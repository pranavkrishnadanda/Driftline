import asyncio
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from driftline.agents.eventlog import AskEventLog
from driftline.config import Settings
from driftline.gateway.ask import build_ask_router
from driftline.gateway.contract import install_event_schemas
from driftline.streams.bus import StreamBus


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.pg = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
        app.state.redis = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1
        )
        # SSE reads block for up to a heartbeat interval, so they get a client without
        # the 1 s socket timeout used for request/response work, but still a bounded one.
        app.state.redis_stream = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=settings.sse_heartbeat_s + 5,  # never wait forever on a dead Redis
        )
        app.state.bus = StreamBus(app.state.redis)
        app.state.events = AskEventLog(
            app.state.redis_stream,
            maxlen=settings.ask_events_maxlen,
            ttl_s=settings.ask_events_ttl_s,
        )
        app.state.sse_slots = asyncio.Semaphore(settings.sse_max_connections)
        try:
            yield
        finally:
            await app.state.redis_stream.aclose()
            await app.state.redis.aclose()
            await app.state.pg.close()

    app = FastAPI(title="Driftline", lifespan=lifespan)
    app.include_router(build_ask_router())
    install_event_schemas(app)

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
