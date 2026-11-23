"""Discover, list and read repository files. Every path is checked to stay inside the repo."""
import fnmatch
import os
from pathlib import Path

import pathspec

from config import settings
from src.utils.errors import ToolError


def resolve_safe(root, rel_path: str) -> Path:
    base = Path(root).resolve()
    target = (base / rel_path).resolve()
    if target != base and base not in target.parents:
        raise ToolError(f"Path is outside the repository: {rel_path}")
    return target


def _gitignore(base: Path):
    f = base / ".gitignore"
    if f.is_file():
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    return None


def iter_files(root):
    """Yield repo-relative posix paths, skipping ignored folders and .gitignore matches."""
    base = Path(root).resolve()
    spec = _gitignore(base)
    for dirpath, dirnames, filenames in os.walk(base):
        rel_dir = Path(dirpath).relative_to(base)
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in settings.IGNORE_DIRS
            and not (spec and spec.match_file((rel_dir / d).as_posix() + "/"))
        )
        for name in sorted(filenames):
            rel = (rel_dir / name).as_posix()
            if spec and spec.match_file(rel):
                continue
            yield rel


def tree(root, max_depth: int = 4, max_entries: int = 300) -> str:
    nested: dict = {}
    for rel in iter_files(root):
        node = nested
        for part in rel.split("/"):
            node = node.setdefault(part, {})

    lines: list[str] = []

    def walk(node: dict, depth: int) -> None:
        for name, child in sorted(node.items(), key=lambda kv: (not kv[1], kv[0])):  # dirs first
            if len(lines) >= max_entries:
                return
            if child:
                lines.append(f"{'  ' * depth}{name}/")
                if depth + 1 < max_depth:
                    walk(child, depth + 1)
                else:
                    lines[-1] += " …"
            else:
                lines.append(f"{'  ' * depth}{name}")

    walk(nested, 0)
    if len(lines) >= max_entries:
        lines.append("… (truncated)")
    return "\n".join(lines) or "(empty)"


def glob_find(root, patterns: list[str]) -> list[str]:
    """Patterns without '/' match file names anywhere; others match the relative path."""
    pats: list[str] = []
    for p in patterns:
        pats += [p.lower(), p.lower().replace("**/", "")]   # so docs/**/*.md also matches docs/a.md

    found = []
    for rel in iter_files(root):
        name = rel.rsplit("/", 1)[-1]
        for p in pats:
            target = rel if "/" in p else name
            if fnmatch.fnmatchcase(target.lower(), p):
                found.append(rel)
                break
    return found


def read_file(root, rel_path: str, max_chars: int = 20000) -> str:
    path = resolve_safe(root, rel_path)
    if not path.is_file():
        raise FileNotFoundError(rel_path)

    with open(path, "rb") as f:
        data = f.read(max_chars * 4 + 4)
    if b"\0" in data[:1024]:
        raise ToolError(f"Binary file: {rel_path}")

    text = data.decode("utf-8", errors="replace")
    if len(text) > max_chars or path.stat().st_size > len(data):
        text = text[:max_chars] + "\n… [truncated]"
    return text

def read_for_llm(root, rel_path: str, max_chars: int = 20000) -> tuple[str, bool]:
    """File text for an LLM. Returns (text, was_cut).

    A long file is cut at a line boundary and followed by a note saying the rest is
    only not displayed, so the model cannot mistake the cut for broken code.
    """
    path = resolve_safe(root, rel_path)
    if not path.is_file():
        raise FileNotFoundError(rel_path)
    with open(path, "rb") as f:
        data = f.read(settings.MAX_FILE_BYTES)
    if b"\0" in data[:1024]:
        raise ToolError(f"Binary file: {rel_path}")

    text = data.decode("utf-8", errors="replace")
    if len(text) <= max_chars:
        return text, False

    cut = text.rfind("\n", 0, max_chars)
    shown = text[: cut if cut > 0 else max_chars]
    note = (
        f"\n\n[NOTE: this file has {text.count(chr(10)) + 1} lines. Lines 1-{shown.count(chr(10)) + 1} "
        "are shown. The rest is only not displayed. The file is not broken or cut off here, "
        "so do not treat the end of this view as an error.]"
    )
    return shown + note, True

def read_window(root, rel_path: str, line: int, radius: int = 25, numbered: bool = False) -> str:
    """Lines around `line`. Never adds a '[truncated]' marker to the code itself."""
    path = resolve_safe(root, rel_path)
    if not path.is_file():
        raise FileNotFoundError(rel_path)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    body = [f"{n}: {lines[n - 1]}" if numbered else lines[n - 1] for n in range(start, end + 1)]
    return f"[showing lines {start}-{end} of {len(lines)}]\n" + "\n".join(body)