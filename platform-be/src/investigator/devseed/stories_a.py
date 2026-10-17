"""Meridian (KYC backlog), Crestline (wrong capital call amounts), Blue Ridge (SSO date)."""

from __future__ import annotations

from investigator.devseed.beats import Attach, Beat, Fact, Story
from investigator.devseed.cast import lp_names
from investigator.devseed.ctx import Ctx

JP = "CSE"  # the customer-escalations Jira project
ENG = "ENG"  # engineering


def meridian(c: Ctx) -> Story:
    f, fw, d = c.f, c.fw, c.date
    close = c.ahead(9)
    promised = d(12)
    root_due = d(8)
    manual_due = d(5)
    names = lp_names(c.rng, 17)
    states = (
        ["Document expired"] * 2
        + ["Name mismatch with ID"] * 3
        + ["Sanctions screening hit"]
        + ["Callback never received"] * 11
    )
    csv = ["LP name,Status,Days pending"] + [
        f"{n},{s},{c.rng.randint(3, 9)}" for n, s in zip(names, states, strict=True)
    ]
    B = Beat
    beats = [
        B(
            "m1",
            "email",
            "order",
            "tom",
            "Recaps the signed Fund II order form for Rachel and Victor: onboarding scope, "
            "pricing, and the KYC service. Tom says LP verifications are cleared within 2 business days of a complete "
            "document upload.",
            ["2 business days"],
            day=34,
            to=["rachel", "victor"],
            cc=["sarah"],
            subject="Meridian Growth Partners | Fund II order form recap",
            attach=[
                Attach(
                    "Meridian-Fund-II-Order-Form.pdf",
                    "pdf",
                    "Order Form - Meridian Growth Partners Fund II",
                    [
                        "Services: Investor onboarding, digital subscription documents, KYC/AML verification, investor portal.",
                        "KYC verification service level: verification completed within 5 business days of a complete document upload.",
                        "Platform fee: USD 36,000 per year. Term: 12 months from the effective date.",
                        "Support: business hours, response within 1 business day.",
                    ],
                )
            ],
        ),
        B(
            "m2",
            "email",
            "order",
            "rachel",
            "Thanks Tom, confirms the plan and says the Fund II final close is the "
            "main deadline for them; asks who will be their day-to-day contact.",
            [f"final close {fw(close)}"],
            day=33,
            to=["tom"],
            cc=["victor", "sarah"],
            reply_to="m1",
            length="short",
        ),
        B(
            "m3",
            "email",
            "stuck",
            "beth",
            "Reports that 9 LPs have been showing KYC pending for days even though the "
            "verification vendor shows them as approved on the LP side. Fund II final close is near.",
            [f"final close is {fw(close)}", "9 LPs"],
            day=18,
            to=["hana"],
            cc=["rachel", "sarah"],
            subject="LPs stuck in KYC pending - Fund II",
        ),
        B(
            "m4",
            "email",
            "stuck",
            "hana",
            "Acknowledges, says she is checking logs and will report back today.",
            day=18,
            to=["beth"],
            cc=["rachel", "sarah"],
            reply_to="m3",
            length="short",
        ),
        B(
            "m5",
            "email",
            "stuck",
            "hana",
            "Explains the verification vendor VeriDoc had an incident and results did not "
            "reach the platform; the count is now 17 LPs. The team will review the LPs manually and Hana states the "
            "queue will be cleared by " + fw(promised) + ".",
            [f"cleared by {fw(promised)}", "17 LPs", "VeriDoc"],
            day=17,
            to=["beth"],
            cc=["rachel", "sarah"],
            reply_to="m4",
            quote=True,
            attach=[Attach("meridian-kyc-pending.csv", "csv", "", csv)],
        ),
        B(
            "m6",
            "email",
            "stuck",
            "beth",
            "Thanks, but reminds that the close is " + fw(close) + " and asks for a "
            "daily status.",
            [],
            day=17,
            to=["hana"],
            cc=["rachel", "sarah"],
            reply_to="m5",
            length="short",
        ),
        B(
            "m7",
            "email",
            "cadence",
            "sarah",
            "Introduces herself as CSM for the escalation and commits to a status "
            "summary every morning at 9am Pacific until the queue is cleared.",
            ["9am Pacific"],
            day=16,
            to=["rachel", "beth"],
            cc=["hana", "rebecca"],
            subject="Fund II KYC - daily status from Anduin",
        ),
        B(
            "m8",
            "email",
            "cadence",
            "sarah",
            "Daily update #1: counts, what was done, next steps.",
            ["17 LPs"],
            day=15,
            to=["rachel", "beth"],
            cc=["hana"],
            reply_to="m7",
            length="short",
        ),
        B(
            "m9",
            "email",
            "cadence",
            "sarah",
            "Daily update #2: 4 LPs cleared manually, 13 still pending.",
            ["4 LPs", "13"],
            day=14,
            to=["rachel", "beth"],
            cc=["hana"],
            reply_to="m8",
            length="short",
        ),
        B(
            "m10",
            "email",
            "escalation",
            "rachel",
            "Angry escalation to Rebecca, copying Victor and Tom: no update "
            f"since {f(d(14))}, Hana's {fw(promised)} date passed with 13 LPs still pending, and the close is "
            f"{f(close)}. Cites Tom's 2 business days promise. Demands a call and an owner.",
            ["13 LPs", "2 business days"],
            day=11,
            to=["rebecca"],
            cc=["victor", "sarah", "tom", "beth"],
            subject="Escalation: Fund II KYC - 13 LPs still pending",
        ),
        B(
            "m11",
            "email",
            "escalation",
            "rebecca",
            "Apologises, takes ownership, schedules a call for tomorrow at "
            "10am Pacific with Sarah, Hana, Carla and Alex.",
            ["10am Pacific"],
            day=11,
            to=["rachel"],
            cc=["victor", "sarah", "tom", "beth", "alex", "carla"],
            reply_to="m10",
            length="short",
        ),
        B(
            "m12",
            "email",
            "callrecap",
            "sarah",
            "Call recap with commitments: engineering will give a root cause by "
            f"{f(root_due)}, and all remaining LPs will be cleared or have a clear reason by {f(manual_due)}. "
            "Daily updates resume.",
            [f"root cause by {f(root_due)}", f"by {f(manual_due)}"],
            day=10,
            to=["rachel", "beth"],
            cc=["victor", "rebecca", "hana", "alex"],
            subject="Recap: Fund II KYC call",
        ),
        B(
            "m13",
            "email",
            "rootcause",
            "sarah",
            "Root cause delivered: VeriDoc rotated the webhook signing secret "
            "during maintenance, so the platform rejected their callbacks with HTTP 401. Fix deployed, backlog "
            "reprocessed: 7 more LPs cleared. 6 LPs remain and need manual attention.",
            ["webhook signing secret", "7", "6 LPs"],
            day=8,
            to=["rachel", "beth"],
            cc=["hana", "alex", "rebecca"],
            subject="Fund II KYC - root cause and status",
        ),
        B(
            "m14",
            "email",
            "rootcause",
            "beth",
            f"Reply with the six: 2 expired documents, 3 name mismatches, 1 sanctions "
            f"screening hit. Asks what Anduin can do before {f(close)}.",
            ["sanctions screening"],
            day=6,
            to=["sarah"],
            cc=["rachel", "hana"],
            reply_to="m13",
        ),
        B(
            "m15",
            "email",
            "inject",
            "pete",
            "Meridian Health Systems IT admin unrelated question that happens to say "
            "Meridian: asks how to reset an SSO password for a nurse manager account.",
            [],
            day=5,
            to=["hana"],
            subject="Meridian - password reset for SSO user",
            length="short",
        ),
        # --- live: today ---
        B(
            "ms1",
            "slack",
            "int1",
            "sarah",
            "Posts in the internal channel that Rachel's call is tomorrow 10am Pacific and she "
            "needs a clean story: what happened, what is left, who owns what.",
            [],
            channel="cs-meridian",
        ),
        B(
            "ms2",
            "slack",
            "int1",
            "hana",
            "Admits she told the client " + f(promised) + " without checking with "
            "Compliance whether manual review could be done that fast. Feels bad.",
            [],
            channel="cs-meridian",
            reply_to="ms1",
        ),
        B(
            "ms3",
            "slack",
            "int1",
            "carla",
            "Explains Compliance policy: manual KYC review needs two reviewers and a "
            "sanctions hit needs a documented decision; she never agreed to any date, and cannot guarantee the 6 LPs "
            f"before {f(close)}.",
            ["6 LPs"],
            channel="cs-meridian",
            reply_to="ms1",
        ),
        B(
            "ms4",
            "slack",
            "int1",
            "alex",
            "Engineering: confirms the root cause is the rotated VeriDoc webhook secret, "
            "points to the Jira bug and says a monitor on callback 401s is in progress, not yet shipped.",
            ["{jira:meridian-bug}"],
            channel="cs-meridian",
            reply_to="ms1",
        ),
        B(
            "ms5",
            "slack",
            "int1",
            "rebecca",
            "Reminds everyone that this is a process gap, not Hana's fault: sales "
            "quoted 2 business days, the order form says 5, support promised a date. Asks Sarah to prepare a one-page "
            "timeline.",
            [],
            channel="cs-meridian",
            reply_to="ms1",
        ),
        B(
            "ms6",
            "slack",
            "int1",
            "tom",
            "Defensive: says he quoted 2 days from the standard SLA sheet, not the order "
            "form. Offers to join the call.",
            [],
            channel="cs-meridian",
            reply_to="ms5",
            length="short",
        ),
        B(
            "ms7",
            "slack",
            "ext1",
            "sarah",
            "Posts today's 9am-style status in the shared channel: 7 cleared since "
            "the fix, 6 pending with reasons, call tomorrow.",
            ["6"],
            channel="ext-meridian",
        ),
        B(
            "ms8",
            "slack",
            "ext1",
            "beth",
            "Asks if the sanctions-hit LP can be removed from the close or whether "
            "they must wait.",
            [],
            channel="ext-meridian",
            reply_to="ms7",
            length="short",
        ),
        B(
            "ms9",
            "slack",
            "ext1",
            "sarah",
            "Answers carefully: that decision belongs to Meridian's compliance "
            "officer, Anduin only supplies the screening result; offers to send the report.",
            [],
            channel="ext-meridian",
            reply_to="ms8",
            length="short",
        ),
        B(
            "mj1",
            "jira",
            "meridian-esc",
            "sarah",
            "Creates the escalation: 17 LPs stuck in KYC pending for Meridian "
            "Fund II final close. Description: impact, timeline, promises made, current counts.",
            ["17 LPs"],
            action="create",
            project=JP,
            issue_type="Task",
            labels=["cust-meridian", "escalation"],
            title="Meridian Fund II: LPs stuck in KYC pending before final close",
        ),
        B(
            "mj2",
            "jira",
            "meridian-esc",
            "hana",
            "Comment: manual review log - what has been cleared and why 6 remain.",
            [],
            action="comment",
            project=JP,
        ),
        B(
            "mj3",
            "jira",
            "meridian-esc",
            "carla",
            "Comment: Compliance position on the sanctions hit and manual "
            "review capacity; no date committed.",
            [],
            action="comment",
            project=JP,
        ),
        B(
            "mj4",
            "jira",
            "meridian-esc",
            "sarah",
            "Moves the escalation to In Progress.",
            [],
            action="transition",
            project=JP,
            to_status="In Progress",
        ),
        B(
            "mj5",
            "jira",
            "meridian-bug",
            "alex",
            "Creates the engineering bug: platform rejects VeriDoc callbacks "
            "(HTTP 401, signature mismatch) after the vendor rotates its webhook secret. Includes log lines and the "
            "fix, plus the missing alert.",
            ["HTTP 401"],
            action="create",
            project=ENG,
            issue_type="Bug",
            labels=["cust-meridian", "kyc", "webhook"],
            title="KYC webhook signature validation rejects callbacks after secret rotation",
        ),
        B(
            "mj6",
            "jira",
            "meridian-bug",
            "minh",
            "Comment: fix deployed, backlog replay results, follow-up to add "
            "a secret-rotation runbook and an alert on 401s.",
            [],
            action="comment",
            project=ENG,
        ),
        B(
            "mj7",
            "jira",
            "meridian-bug",
            "minh",
            "Moves the bug to Done (the alert is tracked separately).",
            [],
            action="transition",
            project=ENG,
            to_status="Done",
        ),
        B(
            "mc1",
            "confluence",
            "meridian-pm",
            "alex",
            "Draft postmortem: KYC callback failures for Meridian Fund II. "
            "Sections: summary, impact, timeline, root cause, what went well, what did not (monitoring, commitments "
            "made without owner), action items with owners and dates.",
            ["VeriDoc"],
            action="page",
            space="SEEDKB",
            title="Postmortem (draft): VeriDoc callback failures - Meridian Fund II",
        ),
    ]
    facts = [
        Fact(
            "conflict",
            "Sales (Tom) quoted 2 business days for KYC verification; the signed order form says 5 business days.",
            "tom",
            "",
            None,
            ["m1"],
        ),
        Fact(
            "commitment",
            f"Hana promised the pending queue would be cleared by {fw(promised)}.",
            "hana",
            str(promised),
            False,
            ["m5", "m10"],
        ),
        Fact(
            "commitment",
            "Sarah promised a status every morning at 9am Pacific; sent on two days, then stopped until the call.",
            "sarah",
            "",
            False,
            ["m7", "m8", "m9", "m10"],
        ),
        Fact(
            "commitment",
            f"Engineering root cause promised by {f(root_due)}; delivered.",
            "alex",
            str(root_due),
            True,
            ["m12", "m13"],
        ),
        Fact(
            "commitment",
            f"All remaining LPs cleared or explained by {f(manual_due)}; 6 LPs were still pending after that date.",
            "sarah",
            str(manual_due),
            False,
            ["m12", "m14"],
        ),
        Fact(
            "root_cause",
            "VeriDoc rotated its webhook signing secret during maintenance; the platform rejected callbacks (HTTP 401), leaving 17 LPs in KYC pending.",
            "",
            "",
            None,
            ["m13", "ms4", "mj5"],
        ),
        Fact(
            "status",
            "17 stuck: 4 cleared manually, 7 cleared after the fix, 6 remain (2 expired documents, 3 name mismatches, 1 sanctions hit).",
            "",
            "",
            None,
            ["m9", "m13", "m14"],
        ),
        Fact(
            "trap",
            "Do not blame Hana alone: the date was promised without Compliance input, sales quoted a different SLA than the contract, and no one owned the monitoring gap.",
            "",
            "",
            None,
            ["ms2", "ms5"],
        ),
        Fact(
            "trap",
            "The 'Meridian Health Systems' IT thread is a different customer.",
            "",
            "",
            None,
            ["m15"],
        ),
    ]
    return Story(
        "meridian-kyc",
        "meridian",
        "KYC backlog before Fund II final close",
        "Meridian Growth Partners' LPs were stuck in KYC pending after the verification vendor rotated a webhook secret; promises and an SLA mismatch made it an escalation.",
        "What happened with the Meridian Fund II KYC backlog, who promised what, and what is still open?",
        34,
        ["cs-meridian", "ext-meridian"],
        beats,
        facts,
        ["cust-meridian"],
        ["SEEDKB"],
    )


def crestline(c: Ctx) -> Story:
    f, fw, d = c.f, c.fw, c.date
    total = 12_500_000
    wrong = c.rng.randint(11, 16)
    short = c.money(150_000, 220_000, 10)
    due_wire = d(7)
    corrected = d(11)
    rca_due = d(2)
    inv = c.rng.randint(80, 92)
    B = Beat
    amts = [
        f"LP-{i:03d},{c.money(120_000, 480_000, 100)},{c.money(118_000, 470_000, 100)}"
        for i in range(1, wrong + 1)
    ]
    beats = [
        B(
            "c1",
            "email",
            "notice",
            "dana",
            f"Sends the Capital Call #4 notice package for approval before release: "
            f"total call {c.usd(total)} across {inv} investors, wire due {fw(due_wire)}. Attaches the preview of "
            "the notice.",
            [c.usd(total), fw(due_wire)],
            day=17,
            to=["sarah"],
            cc=["owen", "marcus"],
            subject="Capital Call #4 - preview for approval",
            attach=[
                Attach(
                    "Capital-Call-4-Preview.pdf",
                    "pdf",
                    "Capital Call Notice #4 (preview)",
                    [
                        f"Crestline Real Estate Fund - Capital Call #4. Total call amount: {c.usd(total)}.",
                        f"Wire due date: {fw(due_wire)}. Beneficiary account details are in the portal.",
                        "Example investor LP-007: commitment 5,000,000; call 4.0%; management fee offset 2.0%; amount due 200,000.",
                    ],
                )
            ],
        ),
        B(
            "c2",
            "email",
            "notice",
            "marcus",
            "Controller approves the preview: spot checked five investors, they look "
            "right. Says go ahead and send.",
            [],
            day=16,
            to=["sarah", "dana"],
            cc=["owen"],
            reply_to="c1",
            length="short",
        ),
        B(
            "c3",
            "email",
            "notice",
            "sarah",
            "Confirms notices will be released tomorrow morning.",
            [],
            day=16,
            to=["dana", "marcus"],
            reply_to="c2",
            length="short",
        ),
        B(
            "c4",
            "email",
            "wrong",
            "marcus",
            f"Reports reconciliation is off: wires received so far are {c.usd(short)} "
            f"lower than expected, and one investor wired a lower amount than their statement. Asks if the notice "
            f"template changed.",
            [c.usd(short)],
            day=9,
            to=["sarah"],
            cc=["dana", "owen"],
            subject="Capital Call #4 - wire amounts do not reconcile",
        ),
        B(
            "c5",
            "email",
            "wrong",
            "sarah",
            "Takes it to engineering, promises a root cause and a corrected notice "
            f"list by end of day {fw(corrected)}.",
            [f"{f(corrected)}"],
            day=9,
            to=["marcus"],
            cc=["dana", "owen", "alex"],
            reply_to="c4",
            quote=True,
        ),
        B(
            "c6",
            "email",
            "wrong",
            "alex",
            f"Findings: a template change released on {f(d(20))} applied the management "
            f"fee offset twice for {wrong} investors who have both an offset and a side-letter rate, understating "
            f"their amount due. Total understatement {c.usd(short)}.",
            [f"{wrong} investors", c.usd(short)],
            day=8,
            to=["marcus", "sarah"],
            cc=["owen", "dana", "linh"],
            reply_to="c5",
            attach=[
                Attach(
                    "affected-investors.csv",
                    "csv",
                    "",
                    ["Investor,Notice amount,Correct amount", *amts],
                )
            ],
        ),
        B(
            "c7",
            "email",
            "corrected",
            "dana",
            "Asks Sarah to hold the corrected notices until legal reviews wording, "
            "because investors have been told 'amounts final'. Copies counsel Elaine.",
            [],
            day=8,
            to=["sarah"],
            cc=["owen", "elaine", "marcus"],
            subject="Corrected capital call notices - wording",
        ),
        B(
            "c8",
            "email",
            "corrected",
            "elaine",
            "Counsel advises corrected notices say 'supersedes the notice dated "
            f"{f(d(16))}' and extend the wire deadline for affected investors only, to {fw(c.ahead(3))}.",
            [fw(c.ahead(3))],
            day=7,
            to=["dana", "sarah"],
            cc=["owen", "marcus"],
            reply_to="c7",
        ),
        B(
            "c9",
            "email",
            "corrected",
            "sarah",
            f"Corrected notices were sent to the {wrong} investors; apologises that "
            f"they went out {f(d(7))}, later than the {f(corrected)} promised. Says Alex will deliver a written "
            f"root-cause analysis by {f(rca_due)}.",
            [f(rca_due)],
            day=7,
            to=["marcus", "dana"],
            cc=["owen", "alex"],
            reply_to="c6",
            quote=True,
        ),
        B(
            "c10",
            "email",
            "approval",
            "owen",
            "CFO angry: they approved the preview PDF but it was one sample; "
            "demands to know who approved the template change and why QA missed it; asks whether Anduin will "
            "waive fees for the quarter.",
            [],
            day=5,
            to=["rebecca"],
            cc=["sarah", "marcus", "dana"],
            subject="Capital Call #4 - accountability",
        ),
        B(
            "c11",
            "email",
            "approval",
            "rebecca",
            "Responds without admitting liability: RCA is coming, details the "
            "release process, says commercial matters go through Tom and will be handled separately.",
            [],
            day=4,
            to=["owen"],
            cc=["sarah", "tom"],
            reply_to="c10",
        ),
        # live
        B(
            "cs1",
            "slack",
            "int",
            "alex",
            "Posts RCA findings in internal channel: template v18 released by Minh "
            "bypassed the regression suite because the capital-call fixtures were not part of the required checks.",
            [],
            channel="cs-crestline",
        ),
        B(
            "cs2",
            "slack",
            "int",
            "linh",
            "QA side: says she had the ticket to sign off, but release went out before "
            "her sign-off, and fixtures for offset+side-letter were never in the suite. Not defensive, factual.",
            [],
            channel="cs-crestline",
            reply_to="cs1",
        ),
        B(
            "cs3",
            "slack",
            "int",
            "minh",
            "Owns it: pushed the template after the approval from the change channel, "
            "didn't wait for QA sign-off because the release window was closing.",
            [],
            channel="cs-crestline",
            reply_to="cs1",
        ),
        B(
            "cs4",
            "slack",
            "int",
            "rebecca",
            "Sets expectations: RCA to Owen is due " + f(rca_due) + " and has not "
            "started; asks Alex for a draft today; no discussion of fee waiver in writing.",
            [f(rca_due)],
            channel="cs-crestline",
            reply_to="cs1",
        ),
        B(
            "cs5",
            "slack",
            "ext",
            "sarah",
            "Shared channel: tells Dana and Marcus the RCA draft is in progress and the "
            "reconciled list is attached to the Jira issue.",
            [],
            channel="ext-crestline",
        ),
        B(
            "cs6",
            "slack",
            "ext",
            "marcus",
            "Confirms all but two investors have now wired; asks for a corrected "
            "investor statement for the two.",
            [],
            channel="ext-crestline",
            reply_to="cs5",
            length="short",
        ),
        B(
            "cj1",
            "jira",
            "crest-bug",
            "alex",
            "Creates the bug: capital call template applies management fee offset "
            "twice for investors with offset plus side-letter rate. Impact, root cause, fix and the missing regression "
            "fixture.",
            ["management fee offset"],
            action="create",
            project=ENG,
            issue_type="Bug",
            labels=["cust-crestline", "capital-call"],
            title="Capital call template double-applies fee offset for side-letter investors",
        ),
        B(
            "cj2",
            "jira",
            "crest-bug",
            "linh",
            "Comment: added regression fixtures for offset plus side-letter; suite "
            "is now required before template releases.",
            [],
            action="comment",
            project=ENG,
        ),
        B(
            "cj3",
            "jira",
            "crest-bug",
            "minh",
            "Moves to Done.",
            [],
            action="transition",
            project=ENG,
            to_status="Done",
        ),
        B(
            "cj4",
            "jira",
            "crest-esc",
            "sarah",
            "Creates the customer escalation record for Crestline Capital Call #4 "
            "with timeline and the promises: corrected notices by "
            + f(corrected)
            + ", RCA by "
            + f(rca_due)
            + ".",
            [f(corrected), f(rca_due)],
            action="create",
            project=JP,
            issue_type="Task",
            labels=["cust-crestline", "escalation"],
            title="Crestline: Capital Call #4 incorrect amounts",
        ),
        B(
            "cj5",
            "jira",
            "crest-esc",
            "sarah",
            "Comment: corrected notices went out late; RCA overdue and not yet sent.",
            [],
            action="comment",
            project=JP,
        ),
        B(
            "cc1",
            "confluence",
            "crest-rca",
            "alex",
            "RCA draft for Crestline capital call #4: summary, impact "
            f"({wrong} investors, {c.usd(short)}), timeline, root cause, contributing factors, corrective actions.",
            [c.usd(short)],
            action="page",
            space="SEEDKB",
            title="RCA (draft): Capital Call #4 amounts - Crestline",
        ),
    ]
    facts = [
        Fact(
            "event",
            f"Capital Call #4 notices (total {c.usd(total)}) went out with understated amounts for {wrong} investors, totalling {c.usd(short)}.",
            "",
            "",
            None,
            ["c4", "c6"],
        ),
        Fact(
            "root_cause",
            "A template change double-applied the management fee offset for investors with an offset and a side-letter rate; the regression suite lacked those fixtures and QA sign-off was skipped.",
            "",
            "",
            None,
            ["c6", "cs1", "cs2", "cs3"],
        ),
        Fact(
            "commitment",
            f"Sarah promised corrected notices by {fw(corrected)}; they went out {f(d(7))}.",
            "sarah",
            str(corrected),
            False,
            ["c5", "c9"],
        ),
        Fact(
            "commitment",
            f"RCA from Alex promised by {f(rca_due)}; still a draft, not delivered.",
            "alex",
            str(rca_due),
            False,
            ["c9", "cs4"],
        ),
        Fact(
            "trap",
            "The customer's controller approved a preview of five investors; that does not shift responsibility for the template defect. Do not state fault beyond the evidence.",
            "marcus",
            "",
            None,
            ["c2", "c10"],
        ),
        Fact(
            "trap",
            "A fee waiver was demanded but never offered; commercial terms are not agreed.",
            "",
            "",
            None,
            ["c10", "c11", "cs4"],
        ),
    ]
    return Story(
        "crestline-capital-call",
        "crestline",
        "Capital Call #4 wrong amounts",
        "A template change understated capital call amounts for investors with a fee offset and a side letter.",
        "What went wrong with Crestline's Capital Call #4 notices, who promised what, and what is overdue?",
        17,
        ["cs-crestline", "ext-crestline"],
        beats,
        facts,
        ["cust-crestline"],
        ["SEEDKB"],
    )


def blueridge(c: Ctx) -> Story:
    f, fw, d = c.f, c.fw, c.date
    first_test = d(27)
    second_test = d(19)
    new_eta = c.ahead(5)
    B = Beat
    beats = [
        B(
            "b1",
            "email",
            "contract",
            "tom",
            f"Sends the order form to Helen: SSO via SAML is included. Tom writes "
            f"that Anduin will have SSO live for their team by {f(d(16))}.",
            ["SSO live", f(d(16))],
            day=62,
            to=["helen"],
            cc=["arjun", "sarah"],
            subject="Blue Ridge Family Office - order form and SSO",
        ),
        B(
            "b2",
            "email",
            "contract",
            "helen",
            "Signs and says the date matters because the whole office moves to "
            "Okta-only login at the start of the quarter.",
            [],
            day=60,
            to=["tom"],
            cc=["arjun", "colin"],
            reply_to="b1",
            length="short",
        ),
        B(
            "b3",
            "email",
            "kickoff",
            "mai",
            "Implementation kickoff: plan with milestones. IdP metadata exchange, test "
            f"window, user migration, go-live. Mai's plan shows go-live on {fw(c.ahead(5))}.",
            [fw(c.ahead(5))],
            day=45,
            to=["arjun", "colin"],
            cc=["sarah", "priya_m"],
            subject="Blue Ridge SSO implementation plan",
        ),
        B(
            "b4",
            "email",
            "kickoff",
            "arjun",
            "Pushes back: sales told them it would be live by " + f(d(16)) + ". "
            "Asks why the plan says later.",
            [f(d(16))],
            day=44,
            to=["mai"],
            cc=["colin", "helen", "sarah"],
            reply_to="b3",
        ),
        B(
            "b5",
            "email",
            "kickoff",
            "sarah",
            "Mediates: apologises for the mismatch, says she is checking with sales "
            "and will come back with a single date.",
            [],
            day=44,
            to=["arjun"],
            cc=["mai", "tom", "colin"],
            reply_to="b4",
            length="short",
        ),
        B(
            "b6",
            "email",
            "test1",
            "colin",
            f"Sends Okta IdP metadata and the group-claim names. First test window "
            f"on {f(first_test)} failed: users could log in but landed with no role.",
            ["group"],
            day=27,
            to=["priya_m", "mai"],
            cc=["arjun"],
            subject="SAML test 1 - users have no role after login",
        ),
        B(
            "b7",
            "email",
            "test1",
            "priya_m",
            "Diagnoses: the platform maps roles from a 'roles' claim, Okta sends "
            "'groups'; proposes a claim mapping and a retest.",
            ["groups"],
            day=26,
            to=["colin"],
            cc=["mai", "arjun"],
            reply_to="b6",
        ),
        B(
            "b8",
            "email",
            "test2",
            "colin",
            f"Second test window {f(second_test)}: login works for existing users, "
            "but new users are not created automatically; Okta provisions on first login and the platform returns "
            "403.",
            ["403"],
            day=19,
            to=["priya_m", "mai"],
            cc=["arjun", "helen"],
            subject="SAML test 2 - new users get 403",
        ),
        B(
            "b9",
            "email",
            "test2",
            "priya_m",
            "Admits JIT (just-in-time) user provisioning is not supported on this "
            "tenant tier and was not in scope in the implementation plan; opened a request with engineering.",
            ["JIT"],
            day=18,
            to=["colin", "arjun"],
            cc=["mai", "alex", "sarah"],
            reply_to="b8",
        ),
        B(
            "b10",
            "email",
            "eta",
            "helen",
            "Cuts through: wants one date in writing. Reminds everyone Tom committed "
            f"to {f(d(16))}; says their auditor requires SSO by quarter end.",
            [f(d(16))],
            day=14,
            to=["sarah", "tom"],
            cc=["arjun", "colin", "rebecca"],
            subject="Blue Ridge SSO - need a committed date",
        ),
        B(
            "b11",
            "email",
            "eta",
            "alex",
            f"Engineering's answer to Sarah: targeting {f(new_eta)} for JIT "
            "provisioning; says it is a target, not a commitment, until the design review on Monday.",
            [f(new_eta), "target"],
            day=13,
            to=["sarah"],
            cc=["priya_m", "mai", "rebecca"],
            subject="RE: Blue Ridge SSO date",
        ),
        B(
            "b12",
            "email",
            "eta",
            "sarah",
            f"Replies to Helen with the new date {f(new_eta)}, apologises for the miss "
            f"against {f(d(16))}, and says it depends on the design review; does not say it is only a target.",
            [f(new_eta)],
            day=12,
            to=["helen"],
            cc=["arjun", "colin", "tom", "rebecca"],
            reply_to="b10",
            quote=True,
        ),
        B(
            "b13",
            "email",
            "eta",
            "helen",
            f"Reads Sarah's email as a commitment to {f(new_eta)} and says so; asks "
            "for a weekly written status.",
            [f(new_eta)],
            day=11,
            to=["sarah"],
            cc=["tom", "rebecca"],
            reply_to="b12",
            length="short",
        ),
        B(
            "bs1",
            "slack",
            "int",
            "sarah",
            "Asks in the internal channel: Alex wrote 'target' but I told Helen it's "
            "the date. Are we committing or not? Needs an answer before the weekly status.",
            [],
            channel="cs-blueridge",
        ),
        B(
            "bs2",
            "slack",
            "int",
            "alex",
            "Says no commitment until the design review finishes; JIT work is two "
            "sprints, the date assumes no surprises.",
            ["design review"],
            channel="cs-blueridge",
            reply_to="bs1",
        ),
        B(
            "bs3",
            "slack",
            "int",
            "tom",
            "Admits he wrote the Oct date on instinct from a similar customer; never "
            "checked with implementation.",
            [],
            channel="cs-blueridge",
            reply_to="bs1",
        ),
        B(
            "bs4",
            "slack",
            "int",
            "mai",
            "Notes her plan never had JIT because the scoping call notes didn't mention "
            "it; blames the scoping handoff, not individuals.",
            [],
            channel="cs-blueridge",
            reply_to="bs3",
        ),
        B(
            "bs5",
            "slack",
            "ext",
            "mai",
            "Shared channel: posts weekly status - metadata done, claim mapping done, "
            "JIT in engineering, next retest after design review.",
            [],
            channel="ext-blueridge",
        ),
        B(
            "bj1",
            "jira",
            "br-sso",
            "mai",
            "Creates epic-like task: Blue Ridge SAML SSO implementation with the "
            "milestone list and the dependency on JIT provisioning.",
            ["JIT"],
            action="create",
            project=JP,
            issue_type="Task",
            labels=["cust-blueridge", "sso"],
            title="Blue Ridge: SAML SSO implementation",
        ),
        B(
            "bj2",
            "jira",
            "br-sso",
            "priya_m",
            "Comment: test results summary for tests 1 and 2 and the claim mapping.",
            [],
            action="comment",
            project=JP,
        ),
        B(
            "bj3",
            "jira",
            "br-jit",
            "alex",
            "Creates engineering story: Just-in-time user provisioning for SAML "
            "tenants. Acceptance criteria and estimate (two sprints).",
            ["two sprints"],
            action="create",
            project=ENG,
            issue_type="Story",
            labels=["cust-blueridge", "sso"],
            title="SAML: just-in-time user provisioning",
        ),
        B(
            "bj4",
            "jira",
            "br-jit",
            "alex",
            "Moves to In Progress.",
            [],
            action="transition",
            project=ENG,
            to_status="In Progress",
        ),
        B(
            "bc1",
            "confluence",
            "br-runbook",
            "priya_m",
            "Runbook: customer SAML SSO setup - metadata, claim names, "
            "role mapping, JIT limitations by tier, test checklist, common failures (no role, 403).",
            ["JIT"],
            action="page",
            space="SEEDKB",
            title="Runbook: customer SAML SSO setup",
        ),
    ]
    facts = [
        Fact(
            "commitment",
            f"Tom (sales) wrote that SSO would be live by {f(d(16))}; implementation's plan said {fw(c.ahead(5))}. Nobody reconciled them.",
            "tom",
            str(d(16)),
            False,
            ["b1", "b3", "b4"],
        ),
        Fact(
            "root_cause",
            "Two test failures: role claim mismatch (groups vs roles) then missing JIT provisioning, which was not in the implementation scope.",
            "",
            "",
            None,
            ["b6", "b7", "b8", "b9"],
        ),
        Fact(
            "conflict",
            f"Engineering said {f(new_eta)} is a target, not a commitment; Sarah told the customer it was the date; Helen treats it as a commitment.",
            "",
            str(new_eta),
            None,
            ["b11", "b12", "b13", "bs1", "bs2"],
        ),
        Fact(
            "trap",
            "An expectation is not a commitment: Alex's 'target' must not be reported as a commitment by Anduin, but Sarah's email to the customer did present it as the date.",
            "",
            "",
            None,
            ["b11", "b12"],
        ),
        Fact(
            "trap",
            "Blame lies in the scoping handoff (no JIT in scope), not in one person.",
            "",
            "",
            None,
            ["bs3", "bs4"],
        ),
    ]
    return Story(
        "blueridge-sso",
        "blueridge",
        "SSO go-live slipped past the sold date",
        "Sales sold an SSO date implementation never planned for; testing exposed missing JIT provisioning.",
        "Why is Blue Ridge's SSO late, who committed to which date, and what is the current status?",
        62,
        ["cs-blueridge", "ext-blueridge"],
        beats,
        facts,
        ["cust-blueridge"],
        ["SEEDKB"],
    )
