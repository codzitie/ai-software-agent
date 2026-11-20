"""Routing for the issue subgraph."""
from typing import Literal

from config.settings import MAX_PATCH_ATTEMPTS
from src.state.graph_state import AgentState
from src.utils.trace import route, traced_router


@traced_router("after_verify")  
def route_after_verify(state: AgentState) -> Literal["find_root_cause", "finalize"]:
    return "find_root_cause" if state["issue_report"].reproducible else "finalize"


def on_step_result(current: str, next_node: str):
    """Return a router: continue on success, retry on failure, give up at the limit."""

    def router(state: AgentState) -> str:
        err = state.get("step_error")
        if not err:
            route(f"after_{current}", next_node, "step ok")
            return next_node
        if state.get("attempt", 0) >= MAX_PATCH_ATTEMPTS:
            route("retry_limit", "finalize", f"attempt {state.get('attempt')}: {err[:200]}")
            return "finalize"
        route("retry", "prepare_retry", err[:200])
        return "prepare_retry"

    return router

