"""Deterministic: apply the edits, keep a backup."""
from src.state.graph_state import AgentState
from src.tools import code_modifier


def apply_patch_node(state: AgentState) -> dict:
    result = code_modifier.apply_edits(state["repo_path"], state["patch"].edits)
    if result.errors:
        # Typically "target_text not found" or "target_text not unique".
        return {
            "backup_id": result.backup_id,
            "step_error": "Patch could not be applied:\n" + "\n".join(result.errors),
        }
    return {"backup_id": result.backup_id, "step_error": None}