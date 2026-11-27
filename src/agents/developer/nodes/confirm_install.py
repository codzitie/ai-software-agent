"""Pause and ask the user before installing packages. Does nothing when none are pending."""
from src.agents.common import install_gate
from src.agents.developer.context import pkg_key
from src.state.graph_state import AgentState


def confirm_install_node(state: AgentState) -> dict:
    packages = state.get("pending_install", [])
    if not packages:
        return {}
    planned = state["dev_task"].files[state.get("file_index", 0)]
    if install_gate.ask(packages, f"Needed by {planned.path}: {planned.purpose}", state["repo_path"]):
        return {}
    return {
        "pending_install": [],
        "declined_packages": sorted({*state.get("declined_packages", []), *(pkg_key(p) for p in packages)}),
        "step_error": f"The user declined to install {', '.join(packages)}. "
                      "Implement this without them, using the standard library or packages already available.",
    }