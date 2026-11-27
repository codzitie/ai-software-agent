"""Deterministic: the step passed every check, so checkpoint it."""
from src.agents.developer.context import step_files
from src.state.graph_state import AgentState
from src.tools import git_tool
from src.utils.errors import ToolError


def commit_step_node(state: AgentState) -> dict:
    root = state["repo_path"]
    planned = state["dev_task"].files[state.get("file_index", 0)]
    files = [*step_files(state), *state.get("step_manifest", [])]

    backups = list(state.get("applied_backups", []))
    if state.get("backup_id"):
        backups.append(state["backup_id"])
    update = {"touched_files": sorted({*state.get("touched_files", []), *files}),
              "applied_backups": backups, "step_error": None}

    if state.get("git_task"):
        try:
            sha = git_tool.commit(root, f"{planned.action.capitalize()} {planned.path}: {planned.purpose}", files)
        except ToolError as exc:
            return {"step_error": f"Commit failed: {exc}"}
        if sha:
            update["last_good_sha"] = sha
    return update