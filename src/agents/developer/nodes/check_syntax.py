"""Deterministic: the files this step wrote must parse."""
import ast

from src.agents.developer.context import step_files
from src.state.graph_state import AgentState
from src.tools import filesystem
from src.utils.errors import ToolError


def check_syntax_node(state: AgentState) -> dict:
    root = state["repo_path"]
    for rel in step_files(state):
        if not rel.endswith(".py"):
            continue
        try:
            source = filesystem.resolve_safe(root, rel).read_text(encoding="utf-8")
            ast.parse(source, filename=rel)
        except SyntaxError as exc:
            line = exc.lineno or 1
            window = filesystem.read_window(root, rel, line, radius=4, numbered=True)
            return {"step_error": f"Syntax error in {rel}, line {line}: {exc.msg}\n{window}"}
        except (OSError, UnicodeDecodeError, ToolError) as exc:
            return {"step_error": f"Could not read {rel}: {exc}"}
    return {"step_error": None}