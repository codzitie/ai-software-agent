"""Deterministic: write the generated test file (new files only)."""
from src.state.graph_state import AgentState
from src.tools import file_writer
from src.utils.errors import ToolError


def write_test_node(state: AgentState) -> dict:
    gen = state["test_generated"]
    try:
        written = file_writer.write_files(state["repo_path"], {gen.path: gen.content})
    except ToolError as exc:
        return {"tester_step_written": [], "tester_error": f"Test file could not be written: {exc}"}
    return {"tester_step_written": written,
            "tests_written": [*state.get("tests_written", []), *written],
            "tester_error": None}