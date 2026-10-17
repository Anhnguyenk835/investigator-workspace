"""Sign in with Google: OpenID Connect, authorization code with PKCE.

The identity comes from the `id_token`, whose signature is checked against Google's published
keys and whose issuer, audience, expiry, nonce and verified-email claims are all verified.
Nothing is trusted just because it arrived on the redirect.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
STATE_TTL = timedelta(minutes=10)
CERTS_TTL = 3600.0


class AuthError(Exception):
    """A sign-in attempt that must be refused. `code` is safe to put in a URL."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None
    hosted_domain: str | None


def challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )


def safe_next(value: str | None) -> str:
    """Only a path on this site: never a full URL (an open redirect after sign-in)."""
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or len(value) > 300
    ):
        return "/"
    if any(c in value for c in "\r\n"):
        return "/"
    return value


class GoogleOidc:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http: httpx.AsyncClient,
        now: Any = time.time,
    ) -> None:
        self.client_id = client_id
        self._secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = http
        self._now = now
        self._certs: dict[str, Any] = {}
        self._certs_at = -1e9

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self._secret and self.redirect_uri)

    def authorize_url(self, state: str, verifier: str, nonce: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange(self, code: str, verifier: str) -> str:
        """The `id_token` for an authorization code."""
        try:
            r = await self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self._secret,
                    "code_verifier": verifier,
                },
            )
        except httpx.HTTPError as exc:
            raise AuthError(
                "token_exchange_failed", "Google could not be reached."
            ) from exc
        if r.status_code != 200:
            raise AuthError("token_exchange_failed", "Google refused the sign-in code.")
        token = r.json().get("id_token")
        if not isinstance(token, str):
            raise AuthError("no_id_token", "Google returned no identity.")
        return token

    async def _keys(self) -> dict[str, Any]:
        if self._now() - self._certs_at > CERTS_TTL or not self._certs:
            try:
                r = await self._http.get(CERTS_URL)
                r.raise_for_status()
            except httpx.HTTPError as exc:
                raise AuthError(
                    "keys_unavailable", "Google's signing keys could not be fetched."
                ) from exc
            self._certs = {k["kid"]: k for k in r.json().get("keys", [])}
            self._certs_at = self._now()
        return self._certs

    async def verify(self, id_token: str, nonce: str) -> GoogleIdentity:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise AuthError("bad_token", "The identity token is malformed.") from exc
        keys = await self._keys()
        jwk = keys.get(str(header.get("kid")))
        if jwk is None or header.get("alg") != "RS256":
            raise AuthError("bad_token", "The identity token was not signed by Google.")
        try:
            claims = jwt.decode(
                id_token,
                jwt.PyJWK(jwk).key,
                algorithms=["RS256"],
                audience=self.client_id,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                leeway=30,
            )
        except jwt.PyJWTError as exc:
            raise AuthError(
                "bad_token", "The identity token failed verification."
            ) from exc
        if claims.get("iss") not in ISSUERS:
            raise AuthError("bad_token", "The identity token has the wrong issuer.")
        if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
            raise AuthError("bad_nonce", "The sign-in attempt does not match.")
        email = claims.get("email")
        if not isinstance(email, str) or claims.get("email_verified") is not True:
            raise AuthError(
                "email_not_verified", "Google has not verified this email address."
            )
        return GoogleIdentity(
            sub=str(claims["sub"]),
            email=email.lower(),
            name=claims.get("name"),
            picture=claims.get("picture"),
            hosted_domain=claims.get("hd"),
        )


_ = datetime
