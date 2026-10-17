"""How graph state is serialized into the Postgres checkpointer.

LangGraph only revives classes it has been told about; anything else is warned
about now and will be refused in a future version. The state holds our own
pydantic models, so they are allowed by name, and nothing else is."""

from __future__ import annotations

import importlib
import inspect

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

# Modules whose pydantic models can appear in the investigation state.
STATE_MODULES = (
    "investigator.agents.investigation.schemas",
    "investigator.agents.investigation.state",
    "investigator.connectors.base",
    "investigator.tools.harness",
    "investigator.llm.client",
)


def _state_models() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name in STATE_MODULES:
        module = importlib.import_module(name)
        for cls_name, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseModel) and cls.__module__ == name:
                out.append((name, cls_name))
    return out


def checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_state_models())
