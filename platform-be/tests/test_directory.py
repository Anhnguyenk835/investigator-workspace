"""The directory: naming, narrowing a source to a case, tagging records, telling people apart."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi.testclient import TestClient
from langgraph.types import Command

from investigator.agents.investigation.schemas import (
    CaseContext,
    ClarificationResume,
    InvestigationPlan,
)
from investigator.api.app import AppState, create_app
from investigator.connectors.base import SearchQuery
from investigator.connectors.confluence import ConfluenceConnector
from investigator.connectors.gmail import GmailConnector
from investigator.connectors.jira import JiraConnector
from investigator.connectors.slack import SlackConnector
from investigator.directory import (
    Customer,
    Directory,
    MemoryDirectoryStore,
    Person,
    Project,
)
from investigator.tools import AccessContext, CaseScope
from tests.conftest import MemoryStore
from tests.fakes import FakeConnector, ScriptedLlm, access, rec, result
from tests.scenario import NOW, make_graph, structured
from tests.test_connectors import CTX, Net, Tokens, gmail_net, jira_net, slack_net

ACME = Customer(
    id="cus_acme", name="Acme Fund", aliases=["Acme"], email_domains=["acme.test"]
)
BETA = Customer(id="cus_beta", name="Beta Capital", email_domains=["beta.test"])
P4 = Project(
    id="prj_f4",
    customer_id="cus_acme",
    name="Fund IV Close",
    aliases=["Fund IV"],
    ticket_prefixes=["HPF-"],
    jira_projects=["HPF"],
    jira_labels=["fund-iv"],
    slack_channel_ids=["C0000000001"],
    gmail_labels=["fund-iv"],
    confluence_spaces=["OPS"],
)
P5 = Project(
    id="prj_f5",
    customer_id="cus_acme",
    name="Fund V Close",
    aliases=["Fund V"],
    slack_channel_ids=["C0000000002"],
)
PB = Project(id="prj_b", customer_id="cus_beta", name="Beta Onboarding")
SAM = Person(
    id="per_sam",
    name="Sam Kim",
    emails=["sam@us.test"],
    slack_ids=["U1"],
    jira_account_ids=["acc-1"],
    side="internal",
    role="CSM",
)
MARIA = Person(
    id="per_maria",
    name="Maria Chen",
    emails=["maria@acme.test"],
    side="customer",
    role="Client",
)
DIRECTORY = Directory(
    customers=[ACME, BETA], projects=[P4, P5, PB], people=[SAM, MARIA]
)


# ---- names ----------------------------------------------------------------------------


def test_match_finds_names_aliases_and_ticket_prefixes_on_word_boundaries() -> None:
    m = DIRECTORY.match("What happened with fund iv and the form?")
    assert [p.id for p in m.projects] == ["prj_f4"] and [c.id for c in m.customers] == [
        "cus_acme"
    ]
    assert [p.id for p in DIRECTORY.match("See HPF-123 please").projects] == ["prj_f4"]
    assert DIRECTORY.match("Fund IVA is unrelated").projects == []
    assert DIRECTORY.match("hpf-x and HPFX-1").projects == []
    both = DIRECTORY.match("Compare Fund IV with Fund V")
    assert {p.id for p in both.projects} == {"prj_f4", "prj_f5"}
    assert [c.id for c in DIRECTORY.match("Acme is unhappy").customers] == ["cus_acme"]


# ---- narrowing ------------------------------------------------------------------------


def test_a_project_narrows_each_source_and_a_customer_unions_its_projects() -> None:
    slack = DIRECTORY.filter_for("slack", None, "prj_f4")
    assert slack is not None and slack.channels == ["C0000000001"]
    jira = DIRECTORY.filter_for("jira", None, "prj_f4")
    assert (
        jira is not None
        and jira.jira_projects == ["HPF"]
        and jira.jira_labels == ["fund-iv"]
    )
    gmail = DIRECTORY.filter_for("gmail", None, "prj_f4")
    assert (
        gmail is not None
        and gmail.gmail_labels == ["fund-iv"]
        and gmail.gmail_domains == ["acme.test"]
    )
    whole = DIRECTORY.filter_for("slack", "cus_acme", None)
    assert whole is not None and set(whole.channels) == {"C0000000001", "C0000000002"}


def test_no_scope_means_no_filter_and_an_unmapped_source_gives_an_empty_one() -> None:
    assert DIRECTORY.filter_for("slack", None, None) is None
    unmapped = DIRECTORY.filter_for("slack", None, "prj_b")
    assert unmapped is not None and unmapped.is_empty()
    assert DIRECTORY.filter_for("jira", None, "unknown") is not None


# ---- tagging --------------------------------------------------------------------------


def test_records_are_tagged_from_where_they_live() -> None:
    assert DIRECTORY.classify("slack", channel="C0000000002") == ("cus_acme", "prj_f5")
    assert DIRECTORY.classify("jira", jira_key="HPF-9") == ("cus_acme", "prj_f4")
    assert DIRECTORY.classify("confluence", space="OPS") == ("cus_acme", "prj_f4")
    assert DIRECTORY.classify("gmail", emails=["maria@acme.test"]) == ("cus_acme", None)
    assert DIRECTORY.classify("gmail", emails=["x@nobody.test"]) == (None, None)
    assert DIRECTORY.classify("slack", channel="C9999999999") == (None, None)
    both = Directory(customers=[ACME, ACME.model_copy(update={"id": "cus_twin"})])
    assert both.classify("gmail", emails=["a@acme.test"]) == (
        None,
        None,
    )  # two owners: do not guess


def test_people_match_on_stable_ids_before_names() -> None:
    assert DIRECTORY.person_for(email="MARIA@acme.test") is MARIA
    assert DIRECTORY.person_for(slack_id="U1") is SAM
    assert DIRECTORY.person_for(jira_id="acc-1") is SAM
    assert DIRECTORY.person_for(name="sam  kim") is SAM
    twins = Directory(
        people=[SAM, SAM.model_copy(update={"id": "per_other", "emails": []})]
    )
    assert twins.person_for(name="Sam Kim") is None  # a shared name proves nothing
    assert twins.person_for(email="sam@us.test") is SAM


# ---- connectors use it ----------------------------------------------------------------


def scoped(**kw: Any) -> AccessContext:
    return AccessContext(
        user_id="u1",
        directory=DIRECTORY,
        scope=CaseScope(**kw),
        permitted_sources=frozenset({"x"}),
    )


async def test_jira_is_narrowed_tagged_and_authors_are_identified() -> None:
    net = jira_net()
    jira = JiraConnector(Tokens(), net.client)
    found = await jira.search(SearchQuery(text="form"), scoped(project_id="prj_f4"))
    jql = net.q()["jql"]
    assert "project in (HPF)" in jql and 'labels in ("fund-iv")' in jql
    (issue,) = found.records
    assert (issue.customer_id, issue.project_id) == ("cus_acme", "prj_f4")

    thread = await jira.get_thread("jira:HPF-19", scoped(project_id="prj_f4"))
    assert all(r.project_id == "prj_f4" for r in thread.records)
    refused = await jira.get_thread("jira:OTHER-1", scoped(project_id="prj_f4"))
    assert refused.coverage.status == "permission_denied"


async def test_a_project_with_nothing_mapped_for_a_source_says_it_was_not_narrowed() -> (
    None
):
    net = jira_net()
    found = await JiraConnector(Tokens(), net.client).search(
        SearchQuery(text="form"), scoped(project_id="prj_b")
    )
    assert "project in" not in net.q()["jql"]
    assert "not narrowed" in (found.coverage.detail or "")


async def test_the_servers_own_limit_still_applies_when_the_case_maps_wider() -> None:
    net = jira_net()
    jira = JiraConnector(Tokens(), net.client, project_keys="OTHER")
    found = await jira.search(SearchQuery(text="form"), scoped(project_id="prj_f4"))
    assert found.records == [] and "outside the Jira projects" in (
        found.coverage.detail or ""
    )
    assert not net.requests or "search/jql" not in str(net.requests[-1].url)


async def test_slack_reads_only_the_cases_channels() -> None:
    def msg(ch: str, ts: str, text: str) -> dict[str, Any]:
        return {
            "channel": {"id": ch, "name": "n"},
            "ts": ts,
            "text": text,
            "user": "U1",
        }

    net = slack_net(
        **{
            "search.messages": {
                "ok": True,
                "messages": {
                    "matches": [
                        msg("C0000000001", "1792087485.000100", "in scope"),
                        msg("C0000000002", "1792087486.000100", "other project"),
                    ],
                    "paging": {"page": 1, "pages": 1},
                },
            }
        }
    )
    net.routes["users.info"] = lambda r: httpx.Response(
        200, json={"ok": True, "user": {"id": "U1", "real_name": "Sam Kim"}}
    )
    slack = SlackConnector(Tokens(), net.client)
    found = await slack.search(SearchQuery(text="form"), scoped(project_id="prj_f4"))
    assert [r.excerpt for r in found.records] == ["in scope"]
    (r,) = found.records
    assert (r.project_id, r.author_side, r.author_role) == ("prj_f4", "internal", "CSM")
    out = await slack.get_thread(
        "slack:C0000000002:1792087100.000100", scoped(project_id="prj_f4")
    )
    assert (
        out.records == []
    )  # a channel of another project is not readable for this case


async def test_gmail_is_limited_to_the_cases_labels_or_customer_domains() -> None:
    net = gmail_net()
    found = await GmailConnector(Tokens(), net.client).search(
        SearchQuery(text="form"), scoped(project_id="prj_f4")
    )
    q = net.q(0)["q"]
    assert (
        'label:"fund-iv"' in q
        and "from:@acme.test" in q
        and "cc:@acme.test" in q
        and " OR " in q
    )
    first = found.records[0]
    assert (
        first.author_id == "maria@client.test"
    )  # the sender's address is kept for matching


async def test_gmail_senders_in_the_directory_are_marked_customer_or_internal() -> None:
    net = gmail_net()
    d = Directory(
        customers=[Customer(id="c", name="Client", email_domains=["client.test"])],
        people=[
            Person(
                id="p",
                name="Maria",
                emails=["maria@client.test"],
                side="customer",
                role="Client",
            )
        ],
    )
    ctx = AccessContext(user_id="u1", directory=d, permitted_sources=frozenset({"x"}))
    found = await GmailConnector(Tokens(), net.client).search(
        SearchQuery(text="form"), ctx
    )
    first = found.records[0]
    assert (first.author_side, first.author_role, first.customer_id) == (
        "customer",
        "Client",
        "c",
    )


async def test_confluence_search_is_limited_to_the_cases_spaces() -> None:
    from tests.test_connectors import confluence_net

    net = confluence_net()
    await ConfluenceConnector(Tokens(), net.client).search(
        SearchQuery(text="plan"), scoped(project_id="prj_f4")
    )
    assert 'space in ("OPS")' in net.q()["cql"]


async def test_suggestions_list_what_a_project_could_map_to_and_never_raise() -> None:
    net = slack_net(
        **{
            "users.conversations": {
                "ok": True,
                "channels": [{"id": "C0000000001", "name": "close"}],
            }
        }
    )
    status, options = await SlackConnector(Tokens(), net.client).suggestions(CTX)
    assert status == "ok" and options == [{"id": "C0000000001", "label": "#close"}]
    from investigator.integrations import NotConnectedError

    status, options = await SlackConnector(
        Tokens(NotConnectedError("Slack")), net.client
    ).suggestions(CTX)
    assert (status, options) == ("not_connected", [])
    down = Net(**{"api.atlassian.com": lambda r: httpx.Response(500)})
    assert (await JiraConnector(Tokens(), down.client).suggestions(CTX))[0] == "failed"


# ---- the graph uses it ----------------------------------------------------------------

START = {"question": "Why was the Fund IV form late?"}


def access_for(directory: Directory) -> Any:
    async def run(graph: Any, payload: Any, thread: str = "t") -> Any:
        config = {
            "configurable": {
                "thread_id": thread,
                "access": access("email", "chat"),
                "directory": directory,
            },
            "recursion_limit": 80,
        }
        await graph.ainvoke(payload, config=config)
        snap = await graph.aget_state(config)
        pending = [i.value for t in snap.tasks for i in t.interrupts]
        from investigator.agents.investigation import InvestigationState

        return InvestigationState(**snap.values), (pending[0] if pending else None)

    return run


async def test_a_question_naming_one_project_narrows_the_case_and_seeds_the_queries() -> (
    None
):
    llm = ScriptedLlm(structured=structured())
    run = access_for(DIRECTORY)
    mine = rec("e1", "email", project_id="prj_f4", occurred_at=NOW)
    other = rec("e2", "email", project_id="prj_f5", occurred_at=NOW)
    email = FakeConnector(
        "email", search=lambda q: result("email", "searched", [mine, other])
    )
    state, pending = await run(make_graph(llm, [email]), START)
    assert [e.id for e in state.evidence] == [
        "e1"
    ]  # the other project's record is dropped
    assert (state.context.project_id, state.context.customer_id) == (
        "prj_f4",
        "cus_acme",
    )
    assert state.scope_note and "Fund IV Close" in state.scope_note
    assert pending is not None and pending["kind"] == "review"


async def test_a_question_naming_two_projects_asks_before_searching() -> None:
    llm = ScriptedLlm(structured=structured())
    email = FakeConnector(
        "email",
        search=lambda q: result(
            "email", "searched", [rec("e1", "email", occurred_at=NOW)]
        ),
    )
    run = access_for(DIRECTORY)
    graph = make_graph(llm, [email])
    state, pending = await run(graph, {"question": "Compare Fund IV with Fund V"})
    assert pending is not None and pending["kind"] == "clarification"
    question = pending["questions"][0]
    assert question["key"] == "project_id" and set(question["options"]) == {
        "prj_f4",
        "prj_f5",
    }
    assert question["labels"]["prj_f4"] == "Fund IV Close"
    assert email.queries == []  # nothing was searched while the case was ambiguous
    assert llm.count(InvestigationPlan) == 0

    state, pending = await run(
        graph, Command(resume=ClarificationResume(project_id="prj_f5").model_dump())
    )
    assert (
        state.context.project_id == "prj_f5" and email.queries
    )  # now it searches, scoped


async def test_what_the_person_set_is_never_overridden_by_the_directory() -> None:
    llm = ScriptedLlm(structured=structured())
    run = access_for(DIRECTORY)
    state, _ = await run(
        make_graph(llm),
        {
            "question": "Why was the Fund IV form late?",
            "context": CaseContext(
                project_id="prj_b", customer_id="cus_beta"
            ).model_dump(),
        },
    )
    assert state.context.project_id == "prj_b" and state.scope_note is None


async def test_no_directory_leaves_the_case_exactly_as_asked() -> None:
    state, _ = await access_for(Directory())(
        make_graph(ScriptedLlm(structured=structured())), START
    )
    assert state.context.project_id is None and state.scope_note is None


async def test_records_from_two_projects_prompt_a_question_with_readable_names() -> (
    None
):
    a = rec("a", "email", project_id="prj_f4", occurred_at=NOW)
    b = rec("b", "email", project_id="prj_f5", occurred_at=NOW)
    email = FakeConnector("email", search=lambda q: result("email", "searched", [a, b]))
    run = access_for(Directory(customers=[ACME], projects=[P4, P5]))
    _, pending = await run(
        make_graph(ScriptedLlm(structured=structured()), [email]),
        {"question": "Why late?"},
    )
    assert pending is not None and pending["kind"] == "clarification"
    assert pending["questions"][0]["labels"] == {
        "prj_f4": "Fund IV Close",
        "prj_f5": "Fund V Close",
    }


# ---- HTTP -----------------------------------------------------------------------------


def api(directory: Directory | None = None) -> TestClient:
    return TestClient(
        create_app(
            AppState(
                store=MemoryStore(),
                graph=_NoGraph(),
                access=AccessContext(
                    user_id="local", permitted_sources=frozenset({"gmail", "slack"})
                ),
                directory=MemoryDirectoryStore(directory or Directory()),
            )
        )
    )


class _NoGraph:
    async def astream(self, *a: Any, **k: Any) -> Any:
        return
        yield


def test_the_directory_can_be_filled_edited_and_emptied() -> None:
    c = api()
    cust = c.post(
        "/directory/customers",
        json={
            "name": "Acme",
            "aliases": [" Acme Inc ", ""],
            "email_domains": ["acme.test"],
        },
    ).json()
    assert cust["id"].startswith("cus_")
    assert cust["aliases"] == ["Acme Inc"]  # trimmed, blanks dropped
    proj = c.post(
        "/directory/projects",
        json={
            "name": "Close",
            "customer_id": cust["id"],
            "slack_channel_ids": ["C0000000001"],
        },
    )
    assert proj.status_code == 201
    person = c.post(
        "/directory/people",
        json={
            "name": "Sam",
            "emails": ["sam@us.test"],
            "side": "internal",
            "role": "CSM",
            "customer_id": None,
        },
    )
    assert person.status_code == 201
    listing = c.get("/directory").json()
    assert [x["name"] for x in listing["customers"]] == ["Acme"] and len(
        listing["projects"]
    ) == 1

    renamed = c.put(
        f"/directory/projects/{proj.json()['id']}",
        json={"name": "Close 2", "customer_id": cust["id"]},
    )
    assert renamed.status_code == 200 and renamed.json()["name"] == "Close 2"
    assert c.put("/directory/projects/nope", json={"name": "x"}).status_code == 404

    assert (
        c.delete(f"/directory/customers/{cust['id']}").status_code == 409
    )  # still has a project
    assert c.delete(f"/directory/projects/{proj.json()['id']}").status_code == 204
    assert c.delete(f"/directory/customers/{cust['id']}").status_code == 204
    assert c.delete(f"/directory/customers/{cust['id']}").status_code == 404


def test_the_directory_rejects_links_to_nothing_and_unknown_collections() -> None:
    c = api()
    assert (
        c.post(
            "/directory/projects", json={"name": "P", "customer_id": "cus_missing"}
        ).status_code
        == 422
    )
    assert c.post("/directory/customers", json={"name": ""}).status_code == 422
    assert c.post("/directory/things", json={"name": "x"}).status_code == 404


def test_cases_must_name_customers_and_projects_the_directory_knows() -> None:
    c = api(DIRECTORY)

    def post(**b: Any) -> Any:
        return c.post("/investigations", json={"question": "q", **b})

    assert post(project_id="prj_f4").status_code == 202
    assert post(customer_id="cus_acme", project_id="prj_f4").status_code == 202
    assert post(project_id="nope").status_code == 422
    assert post(customer_id="nope").status_code == 422
    assert (
        "different customer"
        in post(customer_id="cus_beta", project_id="prj_f4").json()["detail"]
    )
    # an empty directory accepts what it is given (nothing to check it against)
    assert (
        api()
        .post("/investigations", json={"question": "q", "project_id": "anything"})
        .status_code
        == 202
    )


async def test_listing_channels_falls_back_to_public_ones_when_the_scope_is_missing() -> (
    None
):
    def conversations(request: httpx.Request) -> httpx.Response:
        if "private_channel" in request.url.params["types"]:
            return httpx.Response(200, json={"ok": False, "error": "missing_scope"})
        return httpx.Response(
            200, json={"ok": True, "channels": [{"id": "C0000000001", "name": "open"}]}
        )

    net = slack_net(**{"users.conversations": conversations})
    status, options = await SlackConnector(Tokens(), net.client).suggestions(CTX)
    assert status == "ok" and options == [{"id": "C0000000001", "label": "#open"}]


async def test_the_planner_is_given_names_never_internal_ids() -> None:
    llm = ScriptedLlm(structured=structured())
    seen: list[str] = []
    original = llm.complete_structured

    async def spy(messages: Any, schema: type, route: str = "fast", **kw: Any) -> Any:
        if schema is InvestigationPlan:
            seen.append("\n".join(str(m.content) for m in messages))
        return await original(messages, schema, route, **kw)

    llm.complete_structured = spy  # type: ignore[method-assign]
    await access_for(DIRECTORY)(make_graph(llm), START)
    prompt = seen[0]
    assert "Fund IV Close" in prompt and "Acme Fund" in prompt and "HPF-" in prompt
    assert "prj_f4" not in prompt and "cus_acme" not in prompt


# ---- asking where to look --------------------------------------------------------------


class _Listing(FakeConnector):
    """A source that can list its channels, as Slack does."""

    async def suggestions(self, ctx: Any) -> tuple[str, list[dict[str, str]]]:
        return "ok", [
            {"id": "C1", "label": "#cs-meridian"},
            {"id": "C2", "label": "#random"},
        ]


def _scoped_run(directory: Directory) -> Any:
    async def run(graph: Any, payload: Any) -> Any:
        config = {
            "configurable": {
                "thread_id": "s",
                "access": access("slack", "chat"),
                "directory": directory,
            },
            "recursion_limit": 80,
        }
        await graph.ainvoke(payload, config=config)
        snap = await graph.aget_state(config)
        pending = [i.value for t in snap.tasks for i in t.interrupts]
        from investigator.agents.investigation import InvestigationState

        return InvestigationState(**snap.values), (pending[0] if pending else None)

    return run


async def test_an_unscoped_case_asks_where_to_look_before_searching() -> None:
    slack = _Listing(
        "slack",
        search=lambda q: result(
            "slack", "searched", [rec("s1", "slack", occurred_at=NOW)]
        ),
    )
    graph = make_graph(ScriptedLlm(structured=structured()), [slack])
    run = _scoped_run(Directory())
    _, pending = await run(graph, {"question": "What happened with the KYC backlog?"})
    assert pending is not None and pending["kind"] == "clarification"
    q = pending["questions"][0]
    assert (q["key"], q["source"], q["multi"]) == ("source_scope", "slack", True)
    assert q["labels"]["C1"] == "#cs-meridian"
    assert slack.queries == []  # nothing was read while the place was undecided

    state, _ = await run(
        graph, Command(resume=ClarificationResume(scope={"slack": ["C1"]}).model_dump())
    )
    assert state.context.source_filters["slack"].channels == ["C1"]
    assert slack.queries


async def test_choosing_all_of_a_source_is_a_decision_and_is_not_asked_again() -> None:
    slack = _Listing(
        "slack",
        search=lambda q: result(
            "slack", "searched", [rec("s1", "slack", occurred_at=NOW)]
        ),
    )
    graph = make_graph(ScriptedLlm(structured=structured()), [slack])
    run = _scoped_run(Directory())
    await run(graph, {"question": "What happened?"})
    state, pending = await run(
        graph, Command(resume=ClarificationResume(scope={"slack": []}).model_dump())
    )
    assert state.context.source_filters["slack"].is_empty()
    assert pending is None or pending["kind"] != "clarification"
    assert slack.queries


async def test_a_case_the_directory_already_narrows_is_not_asked() -> None:
    mapped = Directory(
        customers=[ACME],
        projects=[
            Project(
                id="prj_x",
                name="Fund X Close",
                customer_id="cus_acme",
                slack_channel_ids=["C1"],
            )
        ],
    )
    slack = _Listing(
        "slack",
        search=lambda q: result(
            "slack", "searched", [rec("s1", "slack", occurred_at=NOW)]
        ),
    )
    _, pending = await _scoped_run(mapped)(
        make_graph(ScriptedLlm(structured=structured()), [slack]),
        {"question": "Why was Fund X Close late?"},
    )
    assert pending is None or pending["kind"] != "clarification"
    assert slack.queries
