"""Everything else a real mailbox, workspace and tracker hold: routine customer mail,
newsletters, internal chatter and unrelated tickets. An investigation has to find the signal
among this, and must not mistake it for the signal."""

from __future__ import annotations

from investigator.devseed.beats import Beat, Story
from investigator.devseed.cast import Org, Person
from investigator.devseed.ctx import Ctx

ROUTINE = [
    (
        "Scheduling a quarterly business review",
        "Proposes two time slots for the quarterly business review and asks for an agenda.",
    ),
    (
        "Monthly platform usage summary",
        "Shares last month's usage summary: investors invited, onboarded, documents executed; no action needed.",
    ),
    (
        "Training session for new team member",
        "Asks for a 45-minute training for a new analyst on the investor portal admin.",
    ),
    (
        "Add a user to the admin console",
        "Asks to add a colleague as an admin; includes their name and role.",
    ),
    (
        "Question about exporting the investor register",
        "Asks how to export the investor register to Excel with commitment columns.",
    ),
    (
        "Updated wire instructions on file",
        "Informs of a change of the operating account's bank for the next quarter and asks how to update it securely, without including account numbers.",
    ),
    (
        "Holiday coverage",
        "Tells the team who covers support during the holiday week and asks for the escalation contact.",
    ),
    (
        "Feature request: reminder emails",
        "Requests configurable reminder emails for unsigned subscription documents.",
    ),
]
VENDORS = [
    ("Calendly", "calendly", "A scheduling-tool product update newsletter."),
    (
        "RegWatch Weekly",
        "regwatch",
        "A weekly digest of securities regulation changes relevant to private fund managers.",
    ),
    (
        "Delaney & Co. Client Alert",
        "delaney",
        "A law firm client alert about a recent change to the marketing rule for private funds.",
    ),
    (
        "AWS Notifications",
        "awsnotice",
        "An automated notice about a scheduled maintenance window for a storage service.",
    ),
    (
        "Fund Ops Forum",
        "fundops",
        "An invitation to a webinar on investor onboarding and KYC best practices.",
    ),
    ("Okta", "oktanews", "A security bulletin about a new admin console feature."),
    ("DocuSign Admin", "dsadmin", "A billing reminder for an add-on seat license."),
    (
        "PrivateEquity Wire",
        "pewire",
        "A news digest: fundraising totals and two interview headlines.",
    ),
]
CHATTER = [
    (
        "general",
        "A short post welcoming a new colleague on the team and asking people to say hi.",
    ),
    (
        "general",
        "Reminder about the office hours change next week and a lunch suggestion thread with a few replies.",
    ),
    (
        "deploys",
        "Release notice: production deploy of the web app with a short change list, and a rollback note that wasn't needed.",
    ),
    (
        "deploys",
        "A deploy froze for 12 minutes because of a CI queue; engineers discuss and move on.",
    ),
    (
        "eng-oncall",
        "On-call handoff note from one engineer to the next, listing two open alerts and one flaky test.",
    ),
    (
        "eng-oncall",
        "An alert about elevated latency on the document-generation service, quickly acknowledged and resolved.",
    ),
    (
        "cs-escalations",
        "CSM asks whether anyone has seen a duplicate-email issue in notifications; two people say no.",
    ),
    (
        "cs-escalations",
        "Weekly review of open escalations: counts only, no customer names, owners listed.",
    ),
]
JIRA_NOISE = [
    (
        "ENG",
        "Bug",
        "Date picker shows wrong month on Safari 17",
        "A cosmetic bug in the admin console date picker.",
    ),
    (
        "ENG",
        "Story",
        "Upgrade PDF rendering library to latest minor",
        "A routine dependency upgrade with a test plan.",
    ),
    (
        "ENG",
        "Bug",
        "Typos in German email notification template",
        "Wrong words in a template; trivial fix.",
    ),
    (
        "ENG",
        "Story",
        "Add audit log export to CSV",
        "Feature: export the audit log for a date range.",
    ),
    (
        "CSE",
        "Task",
        "Prepare Q4 customer health review deck",
        "Internal task to prepare the quarterly deck.",
    ),
    (
        "CSE",
        "Task",
        "Update support macros for KYC status explanations",
        "Update canned replies for KYC statuses.",
    ),
    (
        "ENG",
        "Bug",
        "Intermittent 502 on investor portal login",
        "Rare 502 responses on login; traced to a load balancer setting.",
    ),
    (
        "CSE",
        "Task",
        "Draft customer-facing release notes for October",
        "Drafting the monthly release notes.",
    ),
]


def noise(c: Ctx) -> list[Story]:
    stories: list[Story] = []
    rng = c.rng
    cust = [o for o in c.w.orgs.values() if o.kind == "customer"]
    internal = [p for p in c.w.people.values() if p.side == "internal"]
    client_by_org: dict[str, list[Person]] = {}
    for p in c.w.people.values():
        if p.side == "customer":
            client_by_org.setdefault(p.org, []).append(p)

    beats: list[Beat] = []
    n = 0
    for org in cust:
        clients = client_by_org.get(org.name, [])
        if not clients:
            continue
        for subject, intent in rng.sample(ROUTINE, 7):
            n += 1
            who = rng.choice(clients)
            csm = rng.choice(
                [p for p in internal if p.role in ("csm", "support", "implementation")]
            )
            first = rng.uniform(3, 45)
            beats.append(
                Beat(
                    f"n{n}a",
                    "email",
                    f"n{n}",
                    who.key,
                    f"{intent}",
                    day=first,
                    to=[csm.key],
                    subject=subject,
                    length="short",
                )
            )
            if rng.random() < 0.8:
                beats.append(
                    Beat(
                        f"n{n}b",
                        "email",
                        f"n{n}",
                        csm.key,
                        "Replies helpfully and briefly, resolving or scheduling it.",
                        day=max(first - rng.uniform(0.1, 1.5), 0.2),
                        to=[who.key],
                        reply_to=f"n{n}a",
                        length="short",
                        quote=rng.random() < 0.5,
                    )
                )
    # newsletters from outside senders
    extra: dict[str, Person] = {}
    for name, key, intent in VENDORS:
        dom = f"{key}.example"
        extra[key] = Person(
            f"nl_{key}", name, f"news@{dom}", name, "", "third_party", "vendor"
        )
        for i in range(rng.randint(1, 3)):
            n += 1
            beats.append(
                Beat(
                    f"n{n}",
                    "email",
                    f"n{n}",
                    f"nl_{key}",
                    intent,
                    day=rng.uniform(1, 48),
                    to=[rng.choice(internal).key],
                    subject="",
                    length="medium",
                )
            )
    for p in extra.values():
        c.w.people[p.key] = p
    stories.append(
        Story("noise-email", "meridian", "Routine mail", "Noise", "", 48, [], beats, [])
    )

    chat: list[Beat] = []
    for i, (ch, intent) in enumerate(CHATTER * 3):
        crew = rng.sample(internal, 3)
        chat.append(
            Beat(
                f"nc{i}a",
                "slack",
                f"nc{i}",
                crew[0].key,
                intent,
                channel=ch,
                length="short",
            )
        )
        for j, w in enumerate(crew[1:]):
            chat.append(
                Beat(
                    f"nc{i}{j}",
                    "slack",
                    f"nc{i}",
                    w.key,
                    "Replies naturally in a line or two.",
                    channel=ch,
                    reply_to=f"nc{i}a",
                    length="short",
                )
            )
    stories.append(
        Story("noise-slack", "meridian", "Chatter", "Noise", "", 0, [], chat, [])
    )

    jb: list[Beat] = []
    for i, (proj, typ, title, intent) in enumerate(JIRA_NOISE):
        who = rng.choice(internal)
        jb.append(
            Beat(
                f"nj{i}",
                "jira",
                f"nj{i}",
                who.key,
                intent,
                action="create",
                project=proj,
                issue_type=typ,
                title=title,
                labels=["routine"],
            )
        )
        for j in range(rng.randint(0, 2)):
            jb.append(
                Beat(
                    f"nj{i}c{j}",
                    "jira",
                    f"nj{i}",
                    rng.choice(internal).key,
                    "A short, concrete progress comment.",
                    action="comment",
                    project=proj,
                    length="short",
                )
            )
        if rng.random() < 0.5:
            jb.append(
                Beat(
                    f"nj{i}t",
                    "jira",
                    f"nj{i}",
                    who.key,
                    "Moves it forward.",
                    action="transition",
                    project=proj,
                    to_status=rng.choice(["In Progress", "Done"]),
                )
            )
    stories.append(
        Story("noise-jira", "meridian", "Unrelated tickets", "Noise", "", 0, [], jb, [])
    )
    return stories


_ = Org
