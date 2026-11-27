"""Conditional edges leaving the planner."""
from pathlib import Path
from typing import Literal

from src.state.graph_state import AgentState
from src.utils.trace import traced_router


def _repo_exists(state: AgentState) -> bool:
    repo = state.get("repo_path")
    return bool(repo) and Path(repo).is_dir()


@traced_router("after_planner")
def route_after_planner(state: AgentState) -> Literal["codebase", "developer", "chat_reply"]:
    query_type = state.get("query_type")

    if query_type in ("bug_fix", "new_feature"):
        return "codebase" if _repo_exists(state) else "chat_reply"   # chat_reply explains what is missing
    if query_type == "new_project":
        return "developer" if state.get("repo_path") else "chat_reply"  # folder may not exist yet
    return "chat_reply"