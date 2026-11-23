"""LLM node 3: produce the code change as exact-text edits."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import Patch
from src.tools import filesystem

FULL_FILE_CHARS = 40000
WINDOW_RADIUS = 60
MAX_FEEDBACK_SHOWN=3

def generate_patch_node(state: AgentState) -> dict:
    root = state["repo_path"]
    cause = state["root_cause"]

    # Files are clean here: prepare_retry rolls back before we get back to this node.
    source, was_cut = filesystem.read_for_llm(root, cause.file, max_chars=FULL_FILE_CHARS)
    line = state.get("error_line")
    if was_cut and line:
        # Long file with a known error line: show the region around it instead.
        source = filesystem.read_window(root, cause.file, line, radius=WINDOW_RADIUS)
    feedback = state.get("feedback", [])[-MAX_FEEDBACK_SHOWN:]
    feedback_text = (
        "\n\n".join(f"Previous attempt {i + 1} failed:\n{f}" for i, f in enumerate(feedback))
        or "This is the first attempt."
    )

    llm = get_llm().with_structured_output(Patch)
    patch: Patch = llm.invoke(
        [
            SystemMessage(content=load_prompt("patch_generation")),
            HumanMessage(
                content=(
                    f"Issue:\n{state['user_query']}\n\n"
                    f"Known error from the syntax checker:\n{state.get('error_context') or 'none'}\n\n"
                    f"Current file content:\n{source}\n\n"
                    f"{feedback_text}\n\n"
                    "Return minimal edits. Every target_text must appear exactly once in the file."
                )
            ),
        ]
    )
    return {"patch": patch, "attempt": state.get("attempt", 0) + 1, "step_error": None}