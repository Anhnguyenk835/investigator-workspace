"""Who a model call is for. Carried in a ContextVar so every call under a run sees it,
including the concurrent ones (asyncio copies the context into each task)."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

from pydantic import BaseModel, Field


class GuardContext(BaseModel):
    run_id: str | None = None
    thread_id: str | None = None
    # A name the person typed. Never a verified identity.
    actor: str | None = None
    actor_verified: bool = False
    # A demo visitor: their spend also counts toward the demo's own daily cap.
    demo: bool = False
    ip: str | None = None
    purpose: str = "unbound"
    # Identifiers (normalised, `KIND:value`) the model has been shown during this run. A
    # search for one it was never given is not following the case. Shared by every copy of
    # the context made under the same run, so work done in parallel adds to one set.
    shown: set[str] = Field(default_factory=set)
    # People's names learned during the run, from the metadata the connectors read and the
    # directory. Shared like `shown`.
    names: set[str] = Field(default_factory=set)


UNBOUND = GuardContext()
_current: ContextVar[GuardContext] = ContextVar("guard_context", default=UNBOUND)


def current() -> GuardContext:
    return _current.get()


@contextmanager
def bind(
    *,
    run_id: str | None = None,
    thread_id: str | None = None,
    actor: str | None = None,
    ip: str | None = None,
    verified: bool = False,
    demo: bool = False,
    purpose: str | None = None,
    names: Iterable[str] = (),
) -> Iterator[GuardContext]:
    ctx = GuardContext(
        run_id=run_id,
        thread_id=thread_id,
        actor=actor,
        actor_verified=verified,
        demo=demo,
        ip=ip,
        purpose=purpose or "run",
        names=set(names),
    )
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _reset(token)


def _reset(token: Token[GuardContext]) -> None:
    # An async generator can be finalised in another context; the value then dies with it.
    with contextlib.suppress(ValueError):
        _current.reset(token)


@contextmanager
def purpose(name: str) -> Iterator[GuardContext]:
    """Label the calls made inside, keeping who they are for."""
    ctx = current().model_copy(update={"purpose": name})
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _reset(token)
