"""Liveness for worker processes that serve no HTTP: a heartbeat file the event loop
touches, and `python -m driftline.health` for Compose healthchecks."""

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any


def touch(path: str) -> None:
    Path(path).touch()  # creates the file, or bumps its mtime to now


def heartbeat_age(path: str, *, now: float | None = None) -> float | None:
    try:
        mtime = os.path.getmtime(path)
    except FileNotFoundError:
        return None
    return (time.time() if now is None else now) - mtime


def is_fresh(path: str, *, max_age_s: float, now: float | None = None) -> bool:
    age = heartbeat_age(path, now=now)
    return age is not None and age <= max_age_s


async def heartbeat_loop(path: str, stop: asyncio.Event, *, interval_s: float = 10.0) -> None:
    """Touch `path` every `interval_s` until `stop` is set. If the event loop is blocked
    or the process dies, the file goes stale and the healthcheck fails."""
    while not stop.is_set():
        touch(path)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass


async def run_with_heartbeat(
    service: Coroutine[Any, Any, None], stop: asyncio.Event, path: str
) -> None:
    """Await `service` while `heartbeat_loop` touches `path`. However the service ends
    (stop requested, returned early, or raised), the heartbeat stops with it, so a dead
    worker never keeps looking healthy."""
    beat = asyncio.create_task(heartbeat_loop(path, stop))
    try:
        await service
    finally:
        stop.set()
        await beat


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m driftline.health")
    parser.add_argument("--path", default="/tmp/driftline-heartbeat")
    parser.add_argument("--max-age", type=float, default=60.0)
    args = parser.parse_args(argv)
    return 0 if is_fresh(args.path, max_age_s=args.max_age) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
