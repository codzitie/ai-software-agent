"""Install a missing third-party package so the tests can run (asks the user first)."""
import re

from src.agents.common import install_gate
from src.state.graph_state import AgentState
from src.tools import installer
from src.tools.dependency import PIP_ALIASES

_PKG = re.compile(r"third-party package '([\w.-]+)'")


def _blocked(text: str) -> dict:
    return {"tester_status": "blocked", "tester_action": "blocked", "tester_report": text}


def resolve_env_node(state: AgentState) -> dict:
    root = state["repo_path"]
    records = [r for r in state.get("failure_records", []) if r["verdict"] == "environment"]
    pkgs = sorted({PIP_ALIASES.get(m.group(1), m.group(1))
                   for r in records if (m := _PKG.search(r["reason"]))})
    details = "\n".join(f"- {r['nodeid']}: {r['reason']}\n  {r['message'][:200]}" for r in records[:5])

    if not pkgs or state.get("tester_env_rounds", 0) >= 1:
        return _blocked("The tests could not run because of an environment problem:\n" + details)
    if not install_gate.ask(pkgs, "Needed to run the tests. This only installs; it does not edit "
                                  "requirements.txt or pyproject.toml.", root):
        return _blocked(f"The tests need {', '.join(pkgs)}, which was not approved for installation.")
    result = installer.install(root, pkgs)
    if not result.ok:
        return _blocked(f"Could not install {pkgs}:\n{result.output[-1000:]}")
    return {"tester_env_rounds": state.get("tester_env_rounds", 0) + 1, "tester_action": None}