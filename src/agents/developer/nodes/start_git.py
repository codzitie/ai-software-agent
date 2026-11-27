"""Deterministic: open a task branch so every step can be checkpointed and undone."""
from dataclasses import asdict
from pathlib import Path

from src.state.graph_state import AgentState
from src.tools import git_tool
from src.utils.errors import ToolError


def start_git_node(state: AgentState) -> dict:
    root = state.get("repo_path")
    if not root:
        return {"step_error": "No repository path was set.", "attempt": 99}

    base = Path(root)
    new_project = state.get("query_type") == "new_project"
    if new_project:
        if base.exists() and (not base.is_dir() or any(p.name != ".git" for p in base.iterdir())):
            return {"step_error": f"The folder is not empty, so a new project cannot be created in it: {root}",
                    "attempt": 99}
        base.mkdir(parents=True, exist_ok=True)

    if not git_tool.is_available():
        return {"git_task": None, "last_good_sha": None}

    try:
        if new_project:
            git_tool.init(root)
        if not git_tool.status(root).is_repo:
            return {"git_task": None, "last_good_sha": None}     # no checkpoints, backups only
        task = git_tool.start_task(root, state["dev_task"].summary)
    except ToolError as exc:
        return {"step_error": f"Could not start a git task: {exc}", "attempt": 99}

    return {"git_task": asdict(task), "last_good_sha": task.base_sha, "step_error": None}