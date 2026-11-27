"""Shared helpers for the Tester nodes."""
import json
from pathlib import Path

from src.agents.developer.context import render  # noqa: F401  (re-exported for the nodes)
from src.state.graph_state import AgentState
from src.state.schemas import TestPlan
from src.tools import code_modifier, diff_reader, filesystem
from src.tools.diff_reader import FileChange
from src.utils.errors import ToolError

MAX_CODE_CHARS = 12000
MAX_TEST_CHARS = 3000
MAX_FEEDBACK_SHOWN = 3


def is_test_file(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or name == "conftest.py" or "tests" in parts[:-1] or "test" in parts[:-1])


def task_description(state: AgentState) -> str:
    plan = state.get("plan")
    desc = next((t.description for t in (plan.tasks if plan else [])
                 if t.agent in ("developer", "issue")), "")
    return f"{state['user_query']}\n{desc}".strip()


def feedback_text(state: AgentState) -> str:
    notes = state.get("tester_feedback", [])[-MAX_FEEDBACK_SHOWN:]
    return "\n\n".join(f"Previous attempt {i + 1} failed:\n{n}" for i, n in enumerate(notes))


# ---------- what changed ----------
def _read(root, rel: str) -> str | None:
    try:
        return filesystem.resolve_safe(root, rel).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError, ToolError):
        return None


def _originals(state: AgentState) -> dict[str, str]:
    """File text from BEFORE the agent's edits. The earliest backup of a file wins."""
    base = code_modifier._backup_root(state["repo_path"])
    ids = [*state.get("applied_backups", [])]
    if state.get("backup_id"):
        ids.append(state["backup_id"])
    out: dict[str, str] = {}
    for bid in ids:
        manifest = base / bid / "manifest.json"
        if not manifest.is_file():
            continue
        for key in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
            saved = base / bid / "files" / key
            if key not in out and saved.is_file():
                out[key] = saved.read_bytes().decode("utf-8", errors="replace")
    return out


def compute_changes(state: AgentState) -> list[FileChange]:
    """Changed Python source files (edited and newly created), with changed symbols."""
    root = state["repo_path"]
    originals = _originals(state)
    changes: list[FileChange] = []
    for rel, old in originals.items():
        new = _read(root, rel)
        if rel.endswith(".py") and not is_test_file(rel) and new is not None and new != old:
            changes.append(diff_reader.from_texts(rel, old, new))
    for rel in state.get("created_files", []):
        new = _read(root, rel)
        if rel.endswith(".py") and not is_test_file(rel) and rel not in originals and new is not None:
            changes.append(diff_reader.from_texts(rel, None, new))
    return changes


def testable(changes: list[FileChange]) -> list[FileChange]:
    return [c for c in changes if c.status != "D" and c.symbols]


def changed_code(root, changes: list[FileChange], limit: int = MAX_CODE_CHARS) -> str:
    parts: list[str] = []
    used = 0
    for c in changes:
        text = _read(root, c.path)
        if text is None:
            continue
        lines = text.replace("\r\n", "\n").split("\n")
        for s in c.symbols:
            if s.kind == "class" and any(o is not s and o.name.startswith(s.name + ".") for o in c.symbols):
                continue                      # its changed methods are listed on their own
            block = f"### {c.path}::{s.name} (lines {s.start}-{s.end})\n" + "\n".join(lines[s.start - 1:s.end])
            if used + len(block) > limit:
                parts.append("[more changed code omitted]")
                return "\n\n".join(parts)
            parts.append(block)
            used += len(block)
    return "\n\n".join(parts) or "none"


def existing_tests(root, changes: list[FileChange], exclude: list[str], limit: int = 3) -> str:
    words = {Path(c.path).stem for c in changes} - {"__init__"}
    words |= {s.name.split(".")[-1] for c in changes for s in c.symbols}
    related, other = [], []
    for rel in filesystem.iter_files(root):
        if not rel.endswith(".py") or not is_test_file(rel) or rel in exclude:
            continue
        try:
            text, _ = filesystem.read_for_llm(root, rel, max_chars=MAX_TEST_CHARS)
        except (ToolError, FileNotFoundError):
            continue
        (related if any(w in text for w in words) else other).append((rel, text))
    chosen = (related + other)[:limit]
    return "\n\n".join(f"### {r}\n{t}" for r, t in chosen) or "none"


# ---------- test plan helpers ----------
def planned_files(plan: TestPlan) -> list[str]:
    return list(dict.fromkeys(c.test_file for c in plan.cases))


def cases_json(plan: TestPlan, test_file: str) -> str:
    return json.dumps([c.model_dump() for c in plan.cases if c.test_file == test_file], indent=2)


def fresh_path(root, rel: str, taken: set[str]) -> str:
    """A test path that does not exist yet (write_files never overwrites)."""
    p = Path(rel)
    cand, n = rel, 2
    while cand in taken or filesystem.resolve_safe(root, cand).exists():
        cand = p.with_name(f"{p.stem}_{n}{p.suffix}").as_posix()
        n += 1
    return cand


def action_for(records: list[dict]) -> str:
    verdicts = {r["verdict"] for r in records}
    if "test_bug" in verdicts:
        return "fix_tests"
    if "implementation_bug" in verdicts:
        return "fix_implementation"
    return "fix_tests"