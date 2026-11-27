"""LLM stage 1: decide which files to create or edit."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.agents.developer.context import render, summary_text
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import DevTask
from src.tools import project_inspector


def plan_dev_node(state: AgentState) -> dict:
    info = state.get("project_info")
    task_desc = next(
        (t.description for t in (state.get("plan").tasks if state.get("plan") else [])
         if t.agent == "developer"),
        state["user_query"],
    )
    system = render(
        load_prompt("developer"),
        python_version=(info.python_version if info and info.python_version else "3.11+"),
        line_length=(info.line_length if info and info.line_length else 100),
        request=state["user_query"],
        task_description=task_desc,
        mode=state.get("query_type") or "new_feature",
        project_info=project_inspector.summarize(info) if info else "New project: nothing exists yet.",
        codebase_summary=summary_text(state),
        created_files="none yet",
        step_error="",
    )
    llm = get_llm().with_structured_output(DevTask)
    dev_task: DevTask = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content="Run Stage 1 and return the DevTask."),
    ])
    return {"dev_task": dev_task, "step_error": None}