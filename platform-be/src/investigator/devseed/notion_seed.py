"""Notion pages for the seeded world: call notes, hand-offs, reviews and the team's runbooks.

The story facts are the truth. A model writes the pages from them (voice, structure, variety);
nothing here invents a date or a promise. Titles carry the customer and the topic, because
Notion's search matches titles only.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from investigator.devseed.beats import Story
from investigator.devseed.cast import World
from investigator.devseed.compose import PRODUCT
from investigator.llm import Llm, LlmError, Message

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
ROOT_TITLE = "Investigator"
# Where the general pages are filed: folder -> words in the title.
FOLDERS = {
    "Runbooks and playbooks": ("runbook", "playbook", "process", "guide"),
    "Policies and service levels": (
        "policy",
        "service levels",
        "guidelines",
        "security",
    ),
    "Meetings and planning": ("sync", "renewals", "release", "checklist"),
}


def folder_of(title: str) -> str:
    low = title.lower()
    return next(
        (f for f, words in FOLDERS.items() if any(w in low for w in words)),
        "Team handbook",
    )


MAX_TEXT = 1900  # Notion limits one rich-text run to 2000 characters
MAX_CHILDREN = 100  # and one request to 100 blocks

STORY_KINDS = [
    (
        "Call notes",
        "notes from a customer call during the issue: attendees, what was said, asks, owners, dates",
    ),
    (
        "Internal hand-off",
        "an internal note handing the case to another person: state, open items, risks, who to ask",
    ),
    (
        "Review",
        "a short internal review of what happened and what was learned; blameless, factual, with open questions",
    ),
    (
        "Success plan",
        "the customer success plan for the next weeks: goals, owners, checkpoints, dates already committed",
    ),
]

GENERAL_TOPICS = [
    (
        "KYC verification runbook",
        "how investor verification works, the vendor hand-off, what to check when LPs are stuck in pending",
    ),
    (
        "Escalation policy and severity levels",
        "severity levels, who to page, response targets, customer communication rules",
    ),
    (
        "Service levels by plan",
        "a table-like list of what each plan promises: verification, support response, uptime",
    ),
    (
        "Customer onboarding checklist",
        "a checklist (to-do items) for onboarding a new fund manager",
    ),
    (
        "Webhook incident playbook",
        "what to do when vendor callbacks fail: detection, rollback, comms, follow-up",
    ),
    (
        "Capital call notice process",
        "steps to prepare, approve and send capital call notices; common errors",
    ),
    (
        "Data room permissions guide",
        "how permissions are granted to LPs, counsel and administrators; common mistakes",
    ),
    (
        "Release notes, last quarter",
        "five or six dated product changes customers asked about",
    ),
    (
        "Weekly CS sync, notes",
        "four weekly meeting notes with decisions and action items across several accounts",
    ),
    (
        "Renewals calendar",
        "which accounts renew in which month, owners, risks, without inventing contract values",
    ),
    (
        "Support reply guidelines",
        "tone, what never to promise without Engineering, how to quote dates",
    ),
    (
        "Security questionnaire answers",
        "reusable answers: encryption, access control, data residency, sub-processors, incident notice",
    ),
]


class PageDraft(BaseModel):
    title: str
    markdown: str


class PageSet(BaseModel):
    pages: list[PageDraft] = Field(default_factory=list)


SYSTEM = f"""You write internal wiki pages for a test dataset. {PRODUCT}

Rules:
- Markdown only: '#', '##' headings, '-' bullets, '1.' numbered items, '- [ ]' / '- [x]' to-dos, plain paragraphs.
- Use ONLY the facts given. Never invent dates, amounts, ticket numbers, customer names or promises
  that are not given. Where a detail is unknown write 'not recorded'.
- Never write an email address, phone number or web address. Refer to people by name.
- Real pages are uneven: some are short, some thorough; people abbreviate and leave small TODOs.
- Do not mention a dataset, test, story or beat.
- Every title starts with the customer or the topic so a title search finds it."""


def _story_prompt(story: Story, w: World) -> str:
    org = w.orgs[story.customer].name
    facts = "\n".join(
        f"- [{f.kind}] {f.statement}"
        + (f" (due {f.due}, kept: {f.met})" if f.due else "")
        for f in story.facts
    )
    excerpts = "\n".join(
        f"- {w.p(b.actor).name} ({b.source}): {b.text[:350].strip()}"
        for b in story.beats
        if b.text
    )[:6000]
    kinds = "\n".join(f"{i + 1}. {k}: {d}" for i, (k, d) in enumerate(STORY_KINDS))
    return (
        f"Customer: {org}\nCase: {story.title}\nSummary: {story.summary}\n\nGround truth:\n{facts}\n\n"
        f"What was said in mail, chat and tickets (for continuity):\n{excerpts}\n\n"
        f"Write {len(STORY_KINDS)} pages, in this order, each titled '{org} - <topic>: <kind>':\n{kinds}"
    )


def _general_prompt(topics: list[tuple[str, str]]) -> str:
    rows = "\n".join(f"{i + 1}. {t}: {d}" for i, (t, d) in enumerate(topics))
    return f"Write one page per topic, titled with the topic:\n{rows}"


async def _ask(llm: Llm, prompt: str, want: int) -> list[PageDraft]:
    for attempt in range(3):
        try:
            got, _ = await llm.complete_structured(
                [
                    Message(role="system", content=SYSTEM),
                    Message(role="user", content=prompt),
                ],
                PageSet,
                route="strong",
                temperature=0.8,
            )
        except LlmError:
            await asyncio.sleep(2)
            continue
        pages = [p for p in got.pages if p.title.strip() and p.markdown.strip()]
        if len(pages) >= want or attempt == 2:
            return pages
    return []


async def write_pages(
    llm: Llm, stories: list[Story], w: World, *, workers: int = 4
) -> dict[str, list[PageDraft]]:
    """Pages grouped under the customer they are about; '' holds the general ones."""
    gate = asyncio.Semaphore(workers)
    out: dict[str, list[PageDraft]] = {}

    async def story(s: Story) -> None:
        async with gate:
            pages = await _ask(llm, _story_prompt(s, w), len(STORY_KINDS))
        org = w.orgs[s.customer].name
        if len(pages) == len(
            STORY_KINDS
        ):  # the titles are ours, so a title search is reliable
            for page, (kind, _) in zip(pages, STORY_KINDS, strict=True):
                page.title = f"{org} - {s.title}: {kind}"
        out.setdefault(org, []).extend(pages)

    async def general(chunk: list[tuple[str, str]]) -> None:
        async with gate:
            pages = await _ask(llm, _general_prompt(chunk), len(chunk))
        out.setdefault("", []).extend(pages)

    chunks = [GENERAL_TOPICS[i : i + 3] for i in range(0, len(GENERAL_TOPICS), 3)]
    await asyncio.gather(
        *[story(s) for s in stories if s.facts], *[general(c) for c in chunks]
    )
    return out


# ---- markdown -> Notion blocks -------------------------------------------------------


def _runs(text: str) -> list[dict[str, Any]]:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("`", "")
    return [
        {"type": "text", "text": {"content": text[i : i + MAX_TEXT]}}
        for i in range(0, max(len(text), 1), MAX_TEXT)
    ]


def _block(kind: str, text: str, **extra: Any) -> dict[str, Any]:
    return {"object": "block", "type": kind, kind: {"rich_text": _runs(text), **extra}}


def blocks(markdown: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        s = line.strip()
        if m := re.match(r"^(#{1,3})\s+(.*)", s):
            out.append(_block(f"heading_{len(m.group(1))}", m.group(2)))
        elif m := re.match(r"^[-*]\s+\[( |x|X)\]\s+(.*)", s):
            out.append(_block("to_do", m.group(2), checked=m.group(1).lower() == "x"))
        elif m := re.match(r"^[-*•]\s+(.*)", s):
            out.append(_block("bulleted_list_item", m.group(1)))
        elif m := re.match(r"^\d+[.)]\s+(.*)", s):
            out.append(_block("numbered_list_item", m.group(1)))
        elif set(s) <= {"-", "_", "*"} and len(s) >= 3:
            out.append({"object": "block", "type": "divider", "divider": {}})
        else:
            out.append(_block("paragraph", s))
    return out or [_block("paragraph", "(empty)")]


# ---- writing to Notion --------------------------------------------------------------


def page_id(value: str) -> str:
    """A page id from an id or a notion.so link."""
    m = re.search(
        r"([0-9a-fA-F]{32})(?:\?|$|/)|([0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12})",
        value,
    )
    if not m:
        raise ValueError(f"No Notion page id in {value!r}.")
    return m.group(1) or m.group(2)


class NotionWriter:
    def __init__(self, token: str, *, dry: bool = False) -> None:
        self.dry = dry
        self.created: list[str] = []
        self._http = httpx.Client(
            base_url=API,
            headers={"Authorization": f"Bearer {token}", "Notion-Version": VERSION},
            timeout=60,
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        for _ in range(6):
            r = self._http.request(method, path, **kw)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", "2")))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
            time.sleep(0.35)  # Notion allows about 3 requests a second
            return r.json()  # type: ignore[no-any-return]
        raise RuntimeError(f"{method} {path}: rate limited")

    def first_page(self) -> str:
        """Some page the person shared with the connection, to hang the seed under."""
        data = self._call(
            "POST",
            "/search",
            json={"filter": {"property": "object", "value": "page"}, "page_size": 20},
        )
        pages = [o for o in data.get("results", []) if not o.get("archived")]
        top = [o for o in pages if (o.get("parent") or {}).get("type") == "workspace"]
        for o in top or pages:
            return str(o["id"])
        raise RuntimeError(
            "No page is shared with the connection. Reconnect Notion and tick a page on the consent screen."
        )

    def create(self, parent: str, title: str, markdown: str = "") -> str:
        if self.dry:
            self.created.append(f"dry-{len(self.created)}")
            return self.created[-1]
        children = blocks(markdown) if markdown else []
        made = self._call(
            "POST",
            "/pages",
            json={
                "parent": {"page_id": parent},
                "properties": {"title": {"title": _runs(title[:200])}},
                "children": children[:MAX_CHILDREN],
            },
        )
        pid = str(made["id"])
        self.created.append(pid)
        for i in range(MAX_CHILDREN, len(children), MAX_CHILDREN):
            self._call(
                "PATCH",
                f"/blocks/{pid}/children",
                json={"children": children[i : i + MAX_CHILDREN]},
            )
        return pid

    def archive(self, pid: str) -> None:
        self._call("PATCH", f"/pages/{pid}", json={"archived": True})
