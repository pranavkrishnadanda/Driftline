"""Per-tenant API keys (P6): a tenant is identified by the sha256 of its key.

Only the hash is stored (`tenants.api_key_hash`). Keys are random secrets, not
passwords, so a fast unsalted hash is enough and lets the key be looked up directly.
"""

import hashlib
from dataclasses import dataclass
from uuid import UUID

import asyncpg


class Unauthorized(Exception):
    """No API key, or one that identifies no tenant."""


@dataclass(frozen=True)
class TenantRow:
    id: UUID
    name: str


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


async def resolve_tenant(pool: asyncpg.Pool, bearer: str | None) -> TenantRow:
    """The tenant whose API key is `bearer`; raises Unauthorized otherwise."""
    if not bearer:
        raise Unauthorized("missing API key")
    async with pool.acquire() as conn:
        # LIMIT 2: a hash shared by two tenants identifies neither.
        rows = await conn.fetch(
            "SELECT id, name FROM tenants WHERE api_key_hash = $1 LIMIT 2", hash_api_key(bearer)
        )
    if len(rows) != 1:
        raise Unauthorized("invalid API key")
    return TenantRow(id=rows[0]["id"], name=rows[0]["name"])
