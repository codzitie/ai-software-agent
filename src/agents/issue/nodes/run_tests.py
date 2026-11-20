"""Deterministic: re-run the reproduction command (or the repo's tests)."""
from src.state.graph_state import AgentState
from src.tools import test_runner


def run_tests_node(state: AgentState) -> dict:
    command = state["issue_report"].repro_command  # None -> runner auto-detects suite
    result = test_runner.run(state["repo_path"], command, timeout=300)
    if result.passed:
        return {"step_error": None, "issue_status": "fixed"}
    return {"step_error": f"Tests still failing:\n{result.output[-2000:]}"}