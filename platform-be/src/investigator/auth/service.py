"""Sign-in, sessions and the demo session, over a store."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from investigator.auth.google import STATE_TTL, AuthError, GoogleOidc, safe_next
from investigator.auth.models import Principal, User, principal_of
from investigator.auth.store import AuthStore, PendingLogin

COOKIE = "inv_session"


def _split(raw: str) -> frozenset[str]:
    return frozenset(
        x.strip().lower() for x in raw.replace(";", ",").split(",") if x.strip()
    )


class AuthService:
    def __init__(
        self,
        store: AuthStore,
        google: GoogleOidc,
        *,
        allowed_domains: str = "",
        allowed_emails: str = "",
        session_days: int = 14,
        demo_enabled: bool = True,
        demo_hours: int = 24,
        demo_per_ip_hour: int = 5,
        cookie_secure: bool = False,
        web_url: str = "",
        origins: frozenset[str] = frozenset(),
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.google = google
        self.domains = _split(allowed_domains)
        self.emails = _split(allowed_emails)
        self.session_ttl = timedelta(days=session_days)
        self.demo_enabled = demo_enabled
        self.demo_ttl = timedelta(hours=demo_hours)
        self.demo_per_ip_hour = demo_per_ip_hour
        self.cookie_secure = cookie_secure
        self.web_url = web_url.rstrip("/")
        self.origins = origins
        self._now = now

    # ---- Google --------------------------------------------------------------------

    async def begin_login(self, next_path: str | None) -> str:
        if not self.google.configured:
            raise AuthError(
                "not_configured", "Google sign-in is not set up on this server."
            )
        state, verifier, nonce = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(64),
            secrets.token_urlsafe(24),
        )
        now = self._now()
        await self.store.save_state(
            PendingLogin(state, verifier, nonce, safe_next(next_path), now + STATE_TTL),
            now,
        )
        return self.google.authorize_url(state, verifier, nonce)

    def allowed(self, email: str, hosted_domain: str | None) -> bool:
        if not self.domains and not self.emails:
            return True
        domain = email.rsplit("@", 1)[-1].lower()
        return (
            email.lower() in self.emails
            or domain in self.domains
            or (hosted_domain or "").lower() in self.domains
        )

    async def complete_login(
        self, *, state: str | None, code: str | None, error: str | None
    ) -> tuple[User, str]:
        """Finish the redirect from Google. Returns the user and where to send them next."""
        pending = await self.store.pop_state(state or "")
        if pending is None:
            raise AuthError("invalid_state", "Unknown or reused sign-in attempt.")
        if pending.expires_at < self._now():
            raise AuthError("expired_state", "The sign-in attempt expired.")
        if error:
            raise AuthError(
                "access_denied" if error == "access_denied" else "provider_error"
            )
        if not code:
            raise AuthError("missing_code", "Google returned no code.")
        identity = await self.google.verify(
            await self.google.exchange(code, pending.verifier), pending.nonce
        )
        if not self.allowed(identity.email, identity.hosted_domain):
            raise AuthError("not_allowed", "This account is not allowed to sign in.")
        user = await self.store.upsert_google(
            identity.sub, identity.email, identity.name, identity.picture
        )
        return user, pending.next

    # ---- sessions ------------------------------------------------------------------

    async def start_session(
        self, user: User, ip: str | None, agent: str | None
    ) -> tuple[str, int]:
        """A new session token and its lifetime in seconds."""
        token = secrets.token_urlsafe(32)
        ttl = self.demo_ttl if user.kind == "demo" else self.session_ttl
        await self.store.create_session(user.id, token, self._now() + ttl, ip, agent)
        return token, int(ttl.total_seconds())

    async def principal(self, token: str | None) -> Principal | None:
        if not token:
            return None
        now = self._now()
        # A session lasts a stated time from the last use (the longer of the two lifetimes
        # is the ceiling; a demo session was created with the shorter one).
        return await self.store.principal(token, now, None)

    async def end(self, token: str | None) -> None:
        if token:
            await self.store.end_session(token)

    # ---- demo ----------------------------------------------------------------------

    async def start_demo(self, ip: str | None) -> User:
        if not self.demo_enabled:
            raise AuthError("demo_disabled", "The demo is not available.")
        if (
            ip
            and await self.store.demos_from(ip, self._now() - timedelta(hours=1))
            >= self.demo_per_ip_hour
        ):
            raise AuthError(
                "too_many_demos",
                "Too many demo sessions from this address. Try again later.",
            )
        return await self.store.create_demo(ip)

    async def idle_demo_users(self) -> list[UUID]:
        return await self.store.idle_demo_ids(self._now() - self.demo_ttl)


_ = principal_of
