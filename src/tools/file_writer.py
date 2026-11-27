"""Create NEW files inside the repo.

Existing files are never overwritten here. Edit them with
code_modifier.apply_edits so backup and rollback keep working.
"""
from pathlib import Path

from src.tools import filesystem
from src.utils.errors import ToolError

MAX_FILE_BYTES = 200_000
MAX_FILES_PER_CALL = 50
_BLOCKED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules"}


def write_files(root, files: dict[str, str]) -> list[str]:
    """Create every file in `files` (relative path -> content).

    Returns the relative paths created. Raises ToolError and leaves nothing
    behind if any file is invalid or any write fails.
    """
    base = Path(root).resolve()
    if not files:
        return []
    if len(files) > MAX_FILES_PER_CALL:
        raise ToolError(f"Too many files in one call ({len(files)}); limit is {MAX_FILES_PER_CALL}.")

    # 1) validate everything before touching the disk
    targets: dict[Path, str] = {}
    for rel, content in files.items():
        path = _validate(base, rel, content)
        if path in targets:
            raise ToolError(f"Duplicate path in one call: {rel}")
        targets[path] = content

    # 2) write; undo this call's work if anything fails
    written: list[Path] = []
    try:
        for path, content in targets.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            written.append(path)
    except OSError as exc:
        _remove(base, written)
        raise ToolError(f"Could not write files, rolled back this call: {exc}")

    return [p.relative_to(base).as_posix() for p in written]


def remove_created(root, rel_paths: list[str]) -> list[str]:
    """Delete files created earlier by write_files (rollback).

    Also removes parent folders that become empty. Returns what was removed.
    """
    base = Path(root).resolve()
    paths = [filesystem.resolve_safe(base, rel) for rel in rel_paths]
    return _remove(base, paths)


# ---------- helpers ----------
def _validate(base: Path, rel: str, content: str) -> Path:
    if not isinstance(content, str):
        raise ToolError(f"Content for {rel} must be text.")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ToolError(f"{rel} is larger than {MAX_FILE_BYTES} bytes.")

    path = filesystem.resolve_safe(base, rel)       # raises ToolError if outside the repo
    parts = path.relative_to(base).parts
    if not parts:
        raise ToolError("Empty file path.")
    if any(part in _BLOCKED_DIRS for part in parts):
        raise ToolError(f"Writing inside {parts[0]!r}-style folders is not allowed: {rel}")
    if path.name == ".env" or path.name.startswith(".env."):
        raise ToolError(f"Refusing to create environment/secret file: {rel}")
    if path.exists():
        raise ToolError(f"File already exists (use apply_edits to change it): {rel}")
    for parent in path.parents:
        if parent == base:
            break
        if parent.exists() and not parent.is_dir():
            raise ToolError(f"A file blocks the folder path for: {rel}")
    return path


def _remove(base: Path, paths: list[Path]) -> list[str]:
    removed: list[str] = []
    for path in paths:
        if path.is_file():
            path.unlink()
            removed.append(path.relative_to(base).as_posix())
        parent = path.parent
        while parent != base and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    return removed