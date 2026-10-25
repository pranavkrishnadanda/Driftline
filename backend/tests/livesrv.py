"""Run a real ASGI app on a real socket (uvicorn), for tests that need true streaming.

httpx's ASGITransport buffers the whole response body, so an open-ended SSE stream
never returns through it. A real server on 127.0.0.1 with an ephemeral port does.
"""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn

STARTUP_TIMEOUT_S = 10.0


@asynccontextmanager
async def serve(app) -> AsyncIterator[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(app, log_level="warning", lifespan="on", timeout_graceful_shutdown=1)
    server = uvicorn.Server(config)

    async def run() -> None:
        try:
            await server.serve(sockets=[sock])
        except SystemExit as exc:  # uvicorn exits the process when lifespan startup fails
            raise RuntimeError(f"live server did not start (exit code {exc.code})") from None

    task = asyncio.create_task(run())
    try:
        deadline = asyncio.get_running_loop().time() + STARTUP_TIMEOUT_S
        while not server.started:
            if task.done():
                task.result()  # surface a startup failure
                raise RuntimeError("live server did not start (serve returned early)")
            if asyncio.get_running_loop().time() > deadline:
                raise RuntimeError(f"live server did not start within {STARTUP_TIMEOUT_S} s")
            await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        if not task.done():
            await asyncio.wait_for(task, 10)
        sock.close()
