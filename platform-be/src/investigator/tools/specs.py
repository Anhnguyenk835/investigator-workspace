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


class GetRecordArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=200)


class GetThreadArgs(BaseModel):
    thread_id: str = Field(min_length=1, max_length=200)


TOOL_ARGS: dict[str, type[BaseModel]] = {
    "search_records": SearchRecordsArgs,
    "get_record": GetRecordArgs,
    "get_thread": GetThreadArgs,
}

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
}


def openai_tools(sources: list[str]) -> list[dict[str, Any]]:
    """Tool schemas for the model. `source` is an enum of what this user may read."""
    tools: list[dict[str, Any]] = []
    for name, model in TOOL_ARGS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
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
