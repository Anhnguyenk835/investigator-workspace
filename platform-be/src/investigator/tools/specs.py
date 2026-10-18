"""The tool pool the model may call. All read-only; none take user or permission arguments."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class SearchRecordsArgs(BaseModel):
    source: str
    query: str = Field(min_length=1, max_length=300)
    date_from: date | None = None
    date_to: date | None = None
    cursor: str | None = None
    # Where in the source to look (channel, label, project or space ids from list_scopes).
    # Only a conversation offers it: an investigation's scope is chosen by its person.
    scope: list[str] = Field(default_factory=list, max_length=20)


class ListScopesArgs(BaseModel):
    source: str
    # Keeps only the channels, labels, projects or spaces whose id or name contains this.
    contains: str = Field(default="", max_length=100)


class GetRecordArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=200)


class GetThreadArgs(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)


TOOL_ARGS: dict[str, type[BaseModel]] = {
    "search_records": SearchRecordsArgs,
    "get_record": GetRecordArgs,
    "get_thread": GetThreadArgs,
    "list_scopes": ListScopesArgs,
}

# Offered only where a person is choosing where to look (a conversation), not to the
# investigation's own agent, whose scope the person already set.
SCOPE_TOOLS = frozenset({"list_scopes"})

DESCRIPTIONS = {
    "search_records": (
        "Search one connected source. Returns records plus a status. A NO_MATCHES result "
        "is not proof that nothing exists. Use `cursor` from a previous result to page."
    ),
    "get_record": "Fetch the full content of a record already seen in this investigation, by its id.",
    "get_thread": (
        "Fetch every message/comment of a thread already seen in this investigation, "
        "by a thread_id shown on a record."
    ),
    "list_scopes": (
        "List the parts of one connected source a search can be limited to: Slack channels, "
        "Gmail labels, Jira projects or Confluence spaces. Returns ids and names. Pass the "
        "ids as `scope` to search_records."
    ),
}

SCOPE_DESCRIPTION = (
    "Limit the search to these channels, labels, projects or spaces: ids (or names) "
    "returned by list_scopes. Leave empty to search the case as scoped."
)


def openai_tools(sources: list[str], scoped: bool = False) -> list[dict[str, Any]]:
    """Tool schemas for the model. `source` is an enum of what this user may read.
    `scoped` adds list_scopes and the `scope` argument of search_records."""
    tools: list[dict[str, Any]] = []
    for name, model in TOOL_ARGS.items():
        if name in SCOPE_TOOLS and not scoped:
            continue
        schema = model.model_json_schema()
        schema.pop("title", None)
        if name == "search_records":
            if scoped:
                schema["properties"]["scope"] = {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": SCOPE_DESCRIPTION,
                }
            else:
                schema["properties"].pop("scope", None)
        if "source" in schema.get("properties", {}):
            schema["properties"]["source"] = {
                "type": "string",
                "enum": sources,
                "description": "Connected source to search.",
            }
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": DESCRIPTIONS[name],
                    "parameters": schema,
                },
            }
        )
    return tools
