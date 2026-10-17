"""Turns what the graph reports into run events."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from investigator.investigations.events import STEP_LABELS, EventStore

# Counts worth showing next to a finished step, by the state field they come from.
COUNTED = {
    "evidence": "records",
    "timeline": "timeline_events",
    "commitments": "commitments",
    "blockers": "blockers",
    "conflicts": "contradictions",
    "gaps": "gaps",
    "findings": "findings",
    "actions": "actions",
}


def _detail(node: str, delta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field, name in COUNTED.items():
        value = delta.get(field)
        if isinstance(value, list):
            out[name] = len(value)
    plan = delta.get("plan")
    if plan is not None and getattr(plan, "queries", None):
        out["queries"] = list(plan.queries)
    if node == "assess_evidence":
        coverage = delta.get("coverage")
        if isinstance(coverage, list):
            out["coverage"] = [
                {"source": c.source, "status": c.status} for c in coverage
            ]
    validation = delta.get("validation")
    if validation is not None and hasattr(validation, "passed"):
        out["validation_passed"] = validation.passed
    return out


class ProgressReporter:
    def __init__(self, events: EventStore, investigation_id: UUID) -> None:
        self._events = events
        self._id = investigation_id

    async def update(self, namespace: tuple[str, ...], node: str, delta: Any) -> None:
        """A graph step finished."""
        if node.startswith("__") or not isinstance(delta, dict):
            return
        data: dict[str, Any] = {
            "node": node,
            "label": STEP_LABELS.get(node, node.replace("_", " ").capitalize()),
            **_detail(node, delta),
        }
        if namespace:
            data["parent"] = namespace[0].split(":")[0]
        await self._events.append(self._id, "step", data)

    async def custom(self, chunk: Any) -> None:
        """Something a node reported while it was running (a search that just finished)."""
        if not isinstance(chunk, dict) or chunk.get("type") != "tool":
            return
        await self._events.append(
            self._id, "tool", {k: v for k, v in chunk.items() if k != "type"}
        )
