"""Conditional edges leaving the planner."""
from typing import Literal

from src.state.graph_state import AgentState
from src.utils.trace import route, traced_router

@traced_router("after_planner")
def route_after_planner(
    state: AgentState,
) -> Literal["codebase", "chat_reply", "unsupported"]:
    query_type = state.get("query_type")

    if query_type == "bug_fix":
        if not state.get("repo_path"):
            return "chat_reply"  # ask the user for the repo path
        return "codebase"

    if query_type == "new_project":
        return "unsupported"  # Developer Agent not built yet

    return "chat_reply"