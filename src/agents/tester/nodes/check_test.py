"""Deterministic: the test file must parse, import correctly and contain tests."""
import ast

from src.state.graph_state import AgentState
from src.tools import filesystem, import_checker
from src.utils.errors import ToolError


def check_test_node(state: AgentState) -> dict:
    root = state["repo_path"]
    written = state.get("tester_step_written", [])
    for rel in written:
        try:
            tree = ast.parse(filesystem.resolve_safe(root, rel).read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            line = exc.lineno or 1
            window = filesystem.read_window(root, rel, line, radius=4, numbered=True)
            return {"tester_error": f"Syntax error in {rel}, line {line}: {exc.msg}\n{window}"}
        except (OSError, UnicodeDecodeError, ToolError) as exc:
            return {"tester_error": f"Could not read {rel}: {exc}"}
        if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
                   for n in ast.walk(tree)):
            return {"tester_error": f"{rel} has no test functions (names must start with 'test')."}

    try:
        issues = import_checker.check_imports(root, written)
    except ToolError as exc:
        return {"tester_error": f"Import check failed: {exc}"}
    issues = [i for i in issues if "No module named 'pytest'" not in i.message]   # handled as environment
    if issues:
        return {"tester_error": "Import problems:\n"
                + "\n".join(f"{i.path}:{i.line}: {i.message}" for i in issues[:10])}
    return {"tester_error": None}