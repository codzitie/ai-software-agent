"""Planning Agent: classifies the query, builds a plan, allocates tasks to agents."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import Plan
from src.state.schemas import Plan, Task

# Agents that exist right now. Update this set as new agents are built.
AVAILABLE_AGENTS = {"codebase", "issue"}


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

    # Bug fixes always need repo understanding before the Issue Agent runs.
    if plan.query_type == "bug_fix":
        agents_in_plan = [t.agent for t in plan.tasks]
        if "codebase" not in agents_in_plan:
            plan.tasks.insert(0, type(plan.tasks[0])(
                id=0, agent="codebase",
                description="Explore the repository and find files relevant to the issue",
            ))

    # Drop tasks for agents that are not built yet; remember what was skipped.
    skipped = [t for t in plan.tasks if t.agent not in AVAILABLE_AGENTS]
    plan.tasks = [t for t in plan.tasks if t.agent in AVAILABLE_AGENTS]

    return {
        "plan": plan,
        "query_type": plan.query_type,
        "skipped_tasks": skipped,
    }