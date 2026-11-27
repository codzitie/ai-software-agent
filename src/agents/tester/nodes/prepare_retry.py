"""Deterministic: delete the test file that failed its checks and record why."""
from src.state.graph_state import AgentState
from src.tools import file_writer
from src.utils.errors import ToolError


def tester_prepare_retry_node(state: AgentState) -> dict:
    written = state.get("tester_step_written", [])
    note = ""
    if written:
        try:
            file_writer.remove_created(state["repo_path"], written)
        except (ToolError, OSError) as exc:
            note = f"\n(cleanup warning: {exc})"
    return {
        "tests_written": [p for p in state.get("tests_written", []) if p not in written],
        "tester_step_written": [], "test_generated": None, "tester_error": None,
        "tester_feedback": [*state.get("tester_feedback", []),
                            (state.get("tester_error") or "unknown error") + note],
    }