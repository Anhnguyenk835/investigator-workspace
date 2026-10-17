"""The reusable tool-loop pattern: `agent ⇄ tools`, bounded, with a final `wrap_up`.

    agent ── tool calls ──► tools ── budget left ──► agent
      │                       └─ exhausted ─► wrap_up ─► exit
      └─ no tool calls / failure ──────────────────► exit

Any subgraph whose state extends `ToolLoopState` can add this loop with
`add_tool_loop`. All tool use goes through `ToolHarness`, so scope clamping,
budgets, caching, timeouts and audit apply everywhere the loop is used.
The state, not the chat transcript, is the source of truth: `tools` merges
returned records into `evidence`/`coverage`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from investigator.agents.investigation.env import (
    NodeEnv,
    effective_access,
    ledger_of,
    ledger_update,
)
from investigator.agents.investigation.schemas import CaseContext
from investigator.connectors import EvidenceRecord, SourceCoverage
from investigator.guardrails import GuardDegraded, current, purpose
from investigator.llm import (
    AssistantTurn,
    ChatMessage,
    LlmError,
    Route,
    messages_as_text,
)
from investigator.tools import CallOutcome, ToolEvent

WRAP_UP = (
    "You have used every tool round this task allows. Reply now with plain-text notes: "
    "what was searched, and which data you could not retrieve."
)


STOPPED = "Searching stopped early: "


def tools_purpose() -> str:
    """The label for the loop's model turns: `investigation.tools` is optional work that is
    cut first when a run is short of budget; a chat turn's own label is kept."""
    return f"{current().purpose.split('.')[0]}.tools"


# One model turn. The default calls the model and waits; a caller that streams
# text to a person supplies its own (see agents/chat).
TurnFn = Callable[
    [Sequence[ChatMessage], list[dict[str, Any]], Route], Awaitable[AssistantTurn]
]


def announce(events: list[ToolEvent]) -> None:
    """Tell a live listener what was just searched. Metadata only, never content."""
    try:
        write = get_stream_writer()
    except RuntimeError:
        return
    for e in events:
        write(
            {
                "type": "tool",
                "tool": e.tool,
                "source": e.source,
                "status": e.status,
                "records": e.records,
                "new_records": e.new_records,
                "note": e.note,
            }
        )


class ToolLoopState(BaseModel):
    context: CaseContext = Field(default_factory=CaseContext)
    # Harness-owned.
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    coverage: list[SourceCoverage] = Field(default_factory=list)
    seen_calls: dict[str, str] = Field(default_factory=dict)
    pending_cursors: dict[str, list[str]] = Field(default_factory=dict)
    call_outcomes: dict[str, CallOutcome] = Field(default_factory=dict)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    calls_used: int = 0
    # Loop-owned.
    messages: list[ChatMessage] = Field(default_factory=list)
    tool_rounds: int = 0
    stale_rounds: int = 0
    search_notes: str | None = None
    error: str | None = None


def exhausted(state: ToolLoopState, env: NodeEnv) -> bool:
    lim = env.harness.limits
    return (
        state.tool_rounds >= lim.max_rounds
        or state.calls_used >= lim.max_tool_calls
        or state.stale_rounds >= lim.max_stale_rounds
    )


def add_tool_loop(
    builder: StateGraph,  # type: ignore[type-arg]
    env: NodeEnv,
    opening: Callable[[Any], list[ChatMessage]],
    *,
    exit_to: str = END,
    turn: TurnFn | None = None,
) -> None:
    """Add `agent`, `tools`, `wrap_up` to `builder`; the caller routes into `agent`."""

    async def default_turn(
        messages: Sequence[ChatMessage], tools: list[dict[str, Any]], route: Route
    ) -> AssistantTurn:
        return await env.llm.complete_with_tools(messages, tools, route)

    model_turn = turn or default_turn

    async def agent(state: Any, config: RunnableConfig) -> dict[str, Any]:
        ctx = effective_access(state.context, config, env)
        messages = state.messages or opening(state)
        try:
            with purpose(tools_purpose()):
                answer = await model_turn(
                    messages, env.harness.tool_schemas(ctx), env.agent_route
                )
        except GuardDegraded as exc:
            # Out of budget for more searching: carry on to the next step with what was found.
            return {"search_notes": STOPPED + str(exc), "messages": messages}
        except LlmError as exc:
            return {"error": str(exc), "messages": messages}
        update: dict[str, Any] = {"messages": [*messages, answer.message]}
        if not answer.message.tool_calls:
            update["search_notes"] = answer.message.content
        return update

    async def tools(state: Any, config: RunnableConfig) -> dict[str, Any]:
        ctx = effective_access(state.context, config, env)
        ledger = ledger_of(state)
        before = len(ledger.evidence)
        announced = len(ledger.events)
        results = await env.harness.run_calls(
            state.messages[-1].tool_calls or [], ledger, ctx
        )
        replies = [
            ChatMessage(role="tool", content=text, tool_call_id=call.id, name=call.name)
            for call, text in results
        ]
        added = len(ledger.evidence) - before
        announce(ledger.events[announced:])
        return {
            **ledger_update(ledger),
            "messages": [*state.messages, *replies],
            "tool_rounds": state.tool_rounds + 1,
            "stale_rounds": 0 if added else state.stale_rounds + 1,
        }

    async def wrap_up(state: Any) -> dict[str, Any]:
        """Last turn with no tools bound; tool history is written out as text."""
        history = [
            *messages_as_text(state.messages),
            ChatMessage(role="user", content=WRAP_UP),
        ]
        try:
            with purpose(tools_purpose()):
                answer = await model_turn(history, [], env.agent_route)
        except GuardDegraded as exc:
            return {"search_notes": STOPPED + str(exc)}
        except LlmError as exc:
            return {"error": str(exc)}
        return {"search_notes": answer.message.content}

    def after_agent(state: Any) -> str:
        if state.error:
            return "exit"
        last = state.messages[-1] if state.messages else None
        return "tools" if last is not None and last.tool_calls else "exit"

    def after_tools(state: Any) -> str:
        return "wrap_up" if exhausted(state, env) else "agent"

    builder.add_node("agent", agent)
    builder.add_node("tools", tools)
    builder.add_node("wrap_up", wrap_up)
    builder.add_conditional_edges(
        "agent", after_agent, {"tools": "tools", "exit": exit_to}
    )
    builder.add_conditional_edges(
        "tools", after_tools, {"agent": "agent", "wrap_up": "wrap_up"}
    )
    builder.add_edge("wrap_up", exit_to)
