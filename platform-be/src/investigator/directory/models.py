"""Who the customers, projects and people are, and where each lives in the sources.

The sources themselves know none of this: a Slack channel has no customer, an email
has no project. The directory is the mapping a person writes down once, and it is what
lets a case be limited to one customer and what tells a customer's words from ours."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Side = Literal["customer", "internal", "third_party"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _clean(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


class _Tidy(BaseModel):
    """Lists of names are stored trimmed, without blanks or repeats."""

    @model_validator(mode="after")
    def _tidy_lists(self) -> _Tidy:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                setattr(self, name, _clean(value))
        return self


class CustomerInput(_Tidy):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    # Mail to or from these domains belongs to this customer.
    email_domains: list[str] = Field(default_factory=list, max_length=30)


class Customer(CustomerInput):
    id: str


class ProjectInput(_Tidy):
    name: str = Field(min_length=1, max_length=200)
    customer_id: str | None = None
    aliases: list[str] = Field(default_factory=list, max_length=30)
    # Where this project lives. Empty means "not mapped for that source".
    ticket_prefixes: list[str] = Field(default_factory=list, max_length=20)
    jira_projects: list[str] = Field(default_factory=list, max_length=20)
    jira_labels: list[str] = Field(default_factory=list, max_length=20)
    slack_channel_ids: list[str] = Field(default_factory=list, max_length=50)
    gmail_labels: list[str] = Field(default_factory=list, max_length=20)
    confluence_spaces: list[str] = Field(default_factory=list, max_length=20)


class Project(ProjectInput):
    id: str


class PersonInput(_Tidy):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    emails: list[str] = Field(default_factory=list, max_length=20)
    slack_ids: list[str] = Field(default_factory=list, max_length=10)
    jira_account_ids: list[str] = Field(default_factory=list, max_length=10)
    side: Side = "third_party"
    role: str | None = Field(default=None, max_length=100)
    customer_id: str | None = None


class Person(PersonInput):
    id: str


class SourceFilter(BaseModel):
    """How one source is narrowed to a case. Empty fields mean "no restriction"."""

    channels: list[str] = Field(default_factory=list)
    jira_projects: list[str] = Field(default_factory=list)
    jira_labels: list[str] = Field(default_factory=list)
    gmail_labels: list[str] = Field(default_factory=list)
    gmail_domains: list[str] = Field(default_factory=list)
    confluence_spaces: list[str] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (
                self.channels,
                self.jira_projects,
                self.jira_labels,
                self.gmail_labels,
                self.gmail_domains,
                self.confluence_spaces,
            )
        )


class Matches(BaseModel):
    customers: list[Customer] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)


class Directory(BaseModel):
    customers: list[Customer] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.customers or self.projects)

    def customer(self, customer_id: str | None) -> Customer | None:
        return next((c for c in self.customers if c.id == customer_id), None)

    def project(self, project_id: str | None) -> Project | None:
        return next((p for p in self.projects if p.id == project_id), None)

    # ---- names in text -------------------------------------------------------------

    @staticmethod
    def _mentions(text: str, names: list[str]) -> bool:
        body = _norm(text)
        return any(
            n and re.search(rf"(?<![\w]){re.escape(_norm(n))}(?![\w])", body)
            for n in names
        )

    def match(self, text: str) -> Matches:
        """Customers and projects the text names (by name, alias or ticket id)."""
        out = Matches()
        for p in self.projects:
            tickets = [
                f"{prefix.strip().rstrip('-')}-\\d+" for prefix in p.ticket_prefixes
            ]
            by_ticket = any(
                re.search(rf"\b{t}\b", text, re.IGNORECASE) for t in tickets
            )
            if by_ticket or self._mentions(text, [p.name, *p.aliases]):
                out.projects.append(p)
        named = [
            c for c in self.customers if self._mentions(text, [c.name, *c.aliases])
        ]
        for c in named:
            out.customers.append(c)
        # A named project implies its customer.
        for p in out.projects:
            owner = self.customer(p.customer_id)
            if owner and owner not in out.customers:
                out.customers.append(owner)
        return out

    # ---- narrowing a source --------------------------------------------------------

    def _projects_in_scope(
        self, customer_id: str | None, project_id: str | None
    ) -> list[Project]:
        if project_id:
            found = self.project(project_id)
            return [found] if found else []
        if customer_id:
            return [p for p in self.projects if p.customer_id == customer_id]
        return []

    def filter_for(
        self, source: str, customer_id: str | None, project_id: str | None
    ) -> SourceFilter | None:
        """None: the case is not scoped. An empty filter: scoped, but nothing is
        mapped for this source, so it cannot be narrowed (the caller says so)."""
        if not (customer_id or project_id):
            return None
        projects = self._projects_in_scope(customer_id, project_id)
        customer = self.customer(
            customer_id or (projects[0].customer_id if projects else None)
        )
        f = SourceFilter()
        if source == "slack":
            f.channels = _clean([c for p in projects for c in p.slack_channel_ids])
        elif source == "jira":
            f.jira_projects = _clean(
                [
                    k
                    for p in projects
                    for k in [
                        *p.jira_projects,
                        *[t.rstrip("-") for t in p.ticket_prefixes],
                    ]
                ]
            )
            f.jira_labels = _clean([x for p in projects for x in p.jira_labels])
        elif source == "gmail":
            f.gmail_labels = _clean([x for p in projects for x in p.gmail_labels])
            if customer:
                f.gmail_domains = _clean(customer.email_domains)
        elif source == "confluence":
            f.confluence_spaces = _clean(
                [x for p in projects for x in p.confluence_spaces]
            )
        return f

    # ---- tagging a record ----------------------------------------------------------

    def classify(
        self,
        source: str,
        *,
        channel: str | None = None,
        jira_key: str | None = None,
        space: str | None = None,
        emails: list[str] | None = None,
        labels: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """(customer_id, project_id) for a record, from where it lives; None when unknown."""
        project: Project | None = None
        if source == "slack" and channel:
            project = next(
                (p for p in self.projects if channel in p.slack_channel_ids), None
            )
        elif source == "jira" and jira_key:
            prefix = jira_key.split("-")[0].upper()
            have = {x.lower() for x in labels or []}
            project = next(
                (
                    p
                    for p in self.projects
                    if prefix in [k.upper() for k in p.jira_projects]
                    or prefix in [t.rstrip("-").upper() for t in p.ticket_prefixes]
                ),
                None,
            ) or next(
                (p for p in self.projects if have & {x.lower() for x in p.jira_labels}),
                None,
            )
        elif source == "confluence" and space:
            project = next(
                (p for p in self.projects if space in p.confluence_spaces), None
            )
        if project:
            return project.customer_id, project.id
        if source == "gmail" and emails:
            domains = {e.rsplit("@", 1)[-1].lower() for e in emails if "@" in e}
            found = [
                c
                for c in self.customers
                if domains & {d.lower() for d in c.email_domains}
            ]
            if len(found) == 1:
                return found[0].id, None
        return None, None

    # ---- people --------------------------------------------------------------------

    def person_for(
        self,
        *,
        email: str | None = None,
        slack_id: str | None = None,
        jira_id: str | None = None,
        name: str | None = None,
    ) -> Person | None:
        """Match on a stable identifier first; a name alone is the weakest evidence."""
        for p in self.people:
            if email and email.lower() in [e.lower() for e in p.emails]:
                return p
            if slack_id and slack_id in p.slack_ids:
                return p
            if jira_id and jira_id in p.jira_account_ids:
                return p
        if name:
            wanted = _norm(name)
            hits = [
                p
                for p in self.people
                if wanted in [_norm(n) for n in [p.name, *p.aliases]]
            ]
            if len(hits) == 1:  # two people sharing a name is not a match
                return hits[0]
        return None
