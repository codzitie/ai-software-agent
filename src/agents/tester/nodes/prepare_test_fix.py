"""Deterministic: delete the faulty NEW test files and queue them to be written again."""
from src.agents.tester import context
from src.state.graph_state import AgentState
from src.tools import file_writer
from src.utils.errors import ToolError


def _match(failing: str, written: list[str]) -> str | None:
    return next((w for w in written if failing == w or failing.endswith("/" + w) or w.endswith("/" + failing)), None)


def prepare_test_fix_node(state: AgentState) -> dict:
    root, written = state["repo_path"], state.get("tests_written", [])
    notes: dict[str, list[str]] = {}
    for r in state.get("failure_records", []):
        if r["verdict"] != "test_bug":
            continue
        hit = _match(r["file"], written)
        if hit:
            notes.setdefault(hit, []).append(
                f"{r['nodeid']}: {r['error_type']}: {r['message'][:400]}\n"
                f"Why it is a test problem: {r['reason']} {r.get('fix_hint', '')}".strip())
    if not notes and state.get("tester_action") == "no_tests":
        notes = {w: ["pytest collected no tests from this file; check test function names."] for w in written}
    if not notes:
        return {"tester_status": "blocked", "tester_action": "blocked",
                "tester_report": "The failing tests already existed before this change, so I did not "
                                 "modify them:\n" + state.get("test_summary", "")}

    bad = list(notes)
    try:
        file_writer.remove_created(root, bad)
    except (ToolError, OSError) as exc:
        return {"tester_status": "blocked", "tester_action": "blocked",
                "tester_report": f"Could not remove the faulty test files: {exc}"}

    plan = state.get("test_plan")
    order = context.planned_files(plan) if plan else []
    return {
        "tests_written": [w for w in written if w not in bad],
        "test_queue": [f for f in order if f in bad] + [f for f in bad if f not in order],
        "file_notes": {f: "\n\n".join(n) for f, n in notes.items()},
        "test_fix_rounds": state.get("test_fix_rounds", 0) + 1,
        "tester_attempt": 0, "tester_feedback": [], "tester_action": None,
        "failure_records": [], "tester_error": None,
    }