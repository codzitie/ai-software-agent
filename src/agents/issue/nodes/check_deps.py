"""Deterministic: install any new imports the patch introduced."""
from src.state.graph_state import AgentState
from src.tools import dependency, installer


def check_deps_node(state: AgentState) -> dict:
    root = state["repo_path"]
    files = sorted({e.file for e in state["patch"].edits})

    missing = dependency.find_missing(root, files)
    if not missing:
        return {"step_error": None}

    result = installer.install(root, missing)
    if not result.ok:
        return {
            "step_error": f"Could not install {missing}:\n{result.output[-1500:]}"
        }
    return {"step_error": None}