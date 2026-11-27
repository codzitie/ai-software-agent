"""LLM stage 2: write the next planned test file."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.agents.tester import context
from src.agents.tester.context import render
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import GeneratedFile
from src.tools import project_inspector


def generate_test_node(state: AgentState) -> dict:
    root, plan = state["repo_path"], state["test_plan"]
    target = state["test_queue"][0]
    targets = context.testable(context.compute_changes(state))
    info = project_inspector.inspect(root)

    notes = state.get("file_notes", {}).get(target, "")
    previous = "\n\n".join(x for x in (notes, context.feedback_text(state)) if x)
    system = render(
        load_prompt("tester"),
        python_version=info.python_version or "3.11+",
        test_framework=info.test_framework or "pytest",
        dependencies=", ".join(info.dependencies) or "none",
        task_description=context.task_description(state),
        test_plan=context.cases_json(plan, target),
        changed_code=context.changed_code(root, targets),
        existing_tests=context.existing_tests(root, targets, exclude=state.get("tests_written", [])),
        project_info=project_inspector.summarize(info),
        step_error=previous,
    )
    gen: GeneratedFile = get_llm().with_structured_output(GeneratedFile).invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"Run Stage 2 for this test file.\nPath: {target}"),
    ])
    gen.path = target                         # the plan decides the path, never the model
    return {"test_generated": gen, "tester_attempt": state.get("tester_attempt", 0) + 1,
            "tester_error": None}