"""Deterministic: step finished, move to the next planned file."""
from src.state.graph_state import AgentState


def advance_node(state: AgentState) -> dict:
    return {
        "file_index": state.get("file_index", 0) + 1,
        "attempt": 0, "feedback": [], "step_error": None,
        "step_written": [], "step_manifest": [], "pending_install": [],
        "backup_id": None, "generated_file": None, "patch": None,
    }