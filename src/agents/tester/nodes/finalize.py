"""Deterministic: set the Tester's status and report. Cleans up tests it could not make work."""
from langchain_core.messages import AIMessage

from src.state.graph_state import AgentState
from src.tools import file_writer, git_tool
from src.utils.errors import ToolError


def _impl_lines(records: list[dict]) -> str:
    rows = [f"- {r['nodeid']}: {r['error_type'] or 'error'} at {r['crash_file']}:{r['crash_line']}\n"
            f"  {r['message'][:300]}\n  ({r['reason']})"
            for r in records if r["verdict"] == "implementation_bug"]
    return "\n".join(rows[:6])[:2500]


def _status(state: AgentState) -> str:
    if state.get("tester_status"):
        return state["tester_status"]                  # skipped / blocked, set earlier
    if state.get("tester_error"):
        return "failed"
    action = state.get("tester_action")
    if action == "fix_implementation":
        return "implementation_bug"
    if action in ("fix_tests", "no_tests", "review_ambiguous"):
        return "failed"
    return "passed"


def finalize_node(state: AgentState) -> dict:
    root, written = state["repo_path"], state.get("tests_written", [])
    status = _status(state)
    notes: list[str] = []

    if status in ("failed", "blocked") and written:    # tests we could not make work: leave no trace
        try:
            file_writer.remove_created(root, written)
            written = []
        except (ToolError, OSError) as exc:
            notes.append(f"Could not remove the test files: {exc}")

    if status == "passed":
        report = (f"Tests: {len(written)} new test file(s): {', '.join(written)}\n"
                  f"Result: {state.get('test_summary', '')}")
        if state.get("coverage_note"):
            report += "\n" + state["coverage_note"]
        if written and state.get("git_task"):
            try:
                git_tool.commit(root, "Add tests for the change", written)
            except ToolError as exc:
                notes.append(f"Tests were written but not committed: {exc}")
    elif status == "implementation_bug":
        report = ("The new tests found problems in the implementation:\n" + _impl_lines(state.get("failure_records", [])))
    elif status == "failed":
        report = ("I could not produce working tests.\n"
                  f"{state.get('tester_error') or state.get('test_summary', '')}")
    else:                                              # skipped / blocked
        report = state.get("tester_report") or ""
    report = "\n".join([report, *notes]).strip()

    update: dict = {"tester_status": status, "tester_report": report, "tests_written": written}
    if state.get("dev_status") == "done":              # Developer flow: one combined final reply
        update["messages"] = [AIMessage(content=f"{state.get('dev_report', '')}\n\n{report}".strip())]
    return update