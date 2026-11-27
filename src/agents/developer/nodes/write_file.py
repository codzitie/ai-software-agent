"""Deterministic: put the generated file or edits on disk."""
from src.state.graph_state import AgentState
from src.tools import code_modifier, file_writer
from src.utils.errors import ToolError


def write_file_node(state: AgentState) -> dict:
    root = state["repo_path"]
    gen = state.get("generated_file")

    if gen is not None:
        try:
            written = file_writer.write_files(root, {gen.path: gen.content})
        except ToolError as exc:
            return {"step_written": [], "backup_id": None,
                    "step_error": f"File could not be written: {exc}"}
        return {"step_written": written,
                "created_files": [*state.get("created_files", []), *written],
                "backup_id": None, "step_error": None}

    result = code_modifier.apply_edits(root, state["patch"].edits)
    if result.errors:
        return {"step_written": [], "backup_id": result.backup_id,
                "step_error": "Patch could not be applied:\n" + "\n".join(result.errors)}
    return {"step_written": [], "backup_id": result.backup_id, "step_error": None}