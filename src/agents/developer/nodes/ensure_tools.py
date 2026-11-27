"""Ask once before installing ruff (a dev tool, not added to the project's dependencies)."""
from src.agents.common import install_gate
from src.state.graph_state import AgentState
from src.tools import formatter, installer


def ensure_tools_node(state: AgentState) -> dict:
    if state.get("tools_checked"):
        return {}
    root = state["repo_path"]
    if formatter.is_available(root):
        return {"format_enabled": True, "tools_checked": True}

    approved = install_gate.ask(
        ["ruff"], "Formats and lint-checks the new code. It is a development tool and "
                  "will not be added to the project's dependencies.", root)
    if not approved:
        return {"format_enabled": False, "tools_checked": True}
    result = installer.install(root, ["ruff"])
    return {"format_enabled": result.ok, "tools_checked": True}