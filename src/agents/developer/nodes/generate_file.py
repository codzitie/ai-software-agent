"""LLM stage 2: produce the next planned file (a new file or edits to an existing one)."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.agents.developer.context import dependency_sources, feedback_text, render, summary_text
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import GeneratedFile, Patch
from src.tools import filesystem, project_inspector

FULL_FILE_CHARS = 40000


def generate_file_node(state: AgentState) -> dict:
    task = state["dev_task"]
    planned = task.files[state.get("file_index", 0)]
    root = state["repo_path"]
    info = state.get("project_info")

    system = render(
        load_prompt("developer"),
        python_version=(info.python_version if info and info.python_version else "3.11+"),
        line_length=(info.line_length if info and info.line_length else 100),
        request=state["user_query"],
        task_description=task.summary,
        mode=state.get("query_type") or "new_feature",
        project_info=project_inspector.summarize(info) if info else "",
        codebase_summary=summary_text(state),
        created_files=", ".join(state.get("created_files", [])) or "none",
        step_error=state.get("step_error") or "",
    )
    feedback = feedback_text(state) or "This is the first attempt."
    built_on = dependency_sources(state, planned.depends_on) or "none"
    llm = get_llm()

    if planned.action == "create":
        human = (
            f"Run Stage 2A for this file.\nPath: {planned.path}\nPurpose: {planned.purpose}\n\n"
            f"Files this one builds on:\n{built_on}\n\n{feedback}"
        )
        gen: GeneratedFile = llm.with_structured_output(GeneratedFile).invoke(
            [SystemMessage(content=system), HumanMessage(content=human)]
        )
        gen.path = planned.path     # the plan decides the path, never the model
        return {"generated_file": gen, "patch": None,
                "attempt": state.get("attempt", 0) + 1, "step_error": None}

    source, _ = filesystem.read_for_llm(root, planned.path, max_chars=FULL_FILE_CHARS)
    human = (
        f"Run Stage 2B for this file.\nPath: {planned.path}\nPurpose: {planned.purpose}\n\n"
        f"Current file content:\n{source}\n\n"
        f"Files this one builds on:\n{built_on}\n\n{feedback}"
    )
    patch: Patch = llm.with_structured_output(Patch).invoke(
        [SystemMessage(content=system), HumanMessage(content=human)]
    )
    for edit in patch.edits:
        edit.file = planned.path
    return {"patch": patch, "generated_file": None,
            "attempt": state.get("attempt", 0) + 1, "step_error": None}