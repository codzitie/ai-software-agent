"""LLM stage 3: decide test bug vs implementation bug for failures the parser could not classify."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.agents.tester import context
from src.agents.tester.context import render
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import TestDiagnosis
from src.tools import filesystem, project_inspector
from src.utils.errors import ToolError

MAX_DIAGNOSES = 5


def diagnose_node(state: AgentState) -> dict:
    root, plan = state["repo_path"], state.get("test_plan")
    targets = context.testable(context.compute_changes(state))
    info = project_inspector.inspect(root)
    code = context.changed_code(root, targets)
    records = [dict(r) for r in state.get("failure_records", [])]
    llm = get_llm().with_structured_output(TestDiagnosis)
    done = 0

    for r in records:
        if r["verdict"] != "ambiguous":
            continue
        if done >= MAX_DIAGNOSES:
            r.update(verdict="test_bug", confidence="low",
                     reason=r["reason"] + " (not diagnosed: too many failures; fix the test first)")
            continue
        try:
            test_src, _ = filesystem.read_for_llm(root, r["file"], max_chars=6000)
        except (ToolError, FileNotFoundError):
            test_src = "(test source unavailable)"
        system = render(
            load_prompt("tester"),
            python_version=info.python_version or "3.11+",
            test_framework=info.test_framework or "pytest",
            dependencies=", ".join(info.dependencies) or "none",
            task_description=context.task_description(state),
            test_plan=context.cases_json(plan, r["file"]) if plan else "none",
            changed_code=code, existing_tests="", project_info=project_inspector.summarize(info),
            step_error="",
        )
        human = (
            "Run Stage 3 for this failure and return the TestDiagnosis.\n\n"
            f"Failing test: {r['nodeid']}\nError: {r['error_type']}\nMessage:\n{r['message']}\n\n"
            f"Parser note: {r['reason']}\n\nTraceback:\n{r['traceback'][-1500:]}\n\n"
            f"Test file:\n{test_src}"
        )
        d: TestDiagnosis = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        r.update(verdict=d.verdict, confidence=d.confidence, reason=d.reason, fix_hint=d.fix_hint)
        done += 1

    return {"failure_records": records, "tester_action": context.action_for(records)}