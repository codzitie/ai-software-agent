"""Deterministic: undo only the current step, then record why it failed."""
from src.state.graph_state import AgentState
from src.tools import code_modifier, file_writer, git_tool
from src.utils.errors import ToolError


def dev_prepare_retry_node(state: AgentState) -> dict:
    root = state["repo_path"]
    notes: list[str] = []

    try:
        if state.get("backup_id"):                       # edit to an existing file
            code_modifier.rollback(root, state["backup_id"])
        if state.get("step_written"):                    # file created by this step
            file_writer.remove_created(root, state["step_written"])
        if state.get("git_task") and state.get("last_good_sha"):
            git_tool.reset_to(root, state["last_good_sha"])   # also undoes manifest/format edits
    except (ToolError, OSError) as exc:
        notes.append(f"(cleanup warning: {exc})")

    created = state.get("created_files", [])
    written = set(state.get("step_written", []))
    return {
        "created_files": [p for p in created if p not in written],
        "step_written": [], "step_manifest": [], "pending_install": [],
        "backup_id": None, "step_error": None,
        "feedback": [*state.get("feedback", []),
                     "\n".join([state.get("step_error") or "unknown error", *notes])],
    }