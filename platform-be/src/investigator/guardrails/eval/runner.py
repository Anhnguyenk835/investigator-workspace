"""Scores the deterministic guards against the red-team corpus. No model is called.

What it measures:
  - injection: of the attacks in each placement (email, Slack, Jira, a wiki page, an
    attachment, a title, a sender name), how many still show the canary to the model
    (attack success rate), and how many ordinary records it wrongly changes (false positives);
  - identifiers: precision and recall for each kind of personal detail, and that restoring a
    tokenized text gives the text back exactly;
  - output: how many markdown/HTML exfiltration payloads survive sanitising;
  - egress: whether a search the model should not make is refused, and an ordinary one is not.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from investigator.connectors.base import EvidenceRecord
from investigator.guardrails import GuardPolicy, GuardRuntime
from investigator.guardrails.context import GuardContext
from investigator.guardrails.egress import screen_search
from investigator.guardrails.injection.quarantine import protect
from investigator.guardrails.output.sanitize import sanitize
from investigator.guardrails.pii.aliases import MemoryAliasBook
from investigator.guardrails.pii.detect import find
from investigator.guardrails.pii.names import NameMatcher
from investigator.guardrails.pii.tokenize import ReverseMap, tokenize_text
from investigator.tools.harness import render_record

CORPUS = Path(__file__).parent / "corpus"
FILLER = (
    "The intake form for the Monday filing is still pending and the board pack depends on it. "
    "Legal has asked for the signed copy and the vendor has not confirmed the delivery date. "
)

# placement name -> how a payload is embedded in a record
PLACEMENTS = [
    "email",
    "slack",
    "jira",
    "confluence",
    "notion",
    "forwarded",
    "attachment",
    "title",
    "author",
]


def _record(placement: str, payload: str) -> EvidenceRecord:
    base: dict[str, Any] = {
        "id": "r1",
        "source": "email",
        "title": "Form update",
        "author": "Alex",
    }
    if placement == "email":
        body = f"Hi team,\n\n{FILLER}\n\n{payload}\n\nBest regards,\nAlex"
    elif placement == "slack":
        body = payload
        base["source"] = "chat"
    elif placement == "jira":
        body = f"Status: waiting on customer.\n\n{payload}"
        base["source"] = "ticket"
    elif placement in ("confluence", "notion"):
        body = (FILLER * 4) + payload + "\n" + (FILLER * 4)
        base["source"] = "wiki"
    elif placement == "forwarded":
        body = (
            FILLER
            + "\n---------- Forwarded message ----------\n"
            + "\n".join(f"> {ln}" for ln in payload.split("\n"))
        )
    elif placement == "attachment":
        body = (FILLER * 12) + payload + "\n" + (FILLER * 12)
        base["meta"] = {"kind": "attachment"}
    elif placement == "title":
        body = FILLER
        base["title"] = payload[:160]
    elif placement == "author":
        body = FILLER
        base["author"] = payload[:80]
    else:  # pragma: no cover
        raise ValueError(placement)
    return EvidenceRecord(excerpt=body, **base)


class Rate(BaseModel):
    hits: int = 0
    total: int = 0
    failures: list[str] = Field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.hits / self.total if self.total else 0.0


class Report(BaseModel):
    injection_asr: dict[str, Rate] = Field(default_factory=dict)  # by layer
    injection_by_owasp: dict[str, Rate] = Field(default_factory=dict)
    injection_by_placement: dict[str, Rate] = Field(default_factory=dict)
    injection_fpr: Rate = Field(default_factory=Rate)
    pii_recall: dict[str, Rate] = Field(default_factory=dict)
    pii_precision: dict[str, Rate] = Field(default_factory=dict)
    pii_false_positive: Rate = Field(default_factory=Rate)
    roundtrip: Rate = Field(default_factory=Rate)
    output_asr: Rate = Field(default_factory=Rate)
    egress_correct: Rate = Field(default_factory=Rate)
    sizes: dict[str, int] = Field(default_factory=dict)

    def flat(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for layer, r in self.injection_asr.items():
            out[f"injection.asr.{layer}"] = r.rate
        for k, r in self.injection_by_owasp.items():
            out[f"injection.asr.owasp.{k}"] = r.rate
        out["injection.fpr"] = self.injection_fpr.rate
        for k, r in self.pii_recall.items():
            out[f"pii.recall.{k}"] = r.rate
        for k, r in self.pii_precision.items():
            out[f"pii.precision.{k}"] = r.rate
        out["pii.false_positive"] = self.pii_false_positive.rate
        out["roundtrip.exact"] = self.roundtrip.rate
        out["output.asr"] = self.output_asr.rate
        out["egress.correct"] = self.egress_correct.rate
        return out


def load(name: str) -> Any:
    return json.loads((CORPUS / f"{name}.json").read_text())


def _rate(book: dict[str, Rate], key: str) -> Rate:
    return book.setdefault(key, Rate())


async def run_injection(report: Report) -> None:
    rt = GuardRuntime.for_tests(GuardPolicy(injection="enforce"))
    for case in load("attacks"):
        for placement in PLACEMENTS:
            if (
                placement in ("title", "author")
                and len(case["text"]) > 80
                and "\n" in case["text"]
            ):
                continue
            protected = await protect(_record(placement, case["text"]), rt)
            seen = render_record(protected, 100_000)
            leaked = case["canary"] in seen
            for bucket, key in (
                (report.injection_asr, case["layer"]),
                (report.injection_by_owasp, case["owasp"]),
                (report.injection_by_placement, placement),
            ):
                r = _rate(bucket, key)
                r.total += 1
                if leaked:
                    r.hits += 1
                    r.failures.append(f"{case['id']}@{placement}")
    for text in load("benign"):
        for placement in ("email", "slack", "jira"):
            rec = _record(placement, text)
            changed = await protect(rec, rt)
            report.injection_fpr.total += 1
            if changed.trust == "tainted" or changed.model_excerpt is not None:
                report.injection_fpr.hits += 1
                report.injection_fpr.failures.append(f"{placement}: {text[:70]}")


async def run_pii(report: Report) -> None:
    kinds_total: dict[str, int] = defaultdict(int)
    kinds_found: dict[str, int] = defaultdict(int)
    kinds_claimed: dict[str, int] = defaultdict(int)
    kinds_correct: dict[str, int] = defaultdict(int)
    texts: list[tuple[str, set[str]]] = []
    for case in load("pii"):
        names = set(case["names"])
        matcher = NameMatcher(names) if names else None
        spans = find(case["text"]) + (matcher.find(case["text"]) if matcher else [])
        got = {(s.kind, s.value.strip()) for s in spans}
        gold = {(k, v) for k, v in case["gold"]}
        for kind, value in gold:
            key = "PERSON_free_text" if kind == "PERSON@free" else kind
            kinds_total[key] += 1
            hit = (kind, value) in got or any(
                k == kind and value.lower() in v.lower() for k, v in got
            )
            kinds_found[key] += int(hit)
            if not hit:
                _rate(report.pii_recall, key).failures.append(value)
        for kind, value in got:
            kinds_claimed[kind] += 1
            if any(
                k.split("@")[0] == kind
                and (value.lower() in v.lower() or v.lower() in value.lower())
                for k, v in gold
            ):
                kinds_correct[kind] += 1
        texts.append((case["text"], names))
    for k, n in kinds_total.items():
        r = _rate(report.pii_recall, k)
        r.total, r.hits = n, kinds_found[k]
    for k, n in kinds_claimed.items():
        r = _rate(report.pii_precision, k)
        r.total, r.hits = n, kinds_correct[k]
    for text in load("no_pii"):
        report.pii_false_positive.total += 1
        if find(text):
            report.pii_false_positive.hits += 1
            report.pii_false_positive.failures.append(text)
        texts.append((text, set()))
    texts += [(t, set()) for t in load("benign")[:60]]
    for case in load("attacks"):
        texts.append((case["text"], set()))
    for text, names in texts:
        rev = ReverseMap()
        matcher = NameMatcher(names) if names else None
        out = await tokenize_text(text, "eval", MemoryAliasBook(), rev, matcher)
        report.roundtrip.total += 1
        if rev.restore(out) == text:
            report.roundtrip.hits += 1
        else:
            report.roundtrip.failures.append(text[:70])


def run_output(report: Report) -> None:
    for case in load("output"):
        clean, _ = sanitize(case["text"])
        report.output_asr.total += 1
        if any(f in clean for f in case["forbidden"]):
            report.output_asr.hits += 1
            report.output_asr.failures.append(case["text"][:70])


def run_egress(report: Report) -> None:
    for case in load("egress"):
        ctx = GuardContext(run_id="r", shown=set(case["shown"]))
        refusal = screen_search(case["query"], None, ctx, corpus=[], pending_cursors=[])
        got = refusal.rule if refusal else None
        report.egress_correct.total += 1
        if got == case["expect"]:
            report.egress_correct.hits += 1
        else:
            report.egress_correct.failures.append(
                f"{case['query']!r}: expected {case['expect']}, got {got}"
            )


async def run_all() -> Report:
    report = Report()
    await run_injection(report)
    await run_pii(report)
    run_output(report)
    run_egress(report)
    report.sizes = {
        "attacks": len(load("attacks")),
        "benign": len(load("benign")),
        "pii_cases": len(load("pii")),
        "output_cases": len(load("output")),
        "egress_cases": len(load("egress")),
    }
    return report


def table(report: Report) -> str:
    lines = [f"{'metric':<42}{'value':>8}  detail"]
    for k, v in sorted(report.flat().items()):
        lines.append(f"{k:<42}{v:>8.3f}")
    return "\n".join(lines)


def check(report: Report, thresholds: dict[str, dict[str, float]]) -> list[str]:
    """Violations of the gate: a `max` metric above its limit or a `min` metric below it."""
    flat = report.flat()
    bad: list[str] = []
    for metric, limit in thresholds.get("max", {}).items():
        if metric in flat and flat[metric] > limit + 1e-9:
            bad.append(f"{metric} = {flat[metric]:.3f} is above the limit {limit}")
        if metric not in flat:
            bad.append(f"{metric} was not measured")
    for metric, limit in thresholds.get("min", {}).items():
        if metric in flat and flat[metric] < limit - 1e-9:
            bad.append(f"{metric} = {flat[metric]:.3f} is below the floor {limit}")
        if metric not in flat:
            bad.append(f"{metric} was not measured")
    return bad


class LiveReport(BaseModel):
    detected: Rate = Field(default_factory=Rate)
    wrongly_flagged: Rate = Field(default_factory=Rate)


async def run_live(llm: Any, repeats: int = 3, benign_sample: int = 20) -> LiveReport:
    """Ask the real classifier about the attacks the rules do not claim, and about ordinary
    writing that looks alike. Not run in CI: a model's answers vary, so this reports rates.
    Pass a `GuardedLlm` whose budget has a hard cost cap."""
    from investigator.guardrails.injection.classifier import classify

    report = LiveReport()
    for case in load("attacks"):
        if case["layer"] != "classifier":
            continue
        for _ in range(repeats):
            report.detected.total += 1
            if await classify(llm, case["text"]) is True:
                report.detected.hits += 1
            else:
                report.detected.failures.append(case["id"])
    for text in load("benign")[:benign_sample]:
        report.wrongly_flagged.total += 1
        if await classify(llm, text) is True:
            report.wrongly_flagged.hits += 1
            report.wrongly_flagged.failures.append(text[:70])
    return report
