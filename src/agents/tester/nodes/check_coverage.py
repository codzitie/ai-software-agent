"""Deterministic: were the changed lines executed? Asks before installing coverage."""
from config import settings
from src.agents.common import install_gate
from src.agents.tester import context
from src.state.graph_state import AgentState
from src.tools import coverage_tool, installer


def check_coverage_node(state: AgentState) -> dict:
    root = state["repo_path"]
    changes = context.testable(context.compute_changes(state))
    if not changes or state.get("coverage_declined"):
        return {"coverage_gaps": ""}

    if not coverage_tool.is_available(root):
        approved = install_gate.ask(
            ["coverage"], "Measures whether the tests execute the changed code. It is a development "
                          "tool and is not added to the project's dependencies.", root)
        result = installer.install(root, ["coverage"]) if approved else None
        if not (result and result.ok):
            return {"coverage_declined": True, "coverage_gaps": "",
                    "coverage_note": "Coverage check skipped (coverage was not installed)."}

    report = coverage_tool.check_changed(root, changes, "pytest -q --tb=short", timeout=300)
    note = coverage_tool.summarize(report)
    target = getattr(settings, "TESTER_COVERAGE_TARGET", 80)
    enough = (not report.available or not report.tests_ran
              or (all(f.measured for f in report.files)
                  and (report.overall is None or report.overall >= target)))
    if enough:
        return {"coverage_note": note, "coverage_gaps": ""}
    return {"coverage_note": note, "coverage_gaps": note,
            "coverage_rounds": state.get("coverage_rounds", 0) + 1}