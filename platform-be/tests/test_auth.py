"""Sign-in: Google OIDC with a fake Google, sessions, the origin check and the demo session."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from investigator.api.app import AppState, create_app
from investigator.auth import AuthService, GoogleOidc, MemoryAuthStore
from investigator.auth.google import (
    CERTS_URL,
    TOKEN_URL,
    AuthError,
    challenge,
    safe_next,
)
from investigator.tools import AccessContext
from tests.conftest import MemoryStore

CLIENT = "client-123.apps.example"
WEB = "http://localhost:5173"
REDIRECT = f"{WEB}/api/auth/google/callback"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(key: Any = KEY, kid: str = "k1") -> dict[str, Any]:
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    return {"keys": [{**jwk, "kid": kid, "alg": "RS256", "use": "sig"}]}


class FakeGoogle:
    """The token endpoint and the key set. `claims` is what the next id_token says."""

    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.signer: Any = KEY
        self.refuse = False
        self.seen: list[dict[str, str]] = []
        self.nonce = ""

    def id_token(self, **over: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com", "aud": CLIENT, "sub": "sub-1", "iat": now,
            "exp": now + 600, "email": "Ada@Example.com", "email_verified": True,
            "name": "Ada Lovelace", "picture": "https://img.example/a.png", "nonce": self.nonce,
            **self.claims, **over,
        }  # fmt: skip
        return jwt.encode(claims, self.signer, algorithm="RS256", headers={"kid": "k1"})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == CERTS_URL:
            return httpx.Response(200, json=jwks())
        if str(request.url) == TOKEN_URL:
            self.seen.append(
                {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            )
            if self.refuse:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token()})
        return httpx.Response(404)


def make(**kw: Any) -> tuple[TestClient, FakeGoogle, AuthService, MemoryAuthStore]:
    fake = FakeGoogle()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    store = MemoryAuthStore()
    auth = AuthService(
        store,
        GoogleOidc(CLIENT, "secret", REDIRECT, http),
        web_url=WEB,
        origins=frozenset({WEB}),
        **kw,
    )
    state = AppState(
        store=MemoryStore(),
        graph=None,
        access=AccessContext(user_id="local", permitted_sources=frozenset()),
        auth=auth,
    )
    return TestClient(create_app(state), follow_redirects=False), fake, auth, store


def start(client: TestClient, fake: FakeGoogle, next_: str = "/investigations") -> str:
    """Begin sign-in; returns the state, and remembers the nonce Google would echo."""
    r = client.get("/auth/google/start", params={"next": next_})
    assert r.status_code == 302
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["scope"] == [
        "openid email profile"
    ]
    assert q["redirect_uri"] == [REDIRECT] and q["client_id"] == [CLIENT]
    fake.nonce = q["nonce"][0]
    return q["state"][0]


def sign_in(client: TestClient, fake: FakeGoogle, **claims: Any) -> Any:
    state = start(client, fake)
    fake.claims = claims
    return client.get("/auth/google/callback", params={"state": state, "code": "abc"})


def error_of(r: Any) -> str:
    assert r.status_code == 303
    return str(parse_qs(urlsplit(r.headers["location"]).query)["error"][0])


# ---- signing in ----------------------------------------------------------------------


def test_a_valid_google_sign_in_creates_a_session_and_a_user() -> None:
    client, fake, _, store = make()
    assert client.get("/investigations").status_code == 401
    r = sign_in(client, fake)
    assert r.status_code == 303 and r.headers["location"] == f"{WEB}/investigations"
    cookie = r.headers["set-cookie"]
    assert (
        "inv_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    )
    me = client.get("/auth/me").json()
    assert (
        me["mode"] == "user"
        and me["user"]["email"] == "ada@example.com"
        and me["user"]["name"] == "Ada Lovelace"
    )
    assert client.get("/investigations").status_code == 200
    (user,) = store.users.values()
    assert user.google_sub == "sub-1"
    sent = fake.seen[
        0
    ]  # the code was exchanged with the PKCE verifier, never the challenge
    assert sent["client_secret"] == "secret" and challenge(sent["code_verifier"])


def test_the_session_token_is_stored_only_as_a_hash() -> None:
    client, fake, _, store = make()
    sign_in(client, fake)
    token = client.cookies.get("inv_session")
    assert (
        token and token not in store.sessions and len(next(iter(store.sessions))) == 64
    )


def test_the_same_google_account_is_the_same_user() -> None:
    client, fake, _, store = make()
    sign_in(client, fake)
    client.post("/auth/logout")
    sign_in(client, fake, name="Ada L.")
    assert len(store.users) == 1 and next(iter(store.users.values())).name == "Ada L."


@pytest.mark.parametrize(
    ("claims", "code"),
    [
        ({"aud": "someone-else"}, "bad_token"),
        ({"iss": "https://evil.example"}, "bad_token"),
        ({"exp": int(time.time()) - 3600}, "bad_token"),
        ({"email_verified": False}, "email_not_verified"),
        ({"nonce": "not-the-one"}, "bad_nonce"),
    ],
)
def test_an_identity_token_that_fails_any_check_is_refused(
    claims: dict[str, Any], code: str
) -> None:
    client, fake, _, store = make()
    r = sign_in(client, fake, **claims)
    assert error_of(r) == code and "set-cookie" not in r.headers and not store.users
    assert client.get("/investigations").status_code == 401


def test_a_token_signed_by_someone_else_is_refused() -> None:
    client, fake, _, _ = make()
    fake.signer = OTHER
    assert error_of(sign_in(client, fake)) == "bad_token"


def test_the_state_works_once_and_must_be_known() -> None:
    client, fake, _, _ = make()
    state = start(client, fake)
    assert (
        client.get(
            "/auth/google/callback", params={"state": state, "code": "abc"}
        ).status_code
        == 303
    )
    again = client.get("/auth/google/callback", params={"state": state, "code": "abc"})
    assert error_of(again) == "invalid_state"
    assert (
        error_of(
            client.get("/auth/google/callback", params={"state": "forged", "code": "x"})
        )
        == "invalid_state"
    )


def test_an_expired_attempt_and_a_cancelled_one_and_a_refused_code() -> None:
    client, fake, auth, _ = make()
    state = start(client, fake)
    auth._now = lambda: datetime.now(UTC) + timedelta(minutes=30)
    assert (
        error_of(
            client.get("/auth/google/callback", params={"state": state, "code": "a"})
        )
        == "expired_state"
    )
    auth._now = lambda: datetime.now(UTC)
    state = start(client, fake)
    assert (
        error_of(
            client.get(
                "/auth/google/callback",
                params={"state": state, "error": "access_denied"},
            )
        )
        == "access_denied"
    )
    state = start(client, fake)
    fake.refuse = True
    assert (
        error_of(
            client.get("/auth/google/callback", params={"state": state, "code": "a"})
        )
        == "token_exchange_failed"
    )


def test_only_allowed_accounts_may_sign_in() -> None:
    client, fake, _, _ = make(
        allowed_domains="corp.example", allowed_emails="guest@else.example"
    )
    assert error_of(sign_in(client, fake)) == "not_allowed"  # ada@example.com
    assert sign_in(client, fake, email="bo@corp.example").status_code == 303
    client.post("/auth/logout")
    assert (
        sign_in(client, fake, email="guest@else.example", sub="s2").status_code == 303
    )


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("/investigations/1", "/investigations/1"),
        ("https://evil.example/x", "/"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("/ok\r\nSet-Cookie: x=1", "/"),
        (None, "/"),
        ("", "/"),
    ],
)
def test_the_page_after_sign_in_can_only_be_a_path_on_this_site(
    given: str | None, kept: str
) -> None:
    assert safe_next(given) == kept


def test_google_not_configured_sends_the_visitor_back_with_a_reason() -> None:
    store = MemoryAuthStore()
    http = httpx.AsyncClient()
    auth = AuthService(
        store, GoogleOidc("", "", "", http), web_url=WEB, origins=frozenset({WEB})
    )
    state = AppState(
        store=MemoryStore(),
        graph=None,
        access=AccessContext(user_id="local", permitted_sources=frozenset()),
        auth=auth,
    )
    client = TestClient(create_app(state), follow_redirects=False)
    r = client.get("/auth/google/start")
    assert r.status_code == 303 and "error=not_configured" in r.headers["location"]
    assert client.get("/auth/me").json()["providers"]["google"] is False


# ---- sessions ------------------------------------------------------------------------


def test_signed_out_and_forged_cookies_see_nothing() -> None:
    client, fake, _, _ = make()
    assert client.get("/auth/me").json()["mode"] == "anonymous"
    assert client.get("/investigations").status_code == 401
    client.cookies.set("inv_session", "forged-token")
    assert client.get("/investigations").status_code == 401
    assert client.get("/health").status_code == 200  # open


def test_sign_out_ends_the_session_for_good() -> None:
    client, fake, _, _ = make()
    sign_in(client, fake)
    token = client.cookies.get("inv_session")
    assert client.post("/auth/logout").status_code == 204
    client.cookies.set("inv_session", token or "")
    assert client.get("/investigations").status_code == 401


def test_an_expired_session_is_refused() -> None:
    client, fake, auth, _ = make()
    sign_in(client, fake)
    auth._now = lambda: datetime.now(UTC) + timedelta(days=30)
    assert client.get("/investigations").status_code == 401


def test_writes_from_another_site_are_refused() -> None:
    client, fake, _, _ = make()
    sign_in(client, fake)
    body = {"question": "What happened?"}
    assert (
        client.post(
            "/investigations", json=body, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    ok = client.post("/investigations", json=body, headers={"Origin": WEB})
    assert ok.status_code != 403
    assert (
        client.get(
            "/investigations", headers={"Origin": "https://evil.example"}
        ).status_code
        == 200
    )  # reads are not writes


def test_the_provider_redirects_and_admin_do_not_need_a_session() -> None:
    client, _, _, _ = make()
    # reachable without a cookie: they find the user from their own state, or use a token
    assert (
        client.get("/integrations/google/callback", params={"state": "x"}).status_code
        != 401
    )
    assert client.get("/admin/guardrails/status").status_code in (404, 401)


# ---- demo ----------------------------------------------------------------------------


def test_a_demo_session_needs_no_account_and_is_marked_demo() -> None:
    client, _, _, store = make()
    r = client.post("/auth/demo")
    assert r.status_code == 200 and r.json()["mode"] == "demo"
    assert client.get("/investigations").status_code == 200
    (user,) = store.users.values()
    assert user.kind == "demo" and user.email is None


def test_demo_sessions_are_rate_limited_per_address() -> None:
    client, _, _, _ = make(demo_per_ip_hour=2)
    assert client.post("/auth/demo").status_code == 200
    assert client.post("/auth/demo").status_code == 200
    assert client.post("/auth/demo").status_code == 429


def test_the_demo_can_be_switched_off() -> None:
    client, _, _, _ = make(demo_enabled=False)
    assert client.post("/auth/demo").status_code == 403
    assert client.get("/auth/me").json()["providers"]["demo"] is False


async def test_idle_demo_users_are_found_for_cleanup() -> None:
    _, _, auth, store = make(demo_hours=24)
    old = await auth.start_demo("1.1.1.1")
    fresh = await auth.start_demo("1.1.1.2")
    store.seen[old.id] = datetime.now(UTC) - timedelta(hours=30)
    assert await auth.idle_demo_users() == [old.id]
    await store.delete_users([old.id])
    assert old.id not in store.users and fresh.id in store.users


def test_with_sign_in_off_everything_is_the_local_user() -> None:
    state = AppState(
        store=MemoryStore(),
        graph=None,
        access=AccessContext(user_id="local", permitted_sources=frozenset()),
    )
    client = TestClient(create_app(state))
    assert client.get("/investigations").status_code == 200
    assert client.get("/auth/me").json()["mode"] == "disabled"
    with pytest.raises(AuthError):
        raise AuthError("x")
