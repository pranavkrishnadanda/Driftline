"""Ingest every queued document except its newest version (recorded-demo capture only).

The demo shows drift for real: answers are asked and watched while the older versions
are in force, then the regular ingest worker picks up the newest version and the drift
engine re-checks the watched answers. This runs the regular `worker --drain` with each
connector holding back the newest version it would fetch; the source cursor stops at
the version before, so a later normal ingest fetches exactly the held-back one.

    docker compose ... run --rm -v "$PWD/deploy/demo:/stage:ro" ingest-worker \
      python /stage/stage_ingest.py
"""

import asyncio
import sys
from collections.abc import AsyncIterator
from typing import Any

import httpx

import driftline.ingest.__main__ as cli
from driftline.config import Settings

_default_factory = cli.default_connector_factory


class HoldBackNewest:
    """A connector that yields all but the newest version its source would return."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.kind = inner.kind

    async def list_external_ids(self) -> list[str]:
        return await self._inner.list_external_ids()

    async def fetch(self, external_id: str, *, since: str | None = None) -> AsyncIterator[Any]:
        versions = [raw async for raw in self._inner.fetch(external_id, since=since)]
        print(
            f"{external_id}: ingesting {[v.version_key for v in versions[:-1]]}, "
            f"holding back {[v.version_key for v in versions[-1:]]}",
            flush=True,
        )
        for raw in versions[:-1]:
            yield raw


def hold_back_factory(settings: Settings, http: httpx.AsyncClient):
    build = _default_factory(settings, http)
    return lambda kind, config: HoldBackNewest(build(kind, config))


cli.default_connector_factory = hold_back_factory

if __name__ == "__main__":
    sys.exit(asyncio.run(cli.amain(["worker", "--drain", "--timeout", "1800"], Settings())))
