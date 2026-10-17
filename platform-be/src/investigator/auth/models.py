"""Who is asking."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

Kind = Literal["user", "demo"]

# The one user when sign-in is off, and the owner of the shared sample investigations.
LOCAL_ID = "local"
SAMPLE_OWNER = UUID("00000000-0000-0000-0000-00000000d3a0")


class User(BaseModel):
    id: UUID
    kind: Kind
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    google_sub: str | None = None
    created_at: datetime | None = None


class Principal(BaseModel):
    """What a request is acting as. `user_id` is a string because sign-in being off uses
    the fixed id `local`."""

    user_id: str
    kind: Kind = "user"
    email: str | None = None
    name: str | None = None
    picture: str | None = None

    @property
    def is_demo(self) -> bool:
        return self.kind == "demo"

    @property
    def actor(self) -> str:
        """A label for who did what: the verified email, else the name."""
        if self.is_demo:
            return f"Demo visitor {self.user_id[:6]}"
        return self.email or self.name or self.user_id


LOCAL = Principal(user_id=LOCAL_ID, name="Local user")


def principal_of(user: User) -> Principal:
    return Principal(
        user_id=str(user.id),
        kind=user.kind,
        email=user.email,
        name=user.name or (None if user.kind == "user" else "Demo visitor"),
        picture=user.picture,
    )
