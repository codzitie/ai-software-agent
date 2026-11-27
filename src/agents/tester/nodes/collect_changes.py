"""Deterministic: find the changed functions, so tests target only them."""
from pathlib import Path

from src.agents.tester import context
from src.state.graph_state import AgentState

_RESET = {
    "test_plan": None, "test_queue": [], "tests_written": [], "test_generated": None,
    "tester_attempt": 0, "tester_error": None, "tester_feedback": [], "tester_step_written": [],
    "file_notes": {}, "failure_records": [], "tester_action": None, "test_summary": "",
    "test_fix_rounds": 0, "tester_env_rounds": 0, "coverage_gaps": "", "coverage_note": "",
    "coverage_rounds": 0, "coverage_declined": False, "tester_status": None, "tester_report": None,
}


def collect_changes_node(state: AgentState) -> dict:
    root = state["repo_path"]
    # After an implementation_bug the tests were kept: reuse them instead of planning again.
    kept = []
    if state.get("tester_status") == "implementation_bug":
        kept = [p for p in state.get("tests_written", []) if (Path(root) / p).is_file()]

    update = {**_RESET, "tests_written": kept}
    if not context.testable(context.compute_changes(state)):
        return {**update, "tester_status": "skipped",
                "tester_report": "No changed functions or classes needed new tests."}
    return update