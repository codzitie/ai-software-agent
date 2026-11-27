"""Deterministic: make the plan match the disk (scaffold output, wrong create/edit choices)."""
from src.state.graph_state import AgentState
from src.tools import filesystem
from src.utils.errors import ToolError


def reconcile_plan_node(state: AgentState) -> dict:
    root, task = state["repo_path"], state["dev_task"]
    seen: set[str] = set()
    files = []
    for f in task.files:
        try:
            path = filesystem.resolve_safe(root, f.path)
        except ToolError as exc:
            return {"step_error": f"The plan contains an unsafe path: {exc}", "attempt": 99}
        rel = path.relative_to(filesystem.resolve_safe(root, ".")).as_posix()
        if rel in seen:
            continue
        seen.add(rel)
        action = "edit" if path.is_file() else "create"     # disk is the truth
        files.append(f.model_copy(update={"path": rel, "action": action}))
    return {"dev_task": task.model_copy(update={"files": files}), "step_error": None}