"""Which sources a person has connected right now.

An investigation keeps a snapshot of what could be searched when it ran. A person may connect
Slack or Jira afterwards, so a conversation about it asks again, at the time of the question.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Literal

from pydantic import BaseModel

from investigator.auth.models import Principal
from investigator.demo import DemoCorpus
from investigator.integrations import IntegrationStatus, OAuthService

SourceState = Literal["connected", "reconnect", "not_connected", "not_configured"]

_STATE: dict[str, SourceState] = {
    "connected": "connected",
    "reauth_required": "reconnect",
    "not_connected": "not_connected",
    "not_configured": "not_configured",
}


class SourceNow(BaseModel):
    source: str
    state: SourceState
    account: str | None = None


# Who is asking -> what they can search now.
Availability = Callable[[Principal], Awaitable[list[SourceNow]]]


def from_integrations(
    statuses: Iterable[IntegrationStatus], sources: Iterable[str]
) -> list[SourceNow]:
    """One row per source the backend can read; a source several providers unlock (none
    today) counts as connected if any of them is."""
    best: dict[str, SourceNow] = {}
    rank: list[SourceState] = [
        "not_configured",
        "not_connected",
        "reconnect",
        "connected",
    ]
    for s in statuses:
        state = _STATE[s.state]
        for name in s.sources:
            old = best.get(name)
            if old is None or rank.index(state) > rank.index(old.state):
                best[name] = SourceNow(source=name, state=state, account=s.account)
    return [
        best.get(n) or SourceNow(source=n, state="not_configured")
        for n in sorted(set(sources))
    ]


def build(
    oauth: OAuthService | None,
    demo: DemoCorpus | None,
    sources: Iterable[str],
) -> Availability:
    names = sorted(set(sources))

    async def now(principal: Principal) -> list[SourceNow]:
        if principal.is_demo:
            have = set((await demo.index()).sources) if demo else set()
            return [
                SourceNow(
                    source=n,
                    state="connected" if n in have else "not_connected",
                    account="Demo data" if n in have else None,
                )
                for n in names
            ]
        if oauth is None:
            return [SourceNow(source=n, state="not_configured") for n in names]
        return from_integrations(await oauth.status(principal.user_id), names)

    return now
