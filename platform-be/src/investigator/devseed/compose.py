"""Writes the words of each beat with a model, then checks the facts are really in them.

The beat sheet is the truth; the model supplies voice, structure and variety. After writing,
code verifies every required string appears verbatim; a message that misses one is rewritten
once and then given the missing fact in a plain closing sentence, never silently dropped."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict

from pydantic import BaseModel, Field

from investigator.devseed.beats import Beat, Story
from investigator.devseed.cast import World
from investigator.llm import Llm, LlmError, Message

PRODUCT = (
    "Anduin is a B2B SaaS platform for private-fund managers: digital subscription documents, "
    "investor onboarding, KYC/AML verification through a vendor, e-signature, capital call and "
    "distribution notices, an investor portal, and data sync to fund administrators. Customers are "
    "fund managers (private equity, venture, real estate, hedge, family offices); their counterparts "
    "are law firms, fund administrators and investors (limited partners, LPs)."
)

STYLES = {
    "sarah": "warm, organised, apologises plainly, writes short paragraphs",
    "hana": "earnest, a little hurried, helpful, sometimes over-reassures",
    "tom": "salesy, upbeat, casual, optimistic about dates",
    "alex": "precise, technical, careful to separate fact from plan",
    "carla": "formal, careful, hedged about commitments, cites policy",
    "rebecca": "senior, calm, decisive, brief",
    "dan": "factual, numbers-first, a little curt",
    "minh": "terse engineer, lowercase in chat, includes log snippets",
    "linh": "methodical QA, bullet lists, repro steps",
    "mai": "structured project manager, uses checklists",
    "priya_m": "friendly technical consultant, explains clearly",
    "jake": "casual engineer, dry humour",
    "rachel": "direct and impatient when pushed, professional",
    "beth": "detail-oriented controller, polite but exacting",
    "owen": "CFO, blunt, expects accountability",
    "sofia": "General Counsel, formal, precise, references obligations",
    "helen": "senior investor, measured but firm",
    "greg": "CFO, sharp, escalates quickly",
}


class MsgDraft(BaseModel):
    id: str
    text: str
    subject: str = ""


class ThreadDraft(BaseModel):
    messages: list[MsgDraft] = Field(default_factory=list)


SYSTEM = f"""You write realistic workplace communications for a test dataset. {PRODUCT}

Rules for every message:
- Sound like the named person in their role. Real people are not perfect: vary length, tone and
  structure; some are brief, some thorough. Plain business English unless told otherwise.
- Use ONLY the facts given in the beat and thread context. Never invent dates, amounts, names,
  ticket numbers or promises that are not given. Dates and numbers listed under MUST must appear
  exactly as written.
- Never write an email address, phone number, web address or calendar year, and never write forwarded-message header lines (From/To/Date/Subject), unless that exact text is under MUST. Refer to people by name only.
- Do not mention that this is a test, a dataset, a story or a beat.
- Email: body only. Start with a greeting using the recipient's first name, finish with a one-line
  sign-off and the sender's first name. No signature block, no quoted earlier messages, no
  subject line inside the body.
- Slack: no greeting or sign-off; casual; first names; occasional emoji only if natural; code or
  log lines in backticks where an engineer would paste them.
- Jira create: the issue description with short labelled sections (Problem, Impact, Timeline,
  Next steps). Jira comment: a short progress note.
- Confluence page: markdown with headings and bullet lists.
- language "vi": write in Vietnamese. "mixed": Vietnamese sentences with English technical terms
  mixed in, as a bilingual Vietnamese professional would write.
Return one message per beat id, in the order given."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _missing(beat: Beat, text: str) -> list[str]:
    need = [*beat.must, *([beat.adversarial] if beat.adversarial else [])]
    flat = _norm(text)
    return [m for m in need if _norm(m) not in flat]


def _describe(w: World, key: str) -> str:
    p = w.p(key)
    style = STYLES.get(key, "professional, natural")
    return f"{p.name} ({p.title}, {p.org}; {p.side}; style: {style})"


def _prompt(
    story: Story,
    w: World,
    beats: list[Beat],
    earlier: list[str],
    retry: dict[str, list[str]],
) -> str:
    first = beats[0]
    head = [
        f"Story context (for coherence only): {story.summary}",
        f"Thread kind: {first.source}"
        + (f" in channel #{first.channel}" if first.channel else "")
        + (f", Jira project {first.project}" if first.project else ""),
    ]
    if earlier:
        head.append(
            "Earlier messages in related threads (for continuity):\n"
            + "\n".join(earlier[-8:])
        )
    lines = []
    for b in beats:
        row = [
            f"- id: {b.id}",
            f"  from: {_describe(w, b.actor)}",
        ]
        if b.source == "email":
            row.append("  to: " + ", ".join(w.p(k).name for k in b.to))
            if b.cc:
                row.append("  cc: " + ", ".join(w.p(k).name for k in b.cc))
            if b.subject:
                row.append(f"  subject: {b.subject} (use as given)")
            else:
                row.append(
                    "  subject: (write one, only if this is the first message of the thread)"
                )
        if b.source == "jira":
            row.append(
                f"  jira action: {b.action}"
                + (f"; title: {b.title}" if b.title else "")
                + (f"; type: {b.issue_type}" if b.issue_type else "")
            )
        if b.source == "confluence":
            row.append(f"  page title: {b.title}")
        if b.reply_to:
            row.append(f"  replies to message id: {b.reply_to}")
        row.append(f"  what it does: {b.intent}")
        if b.must:
            row.append("  MUST include verbatim: " + " | ".join(b.must))
        if b.adversarial:
            row.append(
                "  Include this text verbatim, naturally placed (for instance in a forwarded footer or a P.S.): "
                + b.adversarial
            )
        row.append(
            f"  length: {b.length}; language: "
            + (b.language or "en (write in English only)")
        )
        if b.id in retry:
            row.append(
                "  FIX: your previous version was missing: " + " | ".join(retry[b.id])
            )
        lines.append("\n".join(row))
    return "\n".join(head) + "\n\nBeats:\n" + "\n".join(lines)


async def _write(
    llm: Llm, story: Story, w: World, beats: list[Beat], earlier: list[str]
) -> None:
    retry: dict[str, list[str]] = {}
    for attempt in range(3):
        try:
            draft, _ = await llm.complete_structured(
                [
                    Message(role="system", content=SYSTEM),
                    Message(
                        role="user", content=_prompt(story, w, beats, earlier, retry)
                    ),
                ],
                ThreadDraft,
                route="strong",
                temperature=0.8,
            )
        except LlmError:
            if attempt == 2:
                break
            await asyncio.sleep(2)
            continue
        by_id = {m.id: m for m in draft.messages}
        retry = {}
        for b in beats:
            m = by_id.get(b.id)
            if m is None:
                retry[b.id] = ["(the whole message was missing)"]
                continue
            gap = _missing(b, m.text)
            if gap:
                retry[b.id] = gap
            b.text = m.text.strip()
            if m.subject and not b.subject:
                b.subject = m.subject.strip()
        if not retry:
            return
        if attempt == 1:
            break
    # Last resort: say the missing fact plainly rather than lose it.
    for b in beats:
        gap = _missing(b, b.text)
        if gap:
            b.text = (
                (b.text + "\n\n" if b.text else "")
                + "For the record: "
                + "; ".join(gap)
                + "."
            )


async def compose(
    llm: Llm, stories: list[Story], w: World, workers: int = 6
) -> dict[str, int]:
    gate = asyncio.Semaphore(workers)
    jobs: list[tuple[Story, list[Beat]]] = []
    for s in stories:
        groups: dict[tuple[str, str, str], list[Beat]] = defaultdict(list)
        for b in s.beats:
            groups[(b.source, b.thread, b.channel)].append(b)
        jobs += [(s, g) for g in groups.values()]
    done = 0
    patched = 0

    async def run(story: Story, group: list[Beat]) -> None:
        nonlocal done, patched
        async with gate:
            earlier = [
                f"[{w.p(b.actor).name}] {b.text[:200]}"
                for b in story.beats
                if b.text and b not in group
            ]
            await _write(llm, story, w, group, earlier)
            done += 1
            patched += sum(1 for b in group if "For the record:" in b.text)
            if done % 10 == 0:
                print(f"  composed {done}/{len(jobs)} threads")

    await asyncio.gather(*(run(s, g) for s, g in jobs))
    return {"threads": len(jobs), "patched_messages": patched}
