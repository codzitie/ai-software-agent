"""Routing for the developer subgraph. Failure routing reuses the issue agent's on_step_result."""
from typing import Literal

from src.agents.issue.routing import on_step_result   # noqa: F401  (used by graph.py)
from src.state.graph_state import AgentState
from src.utils.trace import traced_router


@traced_router("after_start_git")
def route_after_start_git(state: AgentState) -> Literal["scaffold", "finalize"]:
    return "finalize" if state.get("step_error") else "scaffold"


@traced_router("after_scaffold")
def route_after_scaffold(state: AgentState) -> Literal["reconcile_plan", "finalize"]:
    return "finalize" if state.get("step_error") else "reconcile_plan"


@traced_router("after_reconcile")
def route_after_reconcile(state: AgentState) -> Literal["ensure_tools", "finalize"]:
    return "finalize" if state.get("step_error") else "ensure_tools"


@traced_router("after_tools")
def route_after_tools(state: AgentState) -> Literal["generate_file", "smoke_test"]:
    return "generate_file" if state["dev_task"].files else "smoke_test"


@traced_router("after_advance")
def route_after_advance(state: AgentState) -> Literal["generate_file", "smoke_test"]:
    more = state.get("file_index", 0) < len(state["dev_task"].files)
    return "generate_file" if more else "smoke_test"