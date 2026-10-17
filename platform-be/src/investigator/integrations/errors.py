"""Failures of the connect and token flow. Messages never contain tokens or codes."""

from __future__ import annotations


class OAuthError(Exception):
    """`code` is a short machine-readable reason that is safe to show to the user."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class ProviderNotConfiguredError(OAuthError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            "not_configured", f"{provider} is not configured on this server."
        )


class NotConnectedError(OAuthError):
    """The user never connected this provider."""

    def __init__(self, provider: str) -> None:
        super().__init__("not_connected", f"{provider} is not connected.")


class ReauthRequiredError(OAuthError):
    """The grant was revoked or expired and cannot be refreshed; connect again."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            "reauth_required", f"{provider} access expired or was revoked."
        )
