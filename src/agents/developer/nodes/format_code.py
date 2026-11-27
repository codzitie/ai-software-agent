"""Deterministic: format and lint NEW files only (existing files keep their style)."""
from src.state.graph_state import AgentState
from src.tools import formatter

_BLOCKING = ("F821", "F822", "F823")      # undefined names would crash at runtime


def format_code_node(state: AgentState) -> dict:
    if not state.get("format_enabled"):
        return {}
    files = [p for p in state.get("step_written", []) if p.endswith(".py")]
    if not files:
        return {}

    result = formatter.format_files(state["repo_path"], files, lint_fix=True)
    if not result.available or not result.ok:
        return {}                             # formatter restored the files; not worth a retry
    fatal = [ln for ln in result.remaining if any(f" {c} " in ln for c in _BLOCKING)]
    if fatal:
        return {"step_error": "Lint found undefined names:\n" + "\n".join(fatal[:10])}
    return {}