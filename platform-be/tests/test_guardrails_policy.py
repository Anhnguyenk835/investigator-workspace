"""Policy: defaults, a JSON file, and the environment, in that order of precedence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from investigator.guardrails import GuardPolicy
from investigator.settings import Settings


def settings(
    tmp: Path, file: dict[str, object] | None = None, **env: object
) -> Settings:
    path = ""
    if file is not None:
        p = tmp / "policy.json"
        p.write_text(json.dumps(file))
        path = str(p)
    return Settings(_env_file=None, guard_policy_file=path, **env)  # type: ignore[call-arg, arg-type]


def test_defaults_enforce_secrets_and_only_watch_the_rest(tmp_path: Path) -> None:
    p = GuardPolicy.from_settings(settings(tmp_path))
    assert (p.secrets, p.pii, p.injection, p.output, p.egress) == (
        "enforce",
        "monitor",
        "monitor",
        "monitor",
        "monitor",
    )


def test_a_file_sets_modes_and_limits(tmp_path: Path) -> None:
    p = GuardPolicy.from_settings(
        settings(
            tmp_path,
            {
                "version": "2026-10",
                "pii": "enforce",
                "limits": {"chat_turn": {"calls": 5, "tokens": 9, "cost_usd": 0.1}},
            },
        )
    )
    assert p.pii == "enforce" and p.version == "2026-10"
    assert (
        p.limits.chat_turn.calls == 5 and p.limits.run.calls == 600
    )  # the rest stays default


def test_the_environment_beats_the_file(tmp_path: Path) -> None:
    p = GuardPolicy.from_settings(
        settings(
            tmp_path, {"pii": "enforce", "injection": "enforce"}, guard_pii_mode="off"
        )
    )
    assert p.pii == "off" and p.injection == "enforce"


def test_the_run_cost_cap_can_come_from_the_environment(tmp_path: Path) -> None:
    p = GuardPolicy.from_settings(
        settings(
            tmp_path,
            {"limits": {"run": {"calls": 9, "tokens": 9, "cost_usd": 1.0}}},
            guard_run_max_cost_usd=2.5,
        )
    )
    assert p.limits.run.cost_usd == 2.5 and p.limits.run.calls == 9


def test_a_typo_or_a_bad_mode_stops_startup(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        GuardPolicy.from_settings(settings(tmp_path, {"pi": "enforce"}))
    with pytest.raises(ValidationError):
        GuardPolicy.from_settings(settings(tmp_path, {"pii": "sometimes"}))
    with pytest.raises(ValidationError):
        GuardPolicy.from_settings(settings(tmp_path, {"limits": {"bogus": 1}}))


def test_the_fingerprint_changes_when_the_policy_does(tmp_path: Path) -> None:
    a = GuardPolicy.from_settings(settings(tmp_path))
    b = GuardPolicy.from_settings(settings(tmp_path, {"pii": "enforce"}))
    assert a.fingerprint != b.fingerprint
