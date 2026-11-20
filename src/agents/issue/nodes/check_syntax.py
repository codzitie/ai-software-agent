"""Deterministic: syntax-check every file the patch touched."""
from src.state.graph_state import AgentState
from src.tools import syntax_checker,filesystem


def check_syntax_node(state: AgentState) -> dict:
    files = sorted({e.file for e in state["patch"].edits})
    issues = syntax_checker.check_files(state["repo_path"], files)
    if issues:
        parts = []
        for i in issues[:3]:
            part = f"{i.path}:{i.line}: {i.message}"
            if i.line:
                part += "\n" + filesystem.read_window(
                    state["repo_path"], i.path, i.line, radius=6, numbered=True
                )
            parts.append(part)
        text = "\n\n".join(parts)
        return {"step_error": f"Syntax errors after patch:\n{text}"}
    return {"step_error": None}