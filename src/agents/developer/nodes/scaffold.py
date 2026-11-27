"""Deterministic: create the skeleton of a NEW project in repo_path. Skipped for new_feature."""
from src.state.graph_state import AgentState
from src.tools import git_tool, project_inspector, scaffold
from src.utils.errors import ToolError


def scaffold_node(state: AgentState) -> dict:
    if state.get("query_type") != "new_project":
        return {}

    root = state.get("repo_path")
    task = state["dev_task"]
    if not task.project_name:
        return {"step_error": "The plan has no project_name for a new project.", "attempt": 99}

    try:
        # dependencies=[]: nothing may be installed before the user approves it.
        # They are recorded in the manifest after the confirmed install.
        created = scaffold.create(root, task.project_name,
                                  description=state["user_query"], layout=task.layout,
                                  dependencies=[])
        update = {"project_info": project_inspector.inspect(root), "created_files": created,
                  "touched_files": created, "step_error": None}
        if state.get("git_task"):
            sha = git_tool.commit(root, "Scaffold project", created)
            update["last_good_sha"] = sha or state.get("last_good_sha")
    except ToolError as exc:
        return {"step_error": f"Scaffold failed: {exc}", "attempt": 99}
    return update