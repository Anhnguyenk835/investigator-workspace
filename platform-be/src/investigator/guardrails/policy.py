"""Guard modes and the versioned policy every decision is recorded against."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from investigator.guardrails.budget import BudgetLimits
from investigator.guardrails.output.sanitize import DEFAULT_LINK_HOSTS
from investigator.settings import Settings

Mode = Literal["off", "monitor", "enforce"]

# policy field -> the setting that can override it
SCALARS = {
    "enabled": "guard_enabled",
    "secrets": "guard_secrets_mode",
    "pii": "guard_pii_mode",
    "injection": "guard_injection_mode",
    "output": "guard_output_mode",
    "egress": "guard_egress_mode",
    "budget": "guard_budget_mode",
    "breaker": "guard_breaker_mode",
    "audit_fail_closed": "guard_audit_fail_closed",
    "kill_switch": "guard_kill_switch",
    "breaker_threshold": "guard_breaker_threshold",
}

GUARDS = ("secrets", "pii", "injection", "output", "egress", "budget", "breaker")


class GuardPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "1"
    enabled: bool = True
    # Secret redaction is already live behaviour, so it stays enforced by default.
    secrets: Mode = "enforce"
    pii: Mode = "monitor"
    injection: Mode = "monitor"
    output: Mode = "monitor"
    egress: Mode = "monitor"
    budget: Mode = "monitor"
    breaker: Mode = "monitor"
    # Audit failing never fails a call unless a deployment asks for it.
    audit_fail_closed: bool = False
    limits: BudgetLimits = BudgetLimits()
    link_hosts: tuple[str, ...] = DEFAULT_LINK_HOSTS
    breaker_threshold: int = 5
    kill_switch: bool = False

    @property
    def fingerprint(self) -> str:
        """Version plus a hash of the content, so any decision can be tied to exact rules."""
        digest = hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:8]
        return f"{self.version}-{digest}"

    def mode(self, guard: str) -> Mode:
        if not self.enabled:
            return "off"
        value: Mode = getattr(self, guard)
        return value

    @classmethod
    def from_settings(cls, s: Settings) -> GuardPolicy:
        """Defaults, then the policy file, then anything set explicitly in the environment.
        A key the policy does not know is an error, not something to ignore."""
        data: dict[str, Any] = {}
        if s.guard_policy_file:
            data = json.loads(Path(s.guard_policy_file).read_text())
            if not isinstance(data, dict):
                raise ValueError("The guard policy file must hold a JSON object.")
        for key, attr in SCALARS.items():
            if attr in s.model_fields_set or key not in data:
                data[key] = getattr(s, attr)
        limits = dict(data.get("limits") or {})
        run = {**BudgetLimits().run.model_dump(), **(limits.get("run") or {})}
        for attr, target, key in (
            ("guard_run_max_cost_usd", run, "cost_usd"),
            ("guard_ip_day_max_cost_usd", limits, "ip_day_cost_usd"),
            ("guard_ip_day_max_cost_usd", limits, "actor_day_cost_usd"),
            ("guard_global_day_max_cost_usd", limits, "global_day_cost_usd"),
            ("demo_day_cost_usd", limits, "demo_day_cost_usd"),
        ):
            if attr in s.model_fields_set:
                target[key] = getattr(s, attr)
        limits["run"] = run
        data["limits"] = limits
        return cls(**data)
