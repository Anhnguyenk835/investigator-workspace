"""Granite Bay (a sync that failed silently) and Silverleaf (an onboarding that went well)."""

from __future__ import annotations

from investigator.devseed.beats import Beat, Fact, Story
from investigator.devseed.ctx import Ctx

JP, ENG = "CSE", "ENG"


def granite(c: Ctx) -> Story:
    f, fw, d = c.f, c.fw, c.date
    fail_from = d(10)
    days = (c.today - fail_from).days
    rca_due = c.ahead(3)
    B = Beat
    beats = [
        B(
            "g1",
            "email",
            "sla",
            "priya_m",
            "Sends Granite Bay the integration summary: nightly sync of investor "
            "commitments and capital accounts to Northstar Fund Services over SFTP; the support SLA says Anduin will "
            "notify the customer within 4 hours of a failed sync.",
            ["4 hours", "Northstar"],
            day=50,
            to=["leah", "rohan"],
            cc=["sarah", "priya_r"],
            subject="Granite Bay - Northstar integration summary and SLA",
        ),
        B(
            "g2",
            "email",
            "sla",
            "rohan",
            "Confirms the schedule and asks that sync alerts go to the fund ops "
            "mailbox.",
            [],
            day=49,
            to=["priya_m"],
            cc=["leah", "sarah"],
            reply_to="g1",
            length="short",
        ),
        B(
            "g3",
            "email",
            "found",
            "priya_r",
            f"Northstar's accountant notices Granite's capital account balances for "
            f"the quarter do not match the file Northstar last received, dated {f(fail_from)}; asks if there was a "
            "failure. She needs the data before quarter-end reporting.",
            [f(fail_from)],
            day=1,
            to=["rohan", "sarah"],
            cc=["leah"],
            subject="Granite Bay capital accounts - Northstar file is stale",
        ),
        B(
            "g4",
            "email",
            "found",
            "sarah",
            f"Confirms with engineering: the nightly sync has failed since {f(fail_from)} "
            f"({days} days), the customer was never notified. Apologises; says RCA and a fix are in progress.",
            [str(days)],
            day=1,
            to=["rohan", "leah"],
            cc=["priya_r", "alex", "rebecca"],
            reply_to="g3",
            quote=True,
        ),
        B(
            "g5",
            "email",
            "found",
            "leah",
            "CFO: the SLA says 4 hours, not a week and a half; asks for the RCA and what "
            "else may have gone stale.",
            ["4 hours"],
            day=1,
            to=["sarah", "rebecca"],
            cc=["rohan", "priya_r"],
            subject="RE: Granite Bay capital accounts - Northstar file is stale",
            length="short",
        ),
        B(
            "g6",
            "email",
            "found",
            "rebecca",
            f"Commits to an RCA by {fw(rca_due)} and to a monitored alert channel "
            "that pages the on-call engineer; asks Rohan for the right contact.",
            [fw(rca_due)],
            day=0.5,
            to=["leah"],
            cc=["sarah", "alex", "rohan"],
            reply_to="g5",
        ),
        B(
            "gs1",
            "slack",
            "int",
            "alex",
            f"Internal: the SFTP key used by the sync expired and was rotated on "
            f"{f(fail_from)}; the job failed on authentication every night after that. Alerts went to a retired "
            "mailbox (data-sync-alerts@) nobody reads.",
            ["SFTP"],
            channel="cs-granite",
        ),
        B(
            "gs2",
            "slack",
            "int",
            "jake",
            "FDE: says the sync log did show 'auth failed' nightly and he should have "
            "seen it in the weekly log review; he skipped it for two weeks (leave).",
            [],
            channel="cs-granite",
            reply_to="gs1",
        ),
        B(
            "gs3",
            "slack",
            "int",
            "sarah",
            "Notes the customer was never told within 4 hours as the SLA requires; the "
            "SLA breach is real. Asks Alex to confirm which other customers use the same key rotation.",
            ["4 hours"],
            channel="cs-granite",
            reply_to="gs1",
        ),
        B(
            "gs4",
            "slack",
            "int",
            "alex",
            "Answers: 3 other customers use the same job; their keys were rotated at "
            "different times and still work; monitoring work item created.",
            [],
            channel="cs-granite",
            reply_to="gs3",
        ),
        B(
            "gs5",
            "slack",
            "ext",
            "rohan",
            "Shared channel: asks Anduin to re-send the missing nightly files so "
            "Northstar can reconcile.",
            [],
            channel="ext-granite",
            length="short",
        ),
        B(
            "gs6",
            "slack",
            "ext",
            "sarah",
            "Confirms the backfill ran for all missing dates; asks Priya at Northstar "
            "to check the files.",
            [],
            channel="ext-granite",
            reply_to="gs5",
            length="short",
        ),
        B(
            "gj1",
            "jira",
            "gr-sync",
            "alex",
            "Creates a bug: nightly Northstar sync fails on SFTP authentication after "
            "key rotation; alerts go to a retired mailbox. Impact, fix, monitoring.",
            ["SFTP"],
            action="create",
            project=ENG,
            issue_type="Bug",
            labels=["cust-granite", "sync"],
            title="Northstar nightly sync fails silently after SFTP key rotation",
        ),
        B(
            "gj2",
            "jira",
            "gr-sync",
            "jake",
            "Comment: backfilled files for each missed date; counts per date.",
            [],
            action="comment",
            project=ENG,
        ),
        B(
            "gj3",
            "jira",
            "gr-esc",
            "sarah",
            "Creates the customer record: SLA breach notifying Granite Bay, impact on "
            "quarter-end, commitments (RCA, alert channel).",
            [fw(rca_due)],
            action="create",
            project=JP,
            issue_type="Task",
            labels=["cust-granite", "escalation"],
            title="Granite Bay: Northstar sync failure and SLA breach",
        ),
    ]
    facts = [
        Fact(
            "event",
            f"The nightly sync to Northstar failed from {f(fail_from)} ({days} days) because the SFTP key was rotated; nobody was alerted.",
            "",
            "",
            None,
            ["g3", "g4", "gs1"],
        ),
        Fact(
            "conflict",
            "The support SLA requires notice within 4 hours of a failed sync; the customer was told by Northstar after about 10 days.",
            "",
            "",
            None,
            ["g1", "g5", "gs3"],
        ),
        Fact(
            "commitment",
            f"Rebecca committed to an RCA by {fw(rca_due)} and a monitored alert channel; not yet delivered (due in the future).",
            "rebecca",
            str(rca_due),
            None,
            ["g6"],
        ),
        Fact(
            "root_cause",
            "Expired/rotated SFTP key plus alerts routed to a retired mailbox.",
            "",
            "",
            None,
            ["gs1"],
        ),
        Fact(
            "trap",
            "Priya Raman (Northstar, third party) is not Priya Menon (Anduin solutions architect).",
            "",
            "",
            None,
            ["g1", "g3"],
        ),
    ]
    return Story(
        "granite-sync",
        "granite",
        "Silent sync failure to the fund administrator",
        "An SFTP key rotation broke the nightly sync to Northstar and alerts went nowhere.",
        "What happened with Granite Bay's Northstar sync, did we breach the SLA, and what is promised?",
        50,
        ["cs-granite", "ext-granite"],
        beats,
        facts,
        ["cust-granite"],
        ["SEEDKB"],
    )


def silverleaf(c: Ctx) -> Story:
    f, fw, d = c.f, c.fw, c.date
    go_live = d(9)
    B = Beat
    beats = [
        B(
            "v1",
            "email",
            "kick",
            "mai",
            "Kickoff for Silverleaf Ventures onboarding: plan with 4 milestones, go-live "
            f"target {fw(go_live)}, owners and the customer's tasks.",
            [fw(go_live)],
            day=35,
            to=["noor"],
            cc=["sarah", "tom"],
            subject="Silverleaf Ventures - onboarding kickoff and plan",
        ),
        B(
            "v2",
            "email",
            "kick",
            "noor",
            "Thanks, will send the investor list template by next Wednesday.",
            [],
            day=34,
            to=["mai"],
            cc=["sarah"],
            reply_to="v1",
            length="short",
        ),
        B(
            "v3",
            "email",
            "data",
            "noor",
            "Sends the filled investor list (48 investors) with two questions about "
            "entity types.",
            ["48 investors"],
            day=26,
            to=["mai"],
            cc=["sarah"],
            subject="Silverleaf - investor list",
        ),
        B(
            "v4",
            "email",
            "data",
            "mai",
            "Answers the two questions, confirms the import will run tomorrow.",
            [],
            day=25,
            to=["noor"],
            cc=["sarah"],
            reply_to="v3",
            length="short",
        ),
        B(
            "v5",
            "email",
            "golive",
            "sarah",
            f"Go-live confirmation: all 48 investors invited on {f(go_live)} as planned, "
            "no open issues, first-week check-in scheduled.",
            [f(go_live), "48"],
            day=9,
            to=["noor"],
            cc=["mai", "tom"],
            subject="Silverleaf is live",
        ),
        B(
            "v6",
            "email",
            "golive",
            "noor",
            "Thanks, the team is happy; the first investors have already signed.",
            [],
            day=8,
            to=["sarah"],
            cc=["mai"],
            reply_to="v5",
            length="short",
        ),
        B(
            "vs1",
            "slack",
            "int",
            "mai",
            "Posts a tidy handoff note to CS: onboarding done on time, 48 investors, "
            "nothing outstanding, one tip about the entity-type mapping.",
            ["48"],
            channel="cs-silverleaf",
        ),
        B(
            "vs2",
            "slack",
            "int",
            "sarah",
            "Thanks Mai; schedules the 30-day check-in.",
            [],
            channel="cs-silverleaf",
            reply_to="vs1",
            length="short",
        ),
        B(
            "vj1",
            "jira",
            "sv-onb",
            "mai",
            "Creates and closes the onboarding task for Silverleaf; no issues.",
            [],
            action="create",
            project=JP,
            issue_type="Task",
            labels=["cust-silverleaf", "onboarding"],
            title="Silverleaf: onboarding and go-live",
        ),
        B(
            "vj2",
            "jira",
            "sv-onb",
            "mai",
            "Moves to Done.",
            [],
            action="transition",
            project=JP,
            to_status="Done",
        ),
    ]
    facts = [
        Fact(
            "status",
            f"Silverleaf onboarding went live on {f(go_live)} as planned with 48 investors; no escalations, no open commitments.",
            "",
            "",
            None,
            ["v1", "v5", "vs1"],
        ),
        Fact(
            "trap",
            "Nothing went wrong: the investigation should say so plainly and not invent problems.",
            "",
            "",
            None,
            ["v5"],
        ),
    ]
    return Story(
        "silverleaf-onboarding",
        "silverleaf",
        "A smooth onboarding",
        "Control case: an onboarding that went well and on time.",
        "How did the Silverleaf onboarding go and is anything open?",
        35,
        ["cs-silverleaf"],
        beats,
        facts,
        ["cust-silverleaf"],
        [],
    )
