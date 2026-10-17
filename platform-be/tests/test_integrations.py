"""OAuth connect flow and token lifecycle against a faked provider HTTP layer."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from investigator.api.app import AppState, create_app
from investigator.integrations import (
    ClientCredentials,
    NotConnectedError,
    OAuthError,
    OAuthService,
    ProviderNotConfiguredError,
    ReauthRequiredError,
    TokenCipher,
)
from investigator.integrations.models import PendingAuthorization
from investigator.tools import AccessContext
from tests.conftest import MemoryStore

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)
API = "http://api.test"
Handler = Callable[[httpx.Request], httpx.Response]


class MemoryCredentials:
    def __init__(self) -> None:
        self.blobs: dict[tuple[str, str], bytes] = {}
        self.pending: dict[str, PendingAuthorization] = {}

    async def put(self, user_id: str, provider: str, blob: bytes) -> None:
        self.blobs[(user_id, provider)] = blob

    async def get(self, user_id: str, provider: str) -> bytes | None:
        return self.blobs.get((user_id, provider))

    async def list(self, user_id: str) -> dict[str, bytes]:
        return {p: b for (u, p), b in self.blobs.items() if u == user_id}

    async def delete(self, user_id: str, provider: str) -> None:
        self.blobs.pop((user_id, provider), None)

    async def save_pending(self, pending: PendingAuthorization, now: datetime) -> None:
        self.pending[pending.state] = pending

    async def pop_pending(self, state: str) -> PendingAuthorization | None:
        return self.pending.pop(state, None)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class Rig:
    def __init__(self, handler: Handler, *, configured: bool = True) -> None:
        self.requests: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        self.store = MemoryCredentials()
        self.clock = Clock()
        self.cipher = TokenCipher(Fernet.generate_key().decode())
        creds = (
            ClientCredentials("cid", "secret")
            if configured
            else ClientCredentials("", "")
        )
        self.service = OAuthService(
            store=self.store,
            cipher=self.cipher,
            http=httpx.AsyncClient(transport=httpx.MockTransport(record)),
            clients={p: creds for p in ("google", "slack", "atlassian", "notion")},
            api_public_url=API,
            now=self.clock,
        )

    async def connect(self, provider: str, user: str = "u1") -> None:
        url = await self.service.begin(user, provider)
        state = parse_qs(urlparse(url).query)["state"][0]
        await self.service.complete(provider, state=state, code="the-code", error=None)

    def body(self, index: int = -1) -> dict[str, Any]:
        req = self.requests[index]
        raw = req.content.decode()
        if req.headers["content-type"].startswith("application/json"):
            return json.loads(raw)  # type: ignore[no-any-return]
        return {k: v[0] for k, v in parse_qs(raw).items()}


def google_ok(request: httpx.Request) -> httpx.Response:
    if "gmail.googleapis.com" in str(request.url):
        return httpx.Response(200, json={"emailAddress": "cs@example.test"})
    return httpx.Response(
        200,
        json={
            "access_token": "g-access",
            "refresh_token": "g-refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        },
    )


# ---- authorization URL ----------------------------------------------------------------


async def test_google_url_has_state_pkce_and_offline_access() -> None:
    rig = Rig(google_ok)
    url = urlparse(await rig.service.begin("u1", "google"))
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "accounts.google.com"
    assert q["redirect_uri"] == f"{API}/integrations/google/callback"
    assert q["code_challenge_method"] == "S256" and q["code_challenge"]
    assert q["access_type"] == "offline" and q["state"]
    assert "gmail.readonly" in q["scope"]
    assert "secret" not in url.query  # the client secret never goes to the browser


async def test_each_provider_uses_its_own_scope_and_params() -> None:
    rig = Rig(google_ok)

    async def query(provider: str) -> dict[str, str]:
        url = await rig.service.begin("u1", provider)
        return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}

    slack = await query("slack")
    assert "scope" not in slack and "search:read" in slack["user_scope"]
    assert "," in slack["user_scope"] and "code_challenge" not in slack
    atlassian = await query("atlassian")
    assert atlassian["audience"] == "api.atlassian.com"
    assert "offline_access" in atlassian["scope"]
    notion = await query("notion")
    assert notion["owner"] == "user" and "scope" not in notion


async def test_unconfigured_provider_cannot_start_and_reports_so() -> None:
    rig = Rig(google_ok, configured=False)
    with pytest.raises(ProviderNotConfiguredError):
        await rig.service.begin("u1", "google")
    assert {s.state for s in await rig.service.status("u1")} == {"not_configured"}


async def test_unknown_provider_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        Rig(google_ok).service.provider("myspace")


# ---- completing the redirect ----------------------------------------------------------


async def test_completing_stores_encrypted_tokens_and_the_account_label() -> None:
    rig = Rig(google_ok)
    await rig.connect("google")

    exchange = rig.body(0)
    assert (
        exchange["grant_type"] == "authorization_code"
        and exchange["code"] == "the-code"
    )
    assert exchange["code_verifier"] and exchange["client_secret"] == "secret"
    blob = rig.store.blobs[("u1", "google")]
    assert b"g-access" not in blob and b"g-refresh" not in blob  # sealed at rest

    (google, *_) = await rig.service.status("u1")
    assert (google.state, google.account) == ("connected", "cs@example.test")
    assert google.sources == ["gmail"]
    assert await rig.service.access_token("u1", "google") == "g-access"


async def test_connections_are_per_user() -> None:
    rig = Rig(google_ok)
    await rig.connect("google", "alice")
    with pytest.raises(NotConnectedError):
        await rig.service.access_token("bob", "google")


async def test_state_works_once_and_only_for_its_provider() -> None:
    rig = Rig(google_ok)
    url = await rig.service.begin("u1", "google")
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(OAuthError, match="Unknown"):
        await rig.service.complete("slack", state=state, code="c", error=None)
    # the mismatched attempt consumed it, so it cannot be replayed
    with pytest.raises(OAuthError) as exc:
        await rig.service.complete("google", state=state, code="c", error=None)
    assert exc.value.code == "invalid_state"


async def test_expired_state_is_rejected() -> None:
    rig = Rig(google_ok)
    url = await rig.service.begin("u1", "google")
    state = parse_qs(urlparse(url).query)["state"][0]
    rig.clock.now += timedelta(minutes=11)
    with pytest.raises(OAuthError) as exc:
        await rig.service.complete("google", state=state, code="c", error=None)
    assert exc.value.code == "expired_state"


async def test_user_cancelling_reports_the_provider_code_and_stores_nothing() -> None:
    rig = Rig(google_ok)
    url = await rig.service.begin("u1", "google")
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(OAuthError) as exc:
        await rig.service.complete(
            "google", state=state, code=None, error="access_denied"
        )
    assert exc.value.code == "access_denied" and not rig.store.blobs


async def test_free_text_provider_errors_are_not_passed_through() -> None:
    rig = Rig(google_ok)
    url = await rig.service.begin("u1", "google")
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(OAuthError) as exc:
        await rig.service.complete(
            "google", state=state, code=None, error="<script>alert(1)</script>"
        )
    assert exc.value.code == "token_exchange_failed"


async def test_a_failed_account_lookup_does_not_block_the_connection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "gmail.googleapis.com" in str(request.url):
            return httpx.Response(500)
        return google_ok(request)

    rig = Rig(handler)
    await rig.connect("google")
    assert await rig.service.access_token("u1", "google") == "g-access"


# ---- provider quirks ------------------------------------------------------------------


async def test_slack_takes_the_user_token_and_reads_its_error_from_a_200() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "access_token": "xoxb-bot",
                "team": {"id": "T1", "name": "Acme Team"},
                "authed_user": {
                    "id": "U1",
                    "access_token": "xoxp-user",
                    "scope": "search:read",
                },
            },
        )

    rig = Rig(ok)
    await rig.connect("slack")
    assert await rig.service.access_token("u1", "slack") == "xoxp-user"
    slack = (await rig.service.status("u1"))[1]
    assert slack.account == "Acme Team" and slack.scopes == ["search:read"]

    bad = Rig(
        lambda r: httpx.Response(200, json={"ok": False, "error": "invalid_code"})
    )
    with pytest.raises(OAuthError) as exc:
        await bad.connect("slack")
    assert exc.value.code == "invalid_code"


async def test_notion_uses_basic_auth_json_and_never_expires() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "n-token",
                "workspace_id": "w1",
                "workspace_name": "Ops",
            },
        )

    rig = Rig(ok)
    await rig.connect("notion")
    req = rig.requests[0]
    expected = base64.b64encode(b"cid:secret").decode()
    assert req.headers["authorization"] == f"Basic {expected}"
    assert "client_secret" not in rig.body(0)
    rig.clock.now += timedelta(days=400)
    assert await rig.service.access_token("u1", "notion") == "n-token"
    assert len(rig.requests) == 1  # no refresh attempted


async def test_atlassian_posts_json_and_keeps_the_users_sites() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "accessible-resources" in str(request.url):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "cloud-1",
                        "url": "https://acme.atlassian.net",
                        "name": "acme",
                    }
                ],
            )
        return httpx.Response(
            200, json={"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}
        )

    rig = Rig(handler)
    await rig.connect("atlassian")
    assert rig.body(0)["grant_type"] == "authorization_code"
    assert rig.requests[0].headers["content-type"].startswith("application/json")
    assert (await rig.service.account("u1", "atlassian"))["sites"][0]["id"] == "cloud-1"


# ---- token lifecycle ------------------------------------------------------------------


async def test_expired_token_is_refreshed_and_the_refresh_token_is_kept() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "gmail.googleapis.com" in str(request.url):
            return google_ok(request)
        state["n"] += 1
        if state["n"] == 1:
            return google_ok(request)
        return httpx.Response(200, json={"access_token": "g-new", "expires_in": 3600})

    rig = Rig(handler)
    await rig.connect("google")
    rig.clock.now += timedelta(hours=2)
    assert await rig.service.access_token("u1", "google") == "g-new"
    assert rig.body()["grant_type"] == "refresh_token"
    assert rig.body()["refresh_token"] == "g-refresh"
    # now fresh again: no further request, and the old refresh token survived
    n = len(rig.requests)
    assert await rig.service.access_token("u1", "google") == "g-new"
    assert len(rig.requests) == n
    rig.clock.now += timedelta(hours=2)
    await rig.service.access_token("u1", "google")
    assert rig.body()["refresh_token"] == "g-refresh"


async def test_concurrent_callers_trigger_one_refresh() -> None:
    state = {"refreshes": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "gmail.googleapis.com" in str(request.url):
            return google_ok(request)
        if (
            b"refresh_token&" in request.content
            or b"grant_type=refresh_token" in request.content
        ):
            state["refreshes"] += 1
            return httpx.Response(
                200, json={"access_token": "g-new", "expires_in": 3600}
            )
        return google_ok(request)

    rig = Rig(handler)
    await rig.connect("google")
    rig.clock.now += timedelta(hours=2)
    tokens = await asyncio.gather(
        *(rig.service.access_token("u1", "google") for _ in range(5))
    )
    assert set(tokens) == {"g-new"} and state["refreshes"] == 1


async def test_a_revoked_grant_needs_reauth_and_wipes_the_secrets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if b"grant_type=refresh_token" in request.content:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return google_ok(request)

    rig = Rig(handler)
    await rig.connect("google")
    rig.clock.now += timedelta(hours=2)
    with pytest.raises(ReauthRequiredError):
        await rig.service.access_token("u1", "google")
    google = (await rig.service.status("u1"))[0]
    assert google.state == "reauth_required"
    saved = rig.cipher.open(rig.store.blobs[("u1", "google")])
    assert "g-access" not in saved and "g-refresh" not in saved
    with pytest.raises(ReauthRequiredError):  # no more calls to the provider
        n = len(rig.requests)
        try:
            await rig.service.access_token("u1", "google")
        finally:
            assert len(rig.requests) == n


async def test_provider_outage_keeps_the_connection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if b"grant_type=refresh_token" in request.content:
            return httpx.Response(503)
        return google_ok(request)

    rig = Rig(handler)
    await rig.connect("google")
    rig.clock.now += timedelta(hours=2)
    with pytest.raises(OAuthError) as exc:
        await rig.service.access_token("u1", "google")
    assert exc.value.code == "provider_unreachable"
    assert (await rig.service.status("u1"))[0].state == "connected"


async def test_expired_without_a_refresh_token_needs_reauth() -> None:
    rig = Rig(
        lambda r: (
            httpx.Response(200, json={"access_token": "x", "expires_in": 60})
            if "gmail" not in str(r.url)
            else httpx.Response(200, json={})
        )
    )
    await rig.connect("google")
    rig.clock.now += timedelta(hours=1)
    with pytest.raises(ReauthRequiredError):
        await rig.service.access_token("u1", "google")


async def test_disconnect_forgets_the_grant() -> None:
    rig = Rig(google_ok)
    await rig.connect("google")
    await rig.service.disconnect("u1", "google")
    with pytest.raises(NotConnectedError):
        await rig.service.access_token("u1", "google")
    assert (await rig.service.status("u1"))[0].state == "not_connected"


async def test_a_wrong_key_reads_as_not_connected_instead_of_crashing() -> None:
    rig = Rig(google_ok)
    await rig.connect("google")
    rig.service._cipher = TokenCipher(
        Fernet.generate_key().decode()
    )  # key rotated away
    with pytest.raises(NotConnectedError):
        await rig.service.access_token("u1", "google")


# ---- HTTP API -------------------------------------------------------------------------


def api(rig: Rig) -> TestClient:
    return TestClient(
        create_app(
            AppState(
                store=MemoryStore(),
                graph=None,
                access=AccessContext(user_id="local"),
                oauth=rig.service,
            )
        ),
        follow_redirects=False,
    )


def test_api_lists_authorizes_and_completes_a_connection() -> None:
    rig = Rig(google_ok)
    http = api(rig)

    listing = http.get("/integrations").json()
    assert [i["provider"] for i in listing] == [
        "google",
        "slack",
        "atlassian",
        "notion",
    ]
    assert {i["state"] for i in listing} == {"not_connected"}

    url = http.post("/integrations/google/authorize").json()["authorization_url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    done = http.get(f"/integrations/google/callback?code=abc&state={state}")
    assert done.status_code == 303
    assert "connected=google" in done.headers["location"]
    assert http.get("/integrations").json()[0]["state"] == "connected"

    assert http.delete("/integrations/google").status_code == 204
    assert http.get("/integrations").json()[0]["state"] == "not_connected"


def test_api_callback_failures_redirect_with_a_code_and_never_echo_input() -> None:
    http = api(Rig(google_ok))
    bad = http.get("/integrations/google/callback?code=x&state=forged")
    assert bad.status_code == 303 and "error=invalid_state" in bad.headers["location"]
    missing = http.get("/integrations/google/callback")
    assert "error=invalid_state" in missing.headers["location"]
    cancelled = http.get(
        "/integrations/google/callback?error=access_denied&state=forged"
    )
    assert "forged" not in cancelled.headers["location"]


def test_api_errors_for_unknown_and_unconfigured_providers() -> None:
    http = api(Rig(google_ok, configured=False))
    assert http.post("/integrations/myspace/authorize").status_code == 404
    assert http.post("/integrations/google/authorize").status_code == 409
    assert http.delete("/integrations/myspace").status_code == 404
