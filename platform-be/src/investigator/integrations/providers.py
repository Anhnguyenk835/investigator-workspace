"""One entry per OAuth app. Adding a source is adding an entry here (and a connector)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

import httpx

from investigator.integrations.errors import OAuthError
from investigator.integrations.models import TokenSet

# Reads the token response; may return a refreshed or first-time token set.
TokenParser = Callable[[dict[str, Any], datetime, TokenSet | None], TokenSet]
AccountFetcher = Callable[[httpx.AsyncClient, TokenSet], Awaitable[dict[str, Any]]]
Revoker = Callable[[httpx.AsyncClient, TokenSet], Awaitable[None]]


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    label: str
    # Investigation sources a connection to this provider unlocks.
    sources: tuple[str, ...]
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    parse_token: TokenParser
    scope_param: str = "scope"
    scope_separator: str = " "
    pkce: bool = False
    authorize_params: Mapping[str, str] = field(default_factory=dict)
    # Where the client id/secret go on the token request, and how the body is encoded.
    client_auth: Literal["body", "basic"] = "body"
    body_format: Literal["form", "json"] = "form"
    fetch_account: AccountFetcher | None = None
    # Best-effort revoke at the provider when the user disconnects. None: no endpoint.
    revoke: Revoker | None = None
    # Provider error codes that mean the grant is gone for good.
    dead_grant_errors: frozenset[str] = frozenset(
        {"invalid_grant", "invalid_refresh_token", "token_revoked", "invalid_auth"}
    )


def _scopes(raw: object) -> list[str]:
    return [s for s in str(raw or "").replace(",", " ").split() if s]


def _expiry(payload: Mapping[str, Any], now: datetime) -> datetime | None:
    seconds = payload.get("expires_in")
    return now + timedelta(seconds=int(seconds)) if seconds else None


def _require_token(payload: Mapping[str, Any]) -> str:
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise OAuthError("token_exchange_failed", "Provider returned no access token.")
    return token


def _standard(
    payload: dict[str, Any], now: datetime, previous: TokenSet | None
) -> TokenSet:
    """RFC 6749 shape (Google, Atlassian). A refresh may omit the refresh token."""
    return TokenSet(
        access_token=_require_token(payload),
        refresh_token=payload.get("refresh_token")
        or (previous.refresh_token if previous else None),
        expires_at=_expiry(payload, now),
        scopes=_scopes(payload.get("scope")) or (previous.scopes if previous else []),
        account=previous.account if previous else {},
        connected_at=previous.connected_at if previous else now,
    )


def _slack(
    payload: dict[str, Any], now: datetime, previous: TokenSet | None
) -> TokenSet:
    """Slack answers 200 with ok=false on failure; the user token is nested on connect."""
    if payload.get("ok") is False:
        raise OAuthError(str(payload.get("error") or "token_exchange_failed"))
    user = payload.get("authed_user") or payload
    account = dict(previous.account) if previous else {}
    team = payload.get("team") or {}
    if team.get("id"):
        account.update(
            team_id=team["id"],
            label=team.get("name") or team["id"],
            slack_user_id=(payload.get("authed_user") or {}).get("id"),
        )
    return TokenSet(
        access_token=_require_token(user),
        refresh_token=user.get("refresh_token")
        or (previous.refresh_token if previous else None),
        expires_at=_expiry(user, now),
        scopes=_scopes(user.get("scope")) or (previous.scopes if previous else []),
        account=account,
        connected_at=previous.connected_at if previous else now,
    )


def _notion(
    payload: dict[str, Any], now: datetime, previous: TokenSet | None
) -> TokenSet:
    """Notion tokens do not expire. Access is the pages the user shared at consent."""
    return TokenSet(
        access_token=_require_token(payload),
        account={
            "workspace_id": payload.get("workspace_id"),
            "label": payload.get("workspace_name") or payload.get("workspace_id"),
        },
        connected_at=now,
    )


async def _google_account(http: httpx.AsyncClient, tokens: TokenSet) -> dict[str, Any]:
    resp = await http.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/profile",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
    )
    resp.raise_for_status()
    email = resp.json().get("emailAddress")
    return {"label": email, "email": email}


async def _atlassian_account(
    http: httpx.AsyncClient, tokens: TokenSet
) -> dict[str, Any]:
    """Jira and Confluence calls address a cloud site by id, so keep the user's sites."""
    resp = await http.get(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
    )
    resp.raise_for_status()
    sites = [
        {"id": s["id"], "url": s.get("url"), "name": s.get("name")}
        for s in resp.json()
        if isinstance(s, dict) and s.get("id")
    ]
    names = ", ".join(s["name"] or s["url"] or s["id"] for s in sites)
    email = None
    me = await http.get(
        "https://api.atlassian.com/me",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
    )
    if me.status_code == 200:
        email = me.json().get("email")
    label = " · ".join(p for p in (email, names) if p) or None
    return {"sites": sites, "label": label, "email": email}


async def _revoke_google(http: httpx.AsyncClient, tokens: TokenSet) -> None:
    await http.post(
        "https://oauth2.googleapis.com/revoke",
        data={"token": tokens.refresh_token or tokens.access_token},
    )


async def _revoke_slack(http: httpx.AsyncClient, tokens: TokenSet) -> None:
    await http.post(
        "https://slack.com/api/auth.revoke",
        headers={"Authorization": f"Bearer {tokens.access_token}"},
    )


GOOGLE = OAuthProvider(
    id="google",
    label="Google (Gmail)",
    sources=("gmail",),
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=("https://www.googleapis.com/auth/gmail.readonly",),
    parse_token=_standard,
    pkce=True,
    # offline + consent so Google returns a refresh token every time.
    authorize_params={"access_type": "offline", "prompt": "consent"},
    fetch_account=_google_account,
    revoke=_revoke_google,
)

SLACK = OAuthProvider(
    id="slack",
    label="Slack",
    sources=("slack",),
    authorize_url="https://slack.com/oauth/v2/authorize",
    token_url="https://slack.com/api/oauth.v2.access",
    # User scopes: Slack then acts as the person, so private channels stay private.
    scopes=(
        "search:read",
        "channels:history",
        "groups:history",
        "im:history",
        "mpim:history",
        "channels:read",
        "groups:read",
        "users:read",
    ),
    parse_token=_slack,
    scope_param="user_scope",
    scope_separator=",",
    revoke=_revoke_slack,
)

ATLASSIAN = OAuthProvider(
    id="atlassian",
    label="Atlassian (Jira, Confluence)",
    sources=("jira", "confluence"),
    authorize_url="https://auth.atlassian.com/authorize",
    token_url="https://auth.atlassian.com/oauth/token",
    scopes=(
        "offline_access",
        "read:me",
        "read:jira-work",
        "read:jira-user",
        "read:confluence-content.all",
        "read:confluence-space.summary",
        "search:confluence",
    ),
    parse_token=_standard,
    authorize_params={"audience": "api.atlassian.com", "prompt": "consent"},
    body_format="json",
    fetch_account=_atlassian_account,
)

NOTION = OAuthProvider(
    id="notion",
    label="Notion",
    sources=("notion",),
    authorize_url="https://api.notion.com/v1/oauth/authorize",
    token_url="https://api.notion.com/v1/oauth/token",
    scopes=(),  # Notion has no scope list: the user picks pages on the consent screen.
    parse_token=_notion,
    authorize_params={"owner": "user"},
    client_auth="basic",
    body_format="json",
)

PROVIDERS: dict[str, OAuthProvider] = {
    p.id: p for p in (GOOGLE, SLACK, ATLASSIAN, NOTION)
}

SOURCE_PROVIDER: dict[str, str] = {
    source: p.id for p in PROVIDERS.values() for source in p.sources
}
