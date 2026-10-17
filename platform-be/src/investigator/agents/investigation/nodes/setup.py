"""Main graph, steps 1-3: intake, resolve context, plan the investigation."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from investigator.agents.investigation.env import (
    UNTRUSTED,
    NodeEnv,
    ask,
    directory_of,
    effective_access,
    fail,
)
from investigator.agents.investigation.schemas import (
    ClarificationQuestion,
    InvestigationPlan,
    MentionedEntities,
)
from investigator.agents.investigation.state import InvestigationState
from investigator.guardrails.injection.spotlight import user_block

TICKET = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b")
MAX_QUERIES = 5


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for i in items:
        key = i.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(i.strip())
    return out


def intake(state: InvestigationState) -> dict[str, Any]:
    question = state.question.strip()
    if not question:
        return fail("The problem statement is empty.")
    return {"question": question, "status": "investigating"}


async def resolve_context(
    state: InvestigationState, config: RunnableConfig, *, env: NodeEnv
) -> dict[str, Any]:
    """What the problem statement itself mentions. Quoted, never guessed, and used to
    write queries only; the case scope (filters) comes from the user or the directory."""
    draft, _ = await ask(
        env,
        "Extract, verbatim, any customer names, project names, ticket ids, people and "
        "date hints mentioned in the text. Do not infer or add anything. "
        f"{UNTRUSTED}",
        user_block(state.question),
        MentionedEntities,
        route="fast",
    )
    mentioned = draft or MentionedEntities()  # extraction is helpful, not required
    tickets = _dedupe(
        [
            *TICKET.findall(state.question),
            *mentioned.ticket_ids,
            *state.context.ticket_ids,
        ]
    )
    update: dict[str, Any] = {
        "mentioned": mentioned.model_copy(update={"ticket_ids": tickets})
    }
    update.update(_scope_from_directory(state, mentioned, directory_of(config)))
    if not update.get("clarification_needed"):
        ctx = update.get("context", state.context)
        asked = await _scope_questions(
            state.model_copy(update={"context": ctx}), config, env
        )
        if asked:
            update["clarification_needed"] = asked
    return update


# What a person picks in each source, and the label for it.
SCOPE_NOUN = {
    "slack": "Slack channels",
    "jira": "Jira projects",
    "gmail": "Gmail labels",
    "confluence": "Confluence spaces",
}
MAX_CHOICES = 200


async def _scope_questions(
    state: InvestigationState, config: RunnableConfig, env: NodeEnv
) -> list[ClarificationQuestion]:
    """Searching a whole account costs time and money and reads more than the case needs,
    so before any search the person says where to look. Skipped for a source the case is
    already narrowed in (by the directory, or by an earlier answer), and for one that
    cannot list its parts."""
    ctx = effective_access(state.context, config, env)
    questions: list[ClarificationQuestion] = []
    for source in env.harness.readable_sources(ctx):
        noun = SCOPE_NOUN.get(source)
        if noun is None or source in ctx.source_filters:
            continue
        narrowed = (
            ctx.directory.filter_for(
                source, ctx.scope.customer_id, ctx.scope.project_id
            )
            if ctx.directory
            else None
        )
        if narrowed is not None and not narrowed.is_empty():
            continue
        status, options = await env.harness.suggestions(source, ctx)
        if status != "ok" or not options:
            continue
        options = options[:MAX_CHOICES]
        questions.append(
            ClarificationQuestion(
                key="source_scope",
                source=source,
                multi=True,
                question=f"Which {noun} should this investigation search?",
                options=[o["id"] for o in options],
                labels={o["id"]: o["label"] for o in options},
            )
        )
    return questions


def _scope_from_directory(
    state: InvestigationState, mentioned: MentionedEntities, directory: Any
) -> dict[str, Any]:
    """Narrow the case to a customer or project the question names. One match narrows
    it; several matches are put to the person, never picked."""
    ctx = state.context
    if directory is None or directory.is_empty() or ctx.project_id or ctx.customer_id:
        return {}
    text = " ".join([state.question, *mentioned.customers, *mentioned.projects])
    found = directory.match(text)
    if len(found.projects) == 1:
        p = found.projects[0]
        return {
            "context": ctx.model_copy(
                update={"project_id": p.id, "customer_id": p.customer_id}
            ),
            "scope_note": f"Limited to {p.name}: the question names it.",
        }
    if len(found.projects) > 1:
        return {
            "clarification_needed": [
                ClarificationQuestion(
                    key="project_id",
                    question="The question matches more than one project. Which one is this about?",
                    options=[p.id for p in found.projects],
                    labels={p.id: p.name for p in found.projects},
                )
            ]
        }
    if len(found.customers) == 1:
        c = found.customers[0]
        return {
            "context": ctx.model_copy(update={"customer_id": c.id}),
            "scope_note": f"Limited to {c.name}: the question names it.",
        }
    if len(found.customers) > 1:
        return {
            "clarification_needed": [
                ClarificationQuestion(
                    key="customer_id",
                    question="The question matches more than one customer. Which one is this about?",
                    options=[c.id for c in found.customers],
                    labels={c.id: c.name for c in found.customers},
                )
            ]
        }
    return {}


def _known_names(state: InvestigationState, directory: Any) -> str:
    """The names this case goes by, so queries can use them. Only what the directory holds."""
    ctx = state.context
    if directory is None:
        return ""
    project = directory.project(ctx.project_id)
    customer = directory.customer(
        ctx.customer_id or (project.customer_id if project else None)
    )
    names: list[str] = []
    if customer:
        names.append(
            f"customer {customer.name}"
            + (f" (also: {', '.join(customer.aliases)})" if customer.aliases else "")
        )
    if project:
        extra = [
            *project.aliases,
            *[t.rstrip("-") + "-" for t in project.ticket_prefixes],
        ]
        names.append(
            f"project {project.name}"
            + (f" (also: {', '.join(extra)})" if extra else "")
        )
    return ("Known names for this case: " + "; ".join(names) + "\n") if names else ""


async def plan_investigation(
    state: InvestigationState, config: RunnableConfig, *, env: NodeEnv
) -> dict[str, Any]:
    ctx = state.context
    notes = user_block("\n".join(f"- {n}" for n in state.reviewer_notes))
    draft, _ = await ask(
        env,
        "Plan a search for a customer escalation. List up to 5 key questions the "
        "investigation must answer and up to 5 search queries likely to find the relevant "
        "records. A source matches a query only if a record contains ALL of its words, so "
        "keep every query to 1-3 words: a distinctive name, ticket id or term, never a "
        "sentence. Mix one or two broad single-word queries with narrower ones. Do not "
        f"invent names or ids that are not given. {UNTRUSTED}",
        f"Problem: {user_block(state.question)}\nMentioned: {state.mentioned.model_dump_json()}\n"
        f"Dates: {ctx.date_from or 'any'}..{ctx.date_to or 'any'}\n"
        + _known_names(state, directory_of(config))
        + (f"Reviewer asked for more evidence:\n{notes}\n" if notes else ""),
        InvestigationPlan,
        route="fast",
    )
    plan = draft or InvestigationPlan()
    # A plan that comes back empty falls back to the problem statement itself.
    queries = _dedupe([*plan.queries, *state.mentioned.ticket_ids])[:MAX_QUERIES]
    if not queries:
        queries = [state.question[:300]]
    return {"plan": InvestigationPlan(questions=plan.questions, queries=queries)}
