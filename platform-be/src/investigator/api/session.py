"""The request's principal: who is asking, found from the session cookie.

Installed as an app-wide dependency. With sign-in off (`AppState.auth is None`) every request
is the one local user, as before. Cross-site writes are refused by checking `Origin`.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException, Request

from investigator.auth import COOKIE, LOCAL, Principal, can_read, can_write
from investigator.investigations import Investigation
from investigator.tools import AccessContext

SAFE = {"GET", "HEAD", "OPTIONS"}
# Reachable without a session: health, the sign-in routes, the guardrail admin (its own token)
# and the providers' OAuth redirects, which find the user from the stored state instead.
OPEN = re.compile(
    r"^/(health|docs|openapi\.json|auth/|admin/guardrails|integrations/[a-z]+/callback)"
)


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


async def require_session(request: Request) -> None:
    state = getattr(request.app.state, "app", None)
    auth = getattr(state, "auth", None)
    path = request.url.path
    if (
        auth is not None
        and request.method not in SAFE
        and not path.startswith("/admin/")
    ):
        origin = request.headers.get("origin")
        if origin and _origin(origin) not in auth.origins:
            raise HTTPException(403, "This request came from another site.")
    if auth is None:
        request.state.principal = LOCAL
        return
    found = await auth.principal(request.cookies.get(COOKIE))
    if found is not None:
        request.state.principal = found
        return
    request.state.principal = None
    if not OPEN.match(path):
        raise HTTPException(401, "Sign in to continue.")


def principal_of(request: Request) -> Principal:
    """The signed-in principal. Routes behind `require_session` always have one."""
    found: Principal | None = getattr(request.state, "principal", None)
    if found is None:
        raise HTTPException(401, "Sign in to continue.")
    return found


def access_of(request: Request, base: AccessContext) -> AccessContext:
    """The shared source list, acting as this principal (a demo visitor reads the stored corpus)."""
    p = principal_of(request)
    return base.model_copy(update={"user_id": p.user_id, "demo": p.is_demo})


async def visible_investigation(
    request: Request, investigation_id: UUID, *, write: bool = False
) -> Investigation:
    """The investigation if this principal may use it. Someone else's, or none, is a 404."""
    p = principal_of(request)
    record = await request.app.state.app.store.get(investigation_id)
    if record is None or not can_read(p, record.owner_id):
        raise HTTPException(404, "Investigation not found.")
    if write and not can_write(p, record.owner_id):
        raise HTTPException(
            403,
            "This sample is read-only. Start your own investigation to change things.",
        )
    return record  # type: ignore[no-any-return]
