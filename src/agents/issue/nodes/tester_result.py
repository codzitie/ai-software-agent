"""Deterministic: turn the Tester's verdict into the Issue Agent's retry signal."""
from src.state.graph_state import AgentState


def tester_result_node(state: AgentState) -> dict:
    status = state.get("tester_status")
    if status == "implementation_bug":
        # issue_status is cleared so a give-up after the retry limit is not reported as "fixed".
        return {"issue_status": None,
                "step_error": "The fix does not satisfy the new tests:\n" + (state.get("tester_report") or "")}
    return {"step_error": None}