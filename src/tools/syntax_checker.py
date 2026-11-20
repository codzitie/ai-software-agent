"""Syntax validation. Python, JSON, TOML and JavaScript (when node is installed)."""
import ast
import json
import shutil
import subprocess

from src.tools import filesystem
from src.tools.models import SyntaxIssue
from src.utils.errors import ToolError

try:
    import tomllib   # Python 3.11+
except ImportError:
    tomllib = None


def check_files(root, files: list[str]) -> list[SyntaxIssue]:
    issues: list[SyntaxIssue] = []
    for rel in files:
        try:
            path = filesystem.resolve_safe(root, rel)
        except ToolError as exc:
            issues.append(SyntaxIssue(rel, 0, str(exc)))
            continue
        if not path.is_file():
            issues.append(SyntaxIssue(rel, 0, "file not found"))
            continue
        issues += _check(path, rel)
    return issues


def _check(path, rel: str) -> list[SyntaxIssue]:
    ext = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [SyntaxIssue(rel, 0, "file is not valid UTF-8")]

    if ext == ".py":
        try:
            ast.parse(text, filename=rel)
        except SyntaxError as exc:
            return [SyntaxIssue(rel, exc.lineno or 0, exc.msg)]
        except ValueError as exc:
            return [SyntaxIssue(rel, 0, str(exc))]

    elif ext == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return [SyntaxIssue(rel, exc.lineno, exc.msg)]

    elif ext == ".toml" and tomllib:
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            return [SyntaxIssue(rel, 0, str(exc))]

    elif ext in {".js", ".mjs", ".cjs"} and shutil.which("node"):
        proc = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return [SyntaxIssue(rel, 0, (proc.stderr.strip().splitlines() or ["syntax error"])[-1])]

    return []