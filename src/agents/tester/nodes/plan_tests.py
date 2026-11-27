"""LLM stage 1: decide which tests to write for the changed code."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.agents.tester import context
from src.agents.tester.context import render
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import TestPlan
from src.tools import diff_reader, project_inspector
from src.utils.errors import ToolError


def plan_tests_node(state: AgentState) -> dict:
    root = state["repo_path"]
    targets = context.testable(context.compute_changes(state))
    info = project_inspector.inspect(root)
    written = state.get("tests_written", [])

    system = render(
        load_prompt("test_plan"),
        task_description=context.task_description(state),
        test_framework=info.test_framework or "pytest",
        project_info=project_inspector.summarize(info),
        diff_summary=diff_reader.summarize(targets),
        changed_code=context.changed_code(root, targets),
        existing_tests=context.existing_tests(root, targets, exclude=written),
        coverage_gaps=state.get("coverage_gaps") or "none",
        step_error="",
    )
    plan: TestPlan = get_llm().with_structured_output(TestPlan).invoke(
        [SystemMessage(content=system), HumanMessage(content="Return the TestPlan.")]
    )
    if not plan.cases:
        return {"tester_error": "The test plan contained no test cases."}

    # Enforce file rules in code: valid path, never an existing file, one name per file.
    prev = state.get("test_plan")
    taken = set(written)
    rename: dict[str, str] = {}
    ids = {c.id for c in prev.cases} if prev else set()
    cases = []
    try:
        for case in plan.cases:
            rel = case.test_file.replace("\\", "/")
            rel = rel[2:] if rel.startswith("./") else rel
            if not rel.endswith(".py"):
                return {"tester_error": f"Planned test file is not a .py file: {case.test_file}"}
            if rel not in rename:
                rename[rel] = context.fresh_path(root, rel, taken | set(rename.values()))
            cid = case.id
            while cid in ids:
                cid += "_2"
            ids.add(cid)
            cases.append(case.model_copy(update={"test_file": rename[rel], "id": cid}))
    except ToolError as exc:
        return {"tester_error": f"Unsafe test path in the plan: {exc}"}

    new_plan = plan.model_copy(update={"cases": cases})
    queue = context.planned_files(new_plan)
    if prev:                                              # coverage round: keep the earlier cases
        new_plan = new_plan.model_copy(update={"cases": [*prev.cases, *cases]})
    return {"test_plan": new_plan, "test_queue": queue, "tester_attempt": 0,
            "tester_feedback": [], "tester_error": None}