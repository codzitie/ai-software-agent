"""Deterministic: find imports that do not resolve and decide which need an install."""
import re

from src.agents.developer.context import pkg_key, step_files
from src.state.graph_state import AgentState
from src.tools import import_checker
from src.tools.dependency import PIP_ALIASES
from src.utils.errors import ToolError

_MISSING = re.compile(r"No module named '([^']+)'")
_QUOTED = re.compile(r"'([^']+)'")


def _forward_ref(message: str, pending: set[str]) -> bool:
    """True when the import points at a file that is planned but not written yet."""
    quoted = _QUOTED.findall(message)
    if not quoted:
        return False
    if message.startswith("Cannot import name") and len(quoted) >= 2:
        name, module = quoted[0], quoted[1]
    else:
        name, module = None, quoted[0]
    base = module.lstrip(".").replace(".", "/")
    cands = {base} | ({f"{base}/{name}".strip("/")} if name else set())
    cands.discard("")
    return any(p.endswith((f"{c}.py", f"{c}/__init__.py")) for c in cands for p in pending)


def check_imports_node(state: AgentState) -> dict:
    root, task = state["repo_path"], state["dev_task"]
    files = [f for f in step_files(state) if f.endswith(".py")]
    if not files:
        return {"pending_install": [], "step_error": None}
    try:
        issues = import_checker.check_imports(root, files)
    except ToolError as exc:
        return {"step_error": f"Import check failed: {exc}"}

    pending = {f.path for f in task.files[state.get("file_index", 0) + 1:]}
    planned = {pkg_key(d): d for d in task.dependencies}
    declined = set(state.get("declined_packages", []))

    third: dict[str, list] = {}
    errors: list[str] = []
    for issue in issues:
        m = _MISSING.search(issue.message)
        if m:
            top = m.group(1).split(".")[0]
            third.setdefault(PIP_ALIASES.get(top, top), []).append(issue)
        elif not _forward_ref(issue.message, pending):
            errors.append(f"{issue.path}:{issue.line}: {issue.message}")

    for pip, found in third.items():
        first = found[0]
        if pkg_key(pip) in declined:
            errors.append(f"{first.path}:{first.line}: the user declined '{pip}'. Do not use it.")
        elif pkg_key(pip) not in planned:
            errors.append(f"{first.path}:{first.line}: imports '{pip}', which is not standard library, "
                          "not local and not in the plan's dependencies. Remove it or use the standard library.")

    if errors:
        return {"step_error": "Import problems:\n" + "\n".join(errors[:10]), "pending_install": []}
    return {"pending_install": [planned[pkg_key(p)] for p in sorted(third)], "step_error": None}