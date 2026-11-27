"""Planning Agent: classifies the query, builds a plan, allocates tasks to agents."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import Plan, Task

# Agents that exist right now. The tester runs automatically after the developer.
AVAILABLE_AGENTS = {"codebase", "issue", "developer", "tester"}


def _build_user_message(state: AgentState) -> str:
    repo = state.get("repo_path") or "none provided"
    return f"User request:\n{state['user_query']}\n\nRepository path: {repo}"


def planner_node(state: AgentState) -> dict:
    llm = get_llm().with_structured_output(Plan)
    plan: Plan = llm.invoke(
        [
            SystemMessage(content=load_prompt("planner")),
            HumanMessage(content=_build_user_message(state)),
        ]
    )

    agents = [t.agent for t in plan.tasks]
    # Bug fixes and features in an existing repo need repo understanding first.
    if plan.query_type in ("bug_fix", "new_feature") and "codebase" not in agents:
        plan.tasks.insert(0, Task(
            id=0, agent="codebase",
            description="Explore the repository and find files relevant to the request",
        ))
    if plan.query_type in ("new_project", "new_feature") and "developer" not in agents:
        plan.tasks.append(Task(id=len(plan.tasks) + 1, agent="developer",
                               description=state["user_query"]))

    skipped = [t for t in plan.tasks if t.agent not in AVAILABLE_AGENTS]
    plan.tasks = [t for t in plan.tasks if t.agent in AVAILABLE_AGENTS]

    return {"plan": plan, "query_type": plan.query_type, "skipped_tasks": skipped}