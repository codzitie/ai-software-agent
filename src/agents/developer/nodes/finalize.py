"""Deterministic: report success, or undo everything and report why."""
from langchain_core.messages import AIMessage

from src.state.graph_state import AgentState
from src.tools import code_modifier, file_writer, git_tool
from src.utils.errors import ToolError


def _cleanup(state: AgentState) -> list[str]:
    root, notes = state["repo_path"], []
    try:
        if state.get("backup_id"):
            code_modifier.rollback(root, state["backup_id"])
        if state.get("step_written"):
            file_writer.remove_created(root, state["step_written"])
        if state.get("git_task"):
            git_tool.abandon_task(root, git_tool.TaskBranch(**state["git_task"]))
        else:
            for bid in reversed(state.get("applied_backups", [])):
                code_modifier.rollback(root, bid)
            if state.get("created_files"):
                file_writer.remove_created(root, state["created_files"])
    except (ToolError, OSError) as exc:
        notes.append(f"Rollback was incomplete: {exc}. Please check the repository by hand.")
    return notes


def finalize_node(state: AgentState) -> dict:
    task = state.get("dev_task")
    error = state.get("step_error")

    if error:
        notes = _cleanup(state)
        report = ("I could not complete this change, so I rolled everything back.\n\n"
                  f"Last error:\n{error[-1500:]}\n" + "\n".join(notes))
        return {"dev_status": "failed", "dev_report": report, "step_error": None,
                "messages": [AIMessage(content=report)]}

    created = state.get("created_files", [])
    edited = [p for p in state.get("touched_files", []) if p not in created and p.endswith(".py")]
    lines = [task.summary if task else "Done.", ""]
    if created:
        lines.append("Created: " + ", ".join(created))
    if edited:
        lines.append("Edited: " + ", ".join(edited))
    if state.get("installed_packages"):
        lines.append("Installed and recorded: " + ", ".join(state["installed_packages"]))
    if state.get("git_task"):
        g = state["git_task"]
        lines.append(f"\nThe work is on git branch `{g['branch']}`"
                     + (f", started from `{g['base_branch']}`" if g.get("base_branch") else "")
                     + ". Nothing was merged or pushed.")
    report = "\n".join(lines)
    return {"dev_status": "done", "dev_report": report,
            "messages": [AIMessage(content=report)]}