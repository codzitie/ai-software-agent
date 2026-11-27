"""Deterministic: install the approved packages, then record them in the manifest."""
from src.state.graph_state import AgentState
from src.tools import installer, manifest


def install_packages_node(state: AgentState) -> dict:
    packages = state.get("pending_install", [])
    if not packages:
        return {}
    root = state["repo_path"]

    result = installer.install(root, packages)
    if not result.ok:
        return {"pending_install": [],
                "step_error": f"Could not install {packages}:\n{result.output[-1500:]}"}

    recorded = manifest.record_dependencies(root, packages, pin="min")
    if not recorded.ok:
        manifest.undo(root, recorded)
        return {"pending_install": [],
                "step_error": "Could not record dependencies:\n" + "\n".join(recorded.errors)}

    newly_listed = recorded.added or packages
    return {
        "pending_install": [],
        "step_manifest": sorted({*state.get("step_manifest", []), *recorded.files}),
        "installed_packages": [*state.get("installed_packages", []), *newly_listed],
        "step_error": None,
    }