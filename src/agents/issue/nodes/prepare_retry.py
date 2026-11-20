"""Deterministic: undo the failed patch and record why it failed."""
from src.state.graph_state import AgentState
from src.tools import code_modifier


def prepare_retry_node(state: AgentState) -> dict:
    if state.get("backup_id"):
        code_modifier.rollback(state["repo_path"], state["backup_id"])
    feedback = [*state.get("feedback", []), state["step_error"]]
    return {"feedback": feedback, "step_error": None, "backup_id": None}