"""Deterministic: describe the repository so the plan follows its conventions."""
from pathlib import Path

from src.state.graph_state import AgentState
from src.tools import project_inspector

_RESET = {
    "created_files": [], "step_written": [], "step_manifest": [], "touched_files": [],
    "applied_backups": [], "installed_packages": [], "declined_packages": [],
    "pending_install": [], "file_index": 0, "attempt": 0, "feedback": [],
    "step_error": None, "backup_id": None, "generated_file": None, "patch": None,
    "git_task": None, "last_good_sha": None, "tools_checked": False,
    "format_enabled": False, "dev_status": None, "dev_report": None,
}


def inspect_project_node(state: AgentState) -> dict:
    root = state.get("repo_path")
    if root and Path(root).is_dir():
        return {**_RESET, "project_info": project_inspector.inspect(root)}
    return {**_RESET, "project_info": None}      # new project, folder not created yet