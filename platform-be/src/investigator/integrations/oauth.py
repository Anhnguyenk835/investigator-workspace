"""Per-user OAuth 2.0 authorization-code flow and token lifecycle."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from investigator.integrations.crypto import TokenCipher
from investigator.integrations.errors import (
    NotConnectedError,
    OAuthError,
    ProviderNotConfiguredError,
    ReauthRequiredError,
)
from investigator.integrations.models import (
    ConnectionState,
    IntegrationStatus,
    PendingAuthorization,
    TokenSet,
)
from investigator.integrations.providers import PROVIDERS, OAuthProvider
from investigator.integrations.store import CredentialStore

STATE_TTL = timedelta(minutes=10)
REFRESH_SKEW = timedelta(seconds=60)


class TokenProvider(Protocol):
    """What a connector needs: a currently valid access token for this user."""

    async def access_token(self, user_id: str, provider: str) -> str: ...

    async def account(self, user_id: str, provider: str) -> dict[str, Any]:
        """Non-secret facts about the connection (e.g. Atlassian cloud sites)."""
        ...


@dataclass(frozen=True)
class ClientCredentials:
    client_id: str
    client_secret: str


def redirect_uri(api_public_url: str, provider: str) -> str:
    return f"{api_public_url.rstrip('/')}/integrations/{provider}/callback"


class OAuthService:
    def __init__(
        self,
        *,
        store: CredentialStore,
        cipher: TokenCipher | None,
        http: httpx.AsyncClient,
        clients: Mapping[str, ClientCredentials],
        api_public_url: str,
        providers: Mapping[str, OAuthProvider] = PROVIDERS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._http = http
        self._clients = clients
        self._api_public_url = api_public_url
        self._providers = providers
        self._now = now
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    # ---- configuration -------------------------------------------------------------

    def provider(self, provider_id: str) -> OAuthProvider:
        """Raises KeyError for an unknown provider."""
        return self._providers[provider_id]

    def is_configured(self, provider_id: str) -> bool:
        creds = self._clients.get(provider_id)
        return bool(self._cipher and creds and creds.client_id and creds.client_secret)

    def _require(self, provider_id: str) -> tuple[OAuthProvider, ClientCredentials]:
        provider = self.provider(provider_id)
        creds = self._clients.get(provider_id)
        if not self._cipher or not creds or not self.is_configured(provider_id):
            raise ProviderNotConfiguredError(provider.label)
        return provider, creds

    # ---- connect -------------------------------------------------------------------

    async def begin(self, user_id: str, provider_id: str) -> str:
        """Create a single-use state and return the provider's consent URL."""
        provider, creds = self._require(provider_id)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64) if provider.pkce else None
        now = self._now()
        await self._store.save_pending(
            PendingAuthorization(
                state=state,
                user_id=user_id,
                provider=provider_id,
                code_verifier=verifier,
                expires_at=now + STATE_TTL,
            ),
            now,
        )
        params: dict[str, str] = {
            "client_id": creds.client_id,
            "redirect_uri": redirect_uri(self._api_public_url, provider_id),
            "response_type": "code",
            "state": state,
            **provider.authorize_params,
        }
        if provider.scopes:
            params[provider.scope_param] = provider.scope_separator.join(
                provider.scopes
            )
        if verifier:
            digest = hashlib.sha256(verifier.encode()).digest()
            params["code_challenge"] = (
                base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            )
            params["code_challenge_method"] = "S256"
        return f"{provider.authorize_url}?{urlencode(params)}"

    async def complete(
        self,
        provider_id: str,
        *,
        state: str,
        code: str | None,
        error: str | None,
    ) -> str:
        """Finish the redirect from the provider; returns the user id it was started for."""
        provider, creds = self._require(provider_id)
        pending = await self._store.pop_pending(state)
        if pending is None or pending.provider != provider_id:
            raise OAuthError("invalid_state", "Unknown or reused authorization state.")
        if pending.expires_at < self._now():
            raise OAuthError("expired_state", "The authorization attempt expired.")
        if error:
            # e.g. access_denied when the user cancels. Pass the code, not free text.
            raise OAuthError(_safe_code(error))
        if not code:
            raise OAuthError("missing_code", "Provider returned no authorization code.")

        body = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri(self._api_public_url, provider_id),
        }
        if pending.code_verifier:
            body["code_verifier"] = pending.code_verifier
        payload = await self._token_request(provider, creds, body)
        tokens = provider.parse_token(payload, self._now(), None)
        if provider.fetch_account:
            try:
                tokens.account.update(await provider.fetch_account(self._http, tokens))
            except (httpx.HTTPError, ValueError, KeyError):
                # The grant is valid; the label is cosmetic. Connect anyway.
                pass
        await self._save(pending.user_id, provider_id, tokens)
        return pending.user_id

    # ---- use -----------------------------------------------------------------------

    async def access_token(self, user_id: str, provider_id: str) -> str:
        provider, creds = self._require(provider_id)
        tokens = await self._load(user_id, provider_id)
        if tokens is None:
            raise NotConnectedError(provider.label)
        if tokens.needs_reauth:
            raise ReauthRequiredError(provider.label)
        if not self._expired(tokens):
            return tokens.access_token

        async with self._locks.setdefault((user_id, provider_id), asyncio.Lock()):
            # Another task may have refreshed while this one waited.
            tokens = await self._load(user_id, provider_id)
            if tokens is None:
                raise NotConnectedError(provider.label)
            if tokens.needs_reauth:
                raise ReauthRequiredError(provider.label)
            if not self._expired(tokens):
                return tokens.access_token
            if not tokens.refresh_token:
                await self._mark_dead(user_id, provider_id, tokens)
                raise ReauthRequiredError(provider.label)
            try:
                payload = await self._token_request(
                    provider,
                    creds,
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": tokens.refresh_token,
                    },
                )
                fresh = provider.parse_token(payload, self._now(), tokens)
            except OAuthError as exc:
                if exc.code in provider.dead_grant_errors:
                    await self._mark_dead(user_id, provider_id, tokens)
                    raise ReauthRequiredError(provider.label) from exc
                raise
            await self._save(user_id, provider_id, fresh)
            return fresh.access_token

    async def disconnect(self, user_id: str, provider_id: str) -> None:
        """Forget the stored grant and revoke it at the provider where one offers that.
        Revoking is best effort: a failure never keeps a token on this server."""
        provider = self.provider(provider_id)
        tokens = await self._load(user_id, provider_id)
        await self._store.delete(user_id, provider_id)
        if (
            tokens
            and provider.revoke
            and tokens.access_token
            and not tokens.needs_reauth
        ):
            try:
                await provider.revoke(self._http, tokens)
            except httpx.HTTPError:
                pass

    async def account(self, user_id: str, provider_id: str) -> dict[str, Any]:
        """Non-secret facts about the connection (e.g. Atlassian cloud sites)."""
        tokens = await self._load(user_id, provider_id)
        return dict(tokens.account) if tokens else {}

    async def status(self, user_id: str) -> list[IntegrationStatus]:
        blobs = await self._store.list(user_id)
        out: list[IntegrationStatus] = []
        for p in self._providers.values():
            tokens = self._decode(blobs.get(p.id))
            state: ConnectionState
            if not self.is_configured(p.id):
                state = "not_configured"
            elif tokens is None:
                state = "not_connected"
            elif tokens.needs_reauth:
                state = "reauth_required"
            else:
                state = "connected"
            out.append(
                IntegrationStatus(
                    provider=p.id,
                    label=p.label,
                    sources=list(p.sources),
                    state=state,
                    account=str(tokens.account["label"])
                    if tokens and tokens.account.get("label")
                    else None,
                    scopes=tokens.scopes if tokens else [],
                    connected_at=tokens.connected_at if tokens else None,
                )
            )
        return out

    # ---- internals -----------------------------------------------------------------

    def _expired(self, tokens: TokenSet) -> bool:
        return (
            tokens.expires_at is not None
            and tokens.expires_at - REFRESH_SKEW <= self._now()
        )

    def _decode(self, blob: bytes | None) -> TokenSet | None:
        if blob is None or self._cipher is None:
            return None
        try:
            return TokenSet.model_validate_json(self._cipher.open(blob))
        except OAuthError:
            return None

    async def _load(self, user_id: str, provider_id: str) -> TokenSet | None:
        return self._decode(await self._store.get(user_id, provider_id))

    async def _save(self, user_id: str, provider_id: str, tokens: TokenSet) -> None:
        assert self._cipher is not None
        await self._store.put(
            user_id, provider_id, self._cipher.seal(tokens.model_dump_json())
        )

    async def _mark_dead(
        self, user_id: str, provider_id: str, tokens: TokenSet
    ) -> None:
        """Keep the record (so the UI can say "reconnect") but drop the dead secrets."""
        await self._save(
            user_id,
            provider_id,
            tokens.model_copy(
                update={"access_token": "", "refresh_token": None, "needs_reauth": True}
            ),
        )

    async def _token_request(
        self, provider: OAuthProvider, creds: ClientCredentials, body: dict[str, str]
    ) -> dict[str, Any]:
        data = dict(body)
        headers = {"Accept": "application/json"}
        if provider.client_auth == "basic":
            pair = f"{creds.client_id}:{creds.client_secret}".encode()
            headers["Authorization"] = f"Basic {base64.b64encode(pair).decode()}"
        else:
            data |= {
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
            }
        try:
            if provider.body_format == "json":
                resp = await self._http.post(
                    provider.token_url, json=data, headers=headers
                )
            else:
                resp = await self._http.post(
                    provider.token_url, data=data, headers=headers
                )
        except httpx.HTTPError as exc:
            # Not the provider's verdict on the grant: keep the credentials.
            raise OAuthError(
                "provider_unreachable", "Provider did not respond."
            ) from exc
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if resp.status_code >= 500:
            raise OAuthError(
                "provider_unreachable", "Provider returned a server error."
            )
        if (
            resp.status_code >= 400
            or payload.get("error")
            or payload.get("ok") is False
        ):
            raise OAuthError(_safe_code(payload.get("error")))
        return payload


def _safe_code(raw: object) -> str:
    """Provider error codes are short snake_case; anything else becomes a generic code."""
    text = str(raw or "")
    return (
        text
        if text and len(text) <= 64 and all(c.isalnum() or c in "_-" for c in text)
        else "token_exchange_failed"
    )
