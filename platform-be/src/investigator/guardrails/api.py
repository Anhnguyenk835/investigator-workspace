"""Operator endpoints: what the guards are doing, and the off switch.

Protected by a shared token (`GUARD_ADMIN_TOKEN`, sent as `X-Admin-Token`); with no token
configured the endpoints do not exist. A shared token is not an identity: it stops a
stranger from flipping the switch, and nothing more."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from investigator.guardrails.events import GuardEvent
from investigator.guardrails.policy import GUARDS
from investigator.guardrails.runtime import GuardRuntime

router = APIRouter(prefix="/admin/guardrails", tags=["guardrails"])

SCOPES = ("all", "route:", "purpose:")


def _guard(request: Request) -> GuardRuntime:
    state = request.app.state.app
    token: str = getattr(state, "admin_token", "")
    rt: GuardRuntime | None = getattr(state, "guard", None)
    if not token or rt is None:
        raise HTTPException(404, "Not found.")
    sent = request.headers.get("x-admin-token", "")
    if not hmac.compare_digest(sent.encode(), token.encode()):
        raise HTTPException(401, "Missing or wrong admin token.")
    return rt


Rt = Annotated[GuardRuntime, Depends(_guard)]


class Kill(BaseModel):
    scope: str = Field(default="all", max_length=80)
    reason: str = Field(default="", max_length=200)


def _valid(scope: str) -> bool:
    return scope == "all" or any(
        scope.startswith(p) and len(scope) > len(p) for p in SCOPES[1:]
    )


@router.get("/status")
async def status(rt: Rt) -> dict[str, Any]:
    flags = await rt.kill.active()
    return {
        "policy_version": rt.policy.fingerprint,
        "enabled": rt.policy.enabled,
        "modes": {g: rt.mode(g) for g in GUARDS},
        "breakers": rt.breakers.states(),
        "kill": {
            "forced_by_configuration": rt.kill.forced,
            "flags": [f.model_dump(mode="json") for f in flags],
        },
        "identity": "unauthenticated: IP and a self-declared name",
    }


@router.get("/summary")
async def summary(rt: Rt, hours: int = 24) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 24 * 30)))
    data = await rt.sink.summary(since)
    today = await rt.budget.store.totals(rt.budget.day(), None, None)
    return {
        "since": since.isoformat(),
        **data,
        "today": today["global"].model_dump(),
        "policy_version": rt.policy.fingerprint,
        "modes": {g: rt.mode(g) for g in GUARDS},
        "breakers": rt.breakers.states(),
    }


@router.get("/events", response_model=list[GuardEvent])
async def events(
    rt: Rt,
    guard: str | None = None,
    run_id: str | None = None,
    hours: int = 24,
    limit: int = 100,
) -> list[GuardEvent]:
    since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 24 * 30)))
    return await rt.sink.recent_events(since, guard, run_id, max(1, min(limit, 500)))


@router.post("/kill", status_code=201)
async def kill(body: Kill, request: Request, rt: Rt) -> dict[str, str]:
    """Stop model calls: `all`, `route:<name>` or `purpose:<name>`. Takes effect within
    seconds in every process; running investigations pause and can be resumed."""
    if not _valid(body.scope):
        raise HTTPException(422, "scope must be all, route:<name> or purpose:<name>.")
    from investigator.api.dispatch import actor_of

    await rt.flags.set(body.scope, body.reason, actor_of(request) or "admin")
    await rt.kill.refresh()
    await rt.emit(
        "kill",
        "switch_set",
        enforced=True,
        action="block",
        severity="high",
        detail=body.scope,
    )
    return {"scope": body.scope, "state": "paused"}


@router.delete("/kill", status_code=200)
async def resume(rt: Rt, scope: str = "all") -> dict[str, str]:
    if not _valid(scope):
        raise HTTPException(422, "scope must be all, route:<name> or purpose:<name>.")
    await rt.flags.clear(scope)
    await rt.kill.refresh()
    await rt.emit("kill", "switch_cleared", enforced=True, detail=scope)
    return {"scope": scope, "state": "running"}
