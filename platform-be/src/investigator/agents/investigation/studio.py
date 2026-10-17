"""Entry point for `langgraph dev` (development only).

Input: {"question": "..."}. Needs LITELLM_API_KEY. Real sources need a user's
stored OAuth connection, which only the API process has, so Studio runs with no
connectors and reports no evidence rather than inventing any. Studio provides its
own checkpointer, which the human checkpoints need.
"""

from __future__ import annotations

from typing import Any

from investigator.agents.investigation.graph import Deps, build_graph
from investigator.llm import get_llm_client
from investigator.tools import AccessContext


def graph() -> Any:
    access = AccessContext(user_id="studio")
    return build_graph(Deps(llm=get_llm_client(), default_access=access))
