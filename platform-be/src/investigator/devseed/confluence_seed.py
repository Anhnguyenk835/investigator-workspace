"""More Confluence pages for the seeded world, written from the story facts like the Notion ones.

The first seed puts only a handful of pages in Confluence (one incident record per story that
has one). This adds the rest of a team's wiki: per-customer briefs, root-cause write-ups,
meeting notes and trackers, and the general runbooks and policies. A model writes the words from
the story facts; nothing here invents a date or a promise. Pages are plain markdown in
`seed-confluence.json`, shared by the live writer below and by the demo export.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from investigator.devseed.notion_seed import GENERAL_TOPICS, PageDraft, write_pages
from investigator.devseed.post import Poster

SPACE_KEY = "SEEDKB"
SPACE_NAME = "Customer Success Knowledge Base"

STORY_KINDS = [
    (
        "Escalation brief",
        "a one-page brief for whoever picks the case up: what the customer reported, impact, current state, owners, next dates",
    ),
    (
        "Root cause analysis",
        "what failed and why, how it was detected, what was contained and fixed; blameless, factual, with open questions marked 'not recorded'",
    ),
    (
        "Customer call notes",
        "notes from a call with the customer during the issue: attendees, what was said, asks, owners, dates already committed",
    ),
    (
        "Commitments tracker",
        "a list of everything promised to the customer: who promised, to whom, due date, whether it was kept, as far as the facts say",
    ),
    (
        "Lessons learned",
        "a short retrospective: what went well, what did not, follow-ups with owners",
    ),
]

# Topics that differ from the Notion handbook so the two sources are not copies of each other.
EXTRA_TOPICS = [
    (
        "Incident communication templates",
        "wording to use at detection, update and resolution; what never to promise",
    ),
    (
        "Escalation handoff checklist",
        "what a hand-off between CS, Support and Engineering must contain",
    ),
    (
        "Investor onboarding FAQ",
        "answers to the questions fund managers ask in the first weeks",
    ),
    (
        "SLA breach handling",
        "how a breach is confirmed, who is told, and what the customer is owed, without inventing figures",
    ),
]


async def write(
    llm: Any, stories: list[Any], world: Any, *, workers: int = 4
) -> dict[str, list[PageDraft]]:
    return await write_pages(
        llm,
        stories,
        world,
        workers=workers,
        story_kinds=STORY_KINDS,
        topics=[*GENERAL_TOPICS, *EXTRA_TOPICS],
    )


def unique_titles(groups: dict[str, list[dict[str, str]]]) -> list[tuple[str, str]]:
    """(title, markdown) for every page; Confluence needs a title that is unique in its space."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for pages in groups.values():
        for p in pages:
            title, n = p["title"].strip()[:250], 2
            while title.lower() in seen:
                title = f"{p['title'].strip()[:240]} ({n})"
                n += 1
            seen.add(title.lower())
            out.append((title, p["markdown"]))
    return out


class ConfluenceWriter:
    """Creates pages in the seed space through the Atlassian site's own API (basic auth)."""

    def __init__(
        self, base_url: str, email: str, token: str, *, dry: bool = False
    ) -> None:
        self.dry = dry
        self.created = 0
        self.space_id = "0"
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), auth=(email, token), timeout=60
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        for _ in range(6):
            r = self._http.request(method, path, **kw)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After", "3")) + 0.5)
                continue
            return r
        raise RuntimeError("Confluence kept rate-limiting")

    def existing_titles(self) -> set[str]:
        titles: set[str] = set()
        path = f"/wiki/api/v2/spaces/{self.space_id}/pages?limit=250"
        while path:
            r = self._call("GET", path)
            if r.status_code != 200:
                raise RuntimeError(f"list pages: {r.status_code} {r.text[:200]}")
            body = r.json()
            titles |= {str(p["title"]).lower() for p in body.get("results", [])}
            nxt = (body.get("_links") or {}).get("next")
            path = nxt if nxt else ""
        return titles

    def ensure_space(self) -> None:
        if self.dry:
            return
        r = self._call("GET", "/wiki/api/v2/spaces", params={"keys": SPACE_KEY})
        found = r.json().get("results", []) if r.status_code == 200 else []
        if not found:
            raise RuntimeError(
                f"The {SPACE_KEY} space does not exist. Run `post --only confluence` once first."
            )
        self.space_id = str(found[0]["id"])

    def create(self, title: str, markdown: str) -> None:
        if not self.dry:
            r = self._call(
                "POST",
                "/wiki/api/v2/pages",
                json={
                    "spaceId": self.space_id,
                    "status": "current",
                    "title": title,
                    "body": {
                        "representation": "storage",
                        "value": Poster.storage(markdown),
                    },
                },
            )
            if r.status_code not in (200, 201):
                raise RuntimeError(
                    f"create page '{title}': {r.status_code} {r.text[:200]}"
                )
            time.sleep(0.4)
        self.created += 1
