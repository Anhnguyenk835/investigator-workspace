"""Connect, inspect and disconnect the sources a user's investigations read from."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from investigator.api.session import principal_of
from investigator.integrations import (
    IntegrationStatus,
    OAuthError,
    OAuthService,
    ProviderNotConfiguredError,
)
from investigator.settings import get_settings

# No auth yet: every request is this one local user (see AppState.access).

router = APIRouter(prefix="/integrations", tags=["integrations"])


class AuthorizationStart(BaseModel):
    authorization_url: str


def _service(request: Request) -> OAuthService:
    service: OAuthService | None = request.app.state.app.oauth
    if service is None:
        raise HTTPException(503, "Integrations are not available.")
    return service


def _own_connections(request: Request) -> str:
    """Whose connections these are. A demo visitor reads stored data and has none to manage."""
    p = principal_of(request)
    if p.is_demo:
        raise HTTPException(
            403, "The demo uses stored data. Sign in to connect your own sources."
        )
    return p.user_id


def _known(service: OAuthService, provider: str) -> None:
    try:
        service.provider(provider)
    except KeyError:
        raise HTTPException(404, "Unknown integration.") from None


@router.get("", response_model=list[IntegrationStatus])
async def list_integrations(request: Request) -> list[IntegrationStatus]:
    who = principal_of(request)
    found = await _service(request).status(who.user_id)
    if not who.is_demo:
        return found
    # A demo visitor has nothing connected; each source the stored data covers shows as
    # connected to it, and the rest as not available.
    corpus = request.app.state.app.demo
    have = set((await corpus.index()).sources) if corpus else set()
    return [
        i.model_copy(
            update={
                "state": "connected" if have & set(i.sources) else "not_connected",
                "account": "Demo data" if have & set(i.sources) else None,
                "scopes": [],
                "connected_at": None,
            }
        )
        for i in found
    ]


@router.post("/{provider}/authorize", response_model=AuthorizationStart)
async def authorize(provider: str, request: Request) -> AuthorizationStart:
    """POST, not GET: it creates server state. The web app then navigates to the URL."""
    service = _service(request)
    _known(service, provider)
    who = _own_connections(request)
    try:
        return AuthorizationStart(authorization_url=await service.begin(who, provider))
    except ProviderNotConfiguredError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{provider}/callback", include_in_schema=False)
async def callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """The provider redirects the browser here. Always ends in a redirect to the web
    app with a short result code; nothing from the provider is echoed back."""
    service = _service(request)
    _known(service, provider)
    return_url = get_settings().oauth_return_url
    try:
        if not state:
            raise OAuthError("invalid_state")
        await service.complete(provider, state=state, code=code, error=error)
        query = {"connected": provider}
    except OAuthError as exc:
        query = {"provider": provider, "error": exc.code}
    sep = "&" if "?" in return_url else "?"
    return RedirectResponse(f"{return_url}{sep}{urlencode(query)}", status_code=303)


@router.delete("/{provider}", status_code=204)
async def disconnect(provider: str, request: Request) -> None:
    service = _service(request)
    _known(service, provider)
    await service.disconnect(_own_connections(request), provider)
