"""M1: budgets, circuit breaker, kill switch, and what a run does when it is refused."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from investigator.api.app import AppState, create_app
from investigator.guardrails import (
    GuardBlocked,
    GuardDegraded,
    GuardedLlm,
    GuardPolicy,
    GuardRuntime,
    MemoryAuditSink,
    bind,
)
from investigator.guardrails.breaker import CircuitBreaker
from investigator.guardrails.budget import (
    BudgetLimits,
    BudgetTracker,
    RunLimits,
    Usage,
    price,
)
from investigator.llm import AssistantTurn, ChatMessage, GatewayError, LlmError
from investigator.tools import AccessContext
from tests.conftest import MemoryStore
from tests.fakes import ScriptedLlm, text_turn, tool_turn

MSG = [ChatMessage(role="user", content="hello")]


def turn(prompt: int = 100, completion: int = 50) -> AssistantTurn:
    t = text_turn("ok")
    return t.model_copy(
        update={"prompt_tokens": prompt, "completion_tokens": completion}
    )


def rt(
    *,
    limits: BudgetLimits | None = None,
    budget: str = "enforce",
    breaker: str = "enforce",
    **kw: Any,
) -> GuardRuntime:
    policy = GuardPolicy(
        budget=budget,  # type: ignore[arg-type]
        breaker=breaker,  # type: ignore[arg-type]
        limits=limits or BudgetLimits(),
        breaker_threshold=2,
        **kw,
    )
    return GuardRuntime.for_tests(policy)


# ---- cost --------------------------------------------------------------------------


def test_cost_uses_the_route_price() -> None:
    lim = BudgetLimits()
    assert price(lim, "fast", 1_000_000, 0) == pytest.approx(0.25)
    assert price(lim, "strong", 0, 1_000_000) == pytest.approx(10.0)
    assert price(lim, "unknown-route", 1_000_000, 0) == pytest.approx(1.25)


async def test_a_call_updates_usage_and_the_audit_cost() -> None:
    r = rt()
    llm = GuardedLlm(ScriptedLlm([turn(1000, 500)]), r)
    with bind(run_id="r", thread_id="t1", actor="Sam", ip="9.9.9.9"):
        await llm.complete_with_tools(MSG, [], "strong")
    sink = r.sink
    assert isinstance(sink, MemoryAuditSink)
    assert sink.calls[0].cost_usd == pytest.approx(0.00125 + 0.005)
    day = await r.budget.store.totals(r.budget.day(), "9.9.9.9", "Sam")
    assert day["ip"].calls == 1 and day["global"].tokens == 1500
    assert day["actor"].cost_usd == pytest.approx(0.00625)


async def test_missing_usage_is_estimated_and_marked() -> None:
    r = rt()
    llm = GuardedLlm(ScriptedLlm([turn(0, 0)]), r)
    with bind(run_id="r", thread_id="t"):
        await llm.complete_with_tools(MSG, [])
    call = r.sink.calls[0]  # type: ignore[attr-defined]
    assert call.usage_estimated and call.prompt_tokens > 0


# ---- per-run limits and the degrade ladder ----------------------------------------


def small_run(calls: int = 10) -> BudgetLimits:
    return BudgetLimits(run=RunLimits(calls=calls, tokens=10**9, cost_usd=10**6))


async def test_optional_work_stops_at_80_percent_but_essential_work_continues() -> None:
    r = rt(limits=small_run(10))
    llm = GuardedLlm(ScriptedLlm([turn() for _ in range(20)]), r)
    from investigator.guardrails import purpose

    with bind(run_id="r", thread_id="t", purpose="investigation"):
        for _ in range(8):
            await llm.complete_with_tools(MSG, [])
        with purpose("support.check"), pytest.raises(GuardDegraded):
            await llm.complete_with_tools(MSG, [])
        await llm.complete_with_tools(MSG, [])  # essential: still allowed
        await llm.complete_with_tools(MSG, [])
        with pytest.raises(GuardDegraded):  # now the hard limit: everything stops
            await llm.complete_with_tools(MSG, [])
    statuses = [c.status for c in r.sink.calls]  # type: ignore[attr-defined]
    assert statuses.count("degraded") == 2


async def test_a_refused_call_never_reaches_the_model() -> None:
    inner = ScriptedLlm([turn()])
    r = rt(limits=small_run(0))
    with bind(run_id="r", thread_id="t"), pytest.raises(GuardBlocked) as err:
        await GuardedLlm(inner, r).complete_with_tools(MSG, [])
    assert inner.tool_calls_seen == [] and "budget" in str(err.value)


async def test_monitor_mode_records_but_does_not_refuse() -> None:
    r = rt(limits=small_run(0), budget="monitor")
    llm = GuardedLlm(ScriptedLlm([turn()]), r)
    with bind(run_id="r", thread_id="t"):
        await llm.complete_with_tools(MSG, [])
    events = r.sink.events  # type: ignore[attr-defined]
    assert events and not events[0].enforced and events[0].rule == "run_calls"


async def test_chat_turns_have_their_own_smaller_limit() -> None:
    lim = BudgetLimits(chat_turn=RunLimits(calls=1, tokens=10**9, cost_usd=1e6))
    r = rt(limits=lim)
    llm = GuardedLlm(ScriptedLlm([turn(), turn()]), r)
    with bind(run_id="inv", thread_id="turn-1", purpose="chat"):
        await llm.complete_with_tools(MSG, [])
        with pytest.raises(GuardBlocked):
            await llm.complete_with_tools(MSG, [])
    with bind(run_id="inv", thread_id="turn-2", purpose="chat"):
        await llm.complete_with_tools(MSG, [])  # a new turn starts fresh


async def test_an_oversized_request_is_refused_before_sending() -> None:
    r = rt(limits=BudgetLimits(max_input_tokens=100))
    big = [ChatMessage(role="user", content="x" * 5000)]
    with pytest.raises(GuardBlocked) as err:
        await GuardedLlm(ScriptedLlm([turn()]), r).complete_with_tools(big, [])
    assert err.value.rule == "call_too_large"


# ---- per-day limits keyed by IP and by the self-declared name ----------------------


async def test_daily_allowance_is_per_ip_and_blocks_hard() -> None:
    lim = BudgetLimits(ip_day_cost_usd=0.001)
    r = rt(limits=lim)
    llm = GuardedLlm(ScriptedLlm([turn(100_000, 100_000) for _ in range(3)]), r)
    with bind(run_id="a", thread_id="a", ip="1.1.1.1", actor="Sam"):
        await llm.complete_with_tools(MSG, [], "strong")
    with (
        bind(run_id="b", thread_id="b", ip="1.1.1.1", actor="Someone Else"),
        pytest.raises(GuardBlocked) as err,  # same IP, different declared name
    ):
        await llm.complete_with_tools(MSG, [], "strong")
    assert err.value.rule == "ip_day_cost" and not isinstance(err.value, GuardDegraded)
    with bind(run_id="c", thread_id="c", ip="2.2.2.2", actor="Sam"):
        await llm.complete_with_tools(
            MSG, [], "strong"
        )  # another address is unaffected


async def test_the_day_rolls_over() -> None:
    now = [datetime(2026, 10, 17, 23, 59, tzinfo=UTC)]
    t = BudgetTracker(BudgetLimits(global_day_cost_usd=1.0), clock=lambda: now[0])
    from investigator.guardrails import GuardContext

    ctx = GuardContext(run_id="r")
    await t.record(ctx, "x", 10, 2.0)
    assert [v.rule for v in await t.check(ctx, "x", 1)] == ["global_day_cost"]
    now[0] += timedelta(minutes=2)
    assert await t.check(ctx, "x", 1) == []
    assert (await t.store.totals(t.day(), None, None))["global"] == Usage()


# ---- circuit breaker ---------------------------------------------------------------


def test_breaker_opens_backs_off_and_recovers() -> None:
    clock = [0.0]
    b = CircuitBreaker(
        threshold=2, cooldown=30, max_cooldown=100, clock=lambda: clock[0]
    )
    assert b.allow()
    b.failure()
    assert b.state == "closed"
    b.failure()
    assert str(b.state) == "open" and not b.allow()
    clock[0] = 31
    assert str(b.state) == "half_open" and b.allow()
    assert not b.allow()  # only one probe at a time
    b.failure()  # the probe failed: longer cooldown
    clock[0] = 31 + 59
    assert str(b.state) == "open"
    clock[0] = 31 + 61
    assert b.allow()
    b.success()
    assert str(b.state) == "closed" and b.allow()


class Down:
    async def complete_with_tools(self, *_: Any, **__: Any) -> AssistantTurn:
        raise GatewayError("502")


async def test_gateway_failures_open_the_breaker_and_stop_calling() -> None:
    r = rt()
    llm = GuardedLlm(Down(), r)
    for _ in range(2):
        with pytest.raises(GatewayError):
            await llm.complete_with_tools(MSG, [])
    with pytest.raises(GuardBlocked) as err:
        await llm.complete_with_tools(MSG, [])
    assert err.value.rule == "circuit_open" and "not responding" in str(err.value)
    assert r.breakers.states() == {"fast": "open"}


async def test_unusable_output_is_not_a_gateway_failure() -> None:
    class Garbled:
        async def complete_with_tools(self, *_: Any, **__: Any) -> AssistantTurn:
            raise LlmError("returned output that does not match")

    r = rt()
    llm = GuardedLlm(Garbled(), r)
    for _ in range(5):
        with pytest.raises(LlmError):
            await llm.complete_with_tools(MSG, [])
    assert r.breakers.states() == {"fast": "closed"}


async def test_breaker_in_monitor_mode_keeps_calling() -> None:
    r = rt(breaker="monitor")
    for _ in range(3):
        with pytest.raises(GatewayError):
            await GuardedLlm(Down(), r).complete_with_tools(MSG, [])
    assert any(e.rule == "circuit_open" and not e.enforced for e in r.sink.events)  # type: ignore[attr-defined]


# ---- kill switch -------------------------------------------------------------------


async def test_kill_switch_scopes() -> None:
    r = rt()
    llm = GuardedLlm(ScriptedLlm([turn() for _ in range(5)]), r)
    await r.flags.set("route:strong", "cost incident", "ops")
    await r.kill.refresh()
    await llm.complete_with_tools(MSG, [], "fast")
    with pytest.raises(GuardBlocked) as err:
        await llm.complete_with_tools(MSG, [], "strong")
    assert err.value.guard == "kill" and "cost incident" in str(err.value)
    await r.flags.clear("route:strong")
    await r.flags.set("purpose:chat", "", "ops")
    await r.kill.refresh()
    with bind(purpose="chat"), pytest.raises(GuardBlocked):
        await llm.complete_with_tools(MSG, [], "fast")
    await r.flags.clear("purpose:chat")
    await r.kill.refresh()
    await llm.complete_with_tools(MSG, [], "fast")
    assert [c.status for c in r.sink.calls if c.status != "ok"] == ["killed", "killed"]  # type: ignore[attr-defined]


async def test_kill_switch_all_and_forced_by_configuration() -> None:
    r = rt(kill_switch=True)
    with pytest.raises(GuardBlocked):
        await GuardedLlm(ScriptedLlm([turn()]), r).complete_with_tools(MSG, [])
    r2 = rt()
    await r2.flags.set("all", "", "ops")
    await r2.kill.refresh()
    with pytest.raises(GuardBlocked):
        await GuardedLlm(ScriptedLlm([turn()]), r2).complete_with_tools(MSG, [])


async def test_kill_switch_reads_are_cached_and_survive_a_broken_store() -> None:
    r = rt()
    await r.flags.set("all", "", "ops")
    await r.kill.refresh()
    assert await r.kill.reason("fast", "x") is not None

    async def boom() -> list[Any]:
        raise RuntimeError("db down")

    r.flags.all = boom  # type: ignore[method-assign]
    await r.kill.refresh()
    assert await r.kill.reason("fast", "x") is not None  # last known value stays


async def test_kill_switch_cuts_a_stream_mid_answer() -> None:
    r = rt()
    llm = GuardedLlm(ScriptedLlm([text_turn("one two three four five")]), r)
    seen: list[str] = []
    with pytest.raises(GuardBlocked):
        async for item in llm.stream_with_tools(MSG, []):
            seen.append(getattr(item, "text", ""))
            if len(seen) == 2:
                await r.flags.set("all", "stop", "ops")
                await r.kill.refresh()
    assert len(seen) == 2 and r.sink.calls[0].status == "error"  # type: ignore[attr-defined]


# ---- secrets in what people type ---------------------------------------------------


async def test_secrets_typed_by_a_person_never_reach_the_model() -> None:
    inner = ScriptedLlm([turn()])
    r = rt()
    secret = "password: hunter2hunter2"
    await GuardedLlm(inner, r).complete_with_tools(
        [ChatMessage(role="user", content=f"why did it fail? {secret}")], []
    )
    sent = inner.tool_calls_seen[0][0][0].content
    assert "hunter2" not in sent and "[REDACTED]" in sent
    assert r.sink.events[0].rule == "redacted_in_prompt" and r.sink.events[0].enforced  # type: ignore[attr-defined]


async def test_secrets_in_monitor_mode_are_reported_not_changed() -> None:
    inner = ScriptedLlm([turn()])
    r = rt(secrets="monitor")
    await GuardedLlm(inner, r).complete_with_tools(
        [ChatMessage(role="user", content="token: abcdefghij1234567890")], []
    )
    assert "abcdefghij1234567890" in inner.tool_calls_seen[0][0][0].content
    assert not r.sink.events[0].enforced  # type: ignore[attr-defined]


# ---- the tool loop under a budget --------------------------------------------------


async def test_the_tool_loop_stops_searching_when_the_budget_is_short() -> None:
    from langchain_core.runnables import RunnableConfig  # noqa: F401
    from langgraph.graph import START, StateGraph

    from investigator.agents.investigation.env import NodeEnv
    from investigator.agents.investigation.tool_loop import ToolLoopState, add_tool_loop
    from investigator.tools import ToolHarness
    from tests.scenario import make_graph  # noqa: F401  (import check only)

    r = rt(limits=small_run(2))
    scripted = ScriptedLlm(
        [tool_turn(("search_records", {"source": "email", "query": "q"}))] * 8
    )
    llm = GuardedLlm(scripted, r)
    env = NodeEnv(
        llm=llm,
        harness=ToolHarness({}),
        agent_route="fast",
        default_access=AccessContext(
            user_id="u", permitted_sources=frozenset({"email"})
        ),
        now=lambda: datetime.now(UTC),
    )
    b: StateGraph[ToolLoopState, Any, ToolLoopState, ToolLoopState] = StateGraph(
        ToolLoopState
    )
    add_tool_loop(b, env, lambda s: [ChatMessage(role="user", content="go")])
    b.add_edge(START, "agent")
    graph = b.compile()
    with bind(run_id="r", thread_id="t", purpose="investigation"):
        out = await graph.ainvoke(ToolLoopState(), {"recursion_limit": 50})
    assert out.get("error") is None
    assert out["search_notes"].startswith("Searching stopped early")
    assert len(scripted.tool_calls_seen) == 2  # the wrap-up turn was refused


# ---- admin API ---------------------------------------------------------------------


def client(token: str = "s3cret") -> tuple[TestClient, GuardRuntime]:
    guard = rt()
    state = AppState(
        store=MemoryStore(),
        graph=None,
        access=AccessContext(user_id="local", permitted_sources=frozenset()),
        guard=guard,
        admin_token=token,
    )
    return TestClient(create_app(state)), guard


def test_admin_api_is_off_without_a_token_and_needs_it_with_one() -> None:
    c, _ = client(token="")
    assert c.get("/admin/guardrails/status").status_code == 404
    c, _ = client()
    assert c.get("/admin/guardrails/status").status_code == 401
    assert (
        c.get("/admin/guardrails/status", headers={"x-admin-token": "nope"}).status_code
        == 401
    )
    ok = c.get("/admin/guardrails/status", headers={"x-admin-token": "s3cret"})
    assert ok.status_code == 200 and ok.json()["modes"]["secrets"] == "enforce"
    assert "unauthenticated" in ok.json()["identity"]


async def test_admin_kill_and_resume_round_trip_and_summary() -> None:
    c, guard = client()
    h = {"x-admin-token": "s3cret", "x-actor": "Ops"}
    assert (
        c.post("/admin/guardrails/kill", json={"scope": "bogus"}, headers=h).status_code
        == 422
    )
    assert (
        c.post(
            "/admin/guardrails/kill",
            json={"scope": "all", "reason": "incident"},
            headers=h,
        ).status_code
        == 201
    )
    with pytest.raises(GuardBlocked):
        await GuardedLlm(ScriptedLlm([turn()]), guard).complete_with_tools(MSG, [])
    status = c.get("/admin/guardrails/status", headers=h).json()
    assert status["kill"]["flags"][0]["set_by"] == "Ops"
    assert c.delete("/admin/guardrails/kill?scope=all", headers=h).status_code == 200
    await GuardedLlm(ScriptedLlm([turn()]), guard).complete_with_tools(MSG, [])
    s = c.get("/admin/guardrails/summary", headers=h).json()
    assert s["calls"] == 2 and s["by_status"] == {"killed": 1, "ok": 1}
    assert {r["rule"] for r in s["rules"]} >= {"kill_switch", "switch_set"}
    ev = c.get("/admin/guardrails/events?guard=kill", headers=h).json()
    assert ev and all(e["guard"] == "kill" for e in ev)
