"""Who may see and change what. One place, so the rule is the same everywhere.

An investigation (and its chats, notes, events and exports) belongs to the person who started
it. A demo visitor also sees the shared sample investigations, read-only. Anyone else's, or one
that does not exist, answers 404: whether it exists is not theirs to learn.
"""

from __future__ import annotations

from collections.abc import Sequence

from investigator.auth.models import LOCAL_ID, SAMPLE_OWNER, Principal

SAMPLE_ID = str(SAMPLE_OWNER)


def viewer_ids(p: Principal) -> list[str | None]:
    """Owner ids whose investigations this principal may read. `None` is the pre-sign-in data,
    which only the local (sign-in off) user can see."""
    if p.user_id == LOCAL_ID:
        return [None, LOCAL_ID]
    return [p.user_id, SAMPLE_ID] if p.is_demo else [p.user_id]


def owner_for_new(p: Principal) -> str | None:
    return None if p.user_id == LOCAL_ID else p.user_id


def can_read(p: Principal, owner_id: str | None) -> bool:
    return owner_id in viewer_ids(p)


def can_write(p: Principal, owner_id: str | None) -> bool:
    if p.user_id == LOCAL_ID:
        return owner_id in (None, LOCAL_ID)
    return owner_id == p.user_id


def is_sample(owner_id: str | None) -> bool:
    return owner_id == SAMPLE_ID


def directory_owner(p: Principal) -> str | None:
    """Whose directory a principal works in: its own; the demo's shared one; or the pre-sign-in one."""
    if p.user_id == LOCAL_ID:
        return None
    return SAMPLE_ID if p.is_demo else p.user_id


def can_edit_directory(p: Principal) -> bool:
    return not p.is_demo


_ = Sequence
