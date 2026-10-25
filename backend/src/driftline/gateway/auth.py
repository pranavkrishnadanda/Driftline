"""Who is calling: the tenant behind a bearer API key, or (dev mode) a tenant name.

- A bearer key, when sent, must identify a tenant (else 401) and, when a tenant name is
  also given, must be that tenant's key (else 403).
- With `settings.auth_required` the bearer key is mandatory (401 without it). Otherwise
  (dev mode, the default) a tenant name alone identifies the caller, as before P6.
- Keys are read from the `Authorization` header only, never from the query string,
  which ends up in access logs. SSE clients read streams with `fetch`, so they can send it.
"""

from fastapi import Depends, HTTPException, Query, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from driftline.auth import TenantRow, Unauthorized, resolve_tenant

bearer_scheme = HTTPBearer(auto_error=False, description="Per-tenant API key")
BearerKey = Security(bearer_scheme)

TenantQuery = Query(
    default=None,
    min_length=1,
    description="tenant name; optional with a bearer key, which must then match it",
)


AUTH_RESPONSES: dict[int | str, dict] = {
    401: {"description": "missing or invalid API key"},
    403: {"description": "the API key is not the named tenant's"},
}


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401, detail={"code": "unauthorized"}, headers={"WWW-Authenticate": "Bearer"}
    )


async def caller_tenant(
    request: Request,
    tenant_name: str | None,
    credentials: HTTPAuthorizationCredentials | None,
) -> TenantRow | None:
    """The calling tenant, or None in dev mode when the caller named no tenant."""
    state = request.app.state
    if request.headers.get("authorization") is not None:
        if credentials is None:  # an Authorization header that is not `Bearer <key>`
            raise unauthorized()
        try:
            caller = await resolve_tenant(state.pg, credentials.credentials)
        except Unauthorized:
            raise unauthorized() from None
        if tenant_name is not None and tenant_name != caller.name:
            raise HTTPException(status_code=403, detail={"code": "tenant_mismatch"})
        return caller
    if state.settings.auth_required:
        raise unauthorized()
    if tenant_name is None:
        return None
    async with state.pg.acquire() as conn:
        row = await conn.fetchrow("SELECT id, name FROM tenants WHERE name = $1", tenant_name)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_tenant"})
    return TenantRow(id=row["id"], name=row["name"])


async def require_tenant(
    request: Request,
    tenant: str | None = TenantQuery,
    credentials: HTTPAuthorizationCredentials | None = BearerKey,
) -> TenantRow:
    """FastAPI dependency for tenant-scoped routes: the caller's tenant, or 401."""
    caller = await caller_tenant(request, tenant, credentials)
    if caller is None:
        raise unauthorized()
    return caller


async def optional_tenant(
    request: Request,
    tenant: str | None = TenantQuery,
    credentials: HTTPAuthorizationCredentials | None = BearerKey,
) -> TenantRow | None:
    """Like `require_tenant`, but a dev-mode caller that names no tenant gets None.

    Only for routes addressed by an unguessable id that dev-mode clients already call
    without a tenant (the job status and event URLs returned by `POST /v1/ask`). With a
    key, or with `auth_required`, they are scoped exactly like `require_tenant`.
    """
    return await caller_tenant(request, tenant, credentials)


CallerTenant = Depends(require_tenant)
OptionalCaller = Depends(optional_tenant)
