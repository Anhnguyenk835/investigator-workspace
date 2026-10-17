from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TokenSet(BaseModel):
    """What is stored (encrypted) per user and provider."""

    access_token: str
    refresh_token: str | None = None
    # None means the provider issues tokens that do not expire (Notion, Slack by default).
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)
    # Non-secret facts about the connected account: label, workspace/site ids.
    account: dict[str, Any] = Field(default_factory=dict)
    connected_at: datetime
    # Set when the provider refused a refresh; the user must connect again.
    needs_reauth: bool = False


ConnectionState = Literal[
    "not_configured", "not_connected", "connected", "reauth_required"
]


class IntegrationStatus(BaseModel):
    provider: str
    label: str
    # Investigation sources this connection unlocks.
    sources: list[str]
    state: ConnectionState
    account: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None


class PendingAuthorization(BaseModel):
    state: str
    user_id: str
    provider: str
    code_verifier: str | None = None
    expires_at: datetime
