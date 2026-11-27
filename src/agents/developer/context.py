"""Shared helpers for the Developer nodes."""
from src.state.graph_state import AgentState
from src.tools import filesystem
from src.utils.errors import ToolError

DEP_FILE_CHARS = 6000
MAX_FEEDBACK_SHOWN = 3


def render(prompt: str, **values) -> str:
    """Fill {name} placeholders. Plain replace, so other braces in the prompt are safe."""
    for key, value in values.items():
        prompt = prompt.replace("{" + key + "}", str(value))
    return prompt


def feedback_text(state: AgentState) -> str:
    notes = state.get("feedback", [])[-MAX_FEEDBACK_SHOWN:]
    return "\n\n".join(f"Previous attempt {i + 1} failed:\n{n}" for i, n in enumerate(notes))


def summary_text(state: AgentState) -> str:
    cs = state.get("codebase_summary")
    return cs.model_dump_json(indent=2) if cs else ""


def dependency_sources(state: AgentState, depends_on: list[str]) -> str:
    """Contents of files from this task that the current file builds on."""
    created = set(state.get("created_files", []))
    parts = []
    for rel in depends_on:
        if rel not in created:
            continue
        try:
            text, _ = filesystem.read_for_llm(state["repo_path"], rel, max_chars=DEP_FILE_CHARS)
        except (ToolError, FileNotFoundError):
            continue
        parts.append(f"### {rel}\n{text}")
    return "\n\n".join(parts)

import re

_PKG_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def pkg_key(spec: str) -> str:
    """'PyYAML>=6' -> 'pyyaml' (PEP 503 style)."""
    m = _PKG_KEY.match(spec.strip())
    return re.sub(r"[-_.]+", "-", m.group(0)).lower() if m else spec.lower()


def step_files(state: AgentState) -> list[str]:
    """Files the current step created or edited."""
    gen = state.get("generated_file")
    if gen is not None:
        return [gen.path]
    patch = state.get("patch")
    return sorted({e.file for e in patch.edits}) if patch else []