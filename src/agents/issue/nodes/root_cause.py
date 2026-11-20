"""LLM node 2: find why the issue happens."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import RootCause
from src.tools import filesystem

MAX_FILE_CHARS = 6000


def root_cause_node(state: AgentState) -> dict:
    root = state["repo_path"]
    summary = state["codebase_summary"]
    report = state["issue_report"]

    files_text = "\n\n".join(
        f"### {n.path}\n{filesystem.read_file(root, n.path, max_chars=MAX_FILE_CHARS)}"
        for n in summary.relevant_files
    )

    llm = get_llm().with_structured_output(RootCause)
    cause: RootCause = llm.invoke(
        [
            SystemMessage(content=load_prompt("root_cause")),
            HumanMessage(
                content=(
                    f"Issue:\n{state['user_query']}\n\n"
                    f"Reproduction evidence:\n{report.evidence}\n\n"
                    f"Code:\n{files_text}\n\n"
                    "Identify the single file and the reason the bug happens."
                )
            ),
        ]
    )
    return {"root_cause": cause}