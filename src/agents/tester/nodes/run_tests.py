"""Deterministic: run the new tests, then the whole suite for regressions, and classify failures."""
import shlex
from dataclasses import asdict

from src.agents.tester import context
from src.state.graph_state import AgentState
from src.tools import test_runner
from src.tools.test_result_parser import parse_pytest_output
from src.utils.errors import UnsafeCommandError

TIMEOUT = 300
_BASE = "pytest -q --tb=short"


def _blocked(text: str) -> dict:
    return {"tester_status": "blocked", "tester_action": "blocked", "tester_report": text}


def run_tests_node(state: AgentState) -> dict:
    root = state["repo_path"]
    written = state.get("tests_written", [])
    changed = [c.path for c in context.compute_changes(state)]
    ctx = dict(root=str(root), changed_files=changed, new_test_files=written)

    try:
        command = _BASE + "".join(" " + shlex.quote(p) for p in written)
        result = test_runner.run(root, command, timeout=TIMEOUT)
        if result.exit_code is None:
            return _blocked(f"The tests did not finish:\n{result.output[-1500:]}")
        parsed = parse_pytest_output(result.output, result.exit_code, **ctx)

        if parsed.ok and written:                      # new tests pass: check for regressions
            full = test_runner.run(root, _BASE, timeout=TIMEOUT)
            if full.exit_code is None:
                return _blocked(f"The full test suite did not finish:\n{full.output[-1500:]}")
            parsed_full = parse_pytest_output(full.output, full.exit_code, **ctx)
            parsed = parsed_full if not parsed_full.ok else parsed
    except UnsafeCommandError as exc:
        return _blocked(f"The test command was blocked: {exc}")

    return {
        "tester_action": parsed.primary_action,
        "failure_records": [{**asdict(f), "fix_hint": ""} for f in parsed.failures],
        "test_summary": parsed.summary(),
        "tester_error": None,
    }