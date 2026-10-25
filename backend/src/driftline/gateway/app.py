import asyncio
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from driftline.agents.eventlog import AskEventLog
from driftline.config import Settings
from driftline.drift.alerts import AlertLog
from driftline.gateway.ask import build_ask_router
from driftline.gateway.contract import install_event_schemas
from driftline.gateway.drift import build_drift_router
from driftline.gateway.review import build_review_router
from driftline.mcp import build_mcp
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
        app.state.alerts = AlertLog(
            app.state.redis_stream,
            maxlen=settings.alert_events_maxlen,
            ttl_s=settings.alert_events_ttl_s,
        )
        # One pool of SSE slots for ask and alert streams alike.
        app.state.sse_slots = asyncio.Semaphore(settings.sse_max_connections)
        try:
            # The mounted MCP app's own lifespan never runs: its session manager runs here.
            async with mcp.session_manager.run():
                yield
        finally:
            await app.state.redis_stream.aclose()
            await app.state.redis.aclose()
            await app.state.pg.close()

    app = FastAPI(title="Driftline", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Last-Event-ID", "Authorization"],
        expose_headers=["Retry-After"],
    )
    app.include_router(build_ask_router())
    app.include_router(build_drift_router())
    app.include_router(build_review_router())
    install_event_schemas(app)
    mcp = build_mcp(app.state)
    app.add_route("/mcp", mcp.streamable_http_app(), include_in_schema=False)

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
