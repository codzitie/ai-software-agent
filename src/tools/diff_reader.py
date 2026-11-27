"""Which files, lines and functions changed? Read-only, no git calls, no LLM.

Three ways in:
    analyze(root, diff_text)         diff from git_tool.diff(); symbols come from the files on disk
    from_texts(path, old, new)       two versions of one file
    from_patch(root, edits)          a Patch BEFORE it is applied (simulated in memory)
Then:
    summarize(changes)               short text for a prompt
    targets(changes)                 ["calc.py::add", "cart.py::Cart.remove", ...] for the Tester

How lines map to symbols (Python files only):
  * every added or modified line belongs to the innermost def/class that contains it
    (decorators count as part of the def); a method change reports the method, not the class
  * lines outside any def/class (imports, constants, top-level code) set module_level=True;
    blank and comment-only lines there are ignored
  * a pure deletion has no line in the new file, so it is attributed from the indentation of
    the removed lines: inside a body -> that function; at the level of a def -> its parent
    (a deleted method -> its class, a deleted top-level function -> module level).
    This is approximate, and a function that was deleted entirely is never listed.

Limits: git rename detection is read but a renamed AND edited file reports its new path only;
binary files are flagged and skipped; merge (combined) diffs are not supported.
"""
import ast
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.state.schemas import Edit
from src.tools import filesystem
from src.utils.errors import ToolError

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Symbol:
    name: str          # qualified: "add", "Cart.remove", "outer.inner"
    kind: str          # function | method | class
    start: int         # first line (including decorators)
    end: int


@dataclass
class FileChange:
    path: str
    status: str = "M"                                  # A new, M modified, D deleted, R renamed
    old_path: str | None = None
    binary: bool = False
    added_ranges: list[tuple[int, int]] = field(default_factory=list)   # new-file lines added/modified
    removals: list[tuple[int, int]] = field(default_factory=list)       # (new-file line after, indent) of pure deletions
    symbols: list[Symbol] = field(default_factory=list)                 # changed functions/classes
    module_level: bool = False                         # changed code outside any def/class
    notes: list[str] = field(default_factory=list)

    @property
    def changed_lines(self) -> list[int]:
        return [n for a, b in self.added_ranges for n in range(a, b + 1)]


# ================================================================ unified diff parsing
def _clean_path(raw: str) -> str | None:
    p = raw.split("\t")[0].strip()
    if p.startswith('"') and p.endswith('"') and len(p) >= 2:
        p = p[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return None if p == "/dev/null" else p


def _strip_ab(p: str | None) -> str | None:
    if p and p[:2] in ("a/", "b/"):
        return p[2:]
    return p


def _header_path(line: str) -> str:
    """Path from 'diff --git a/X b/X' when it is unambiguous (spaces make it so only if both match)."""
    rest = line[len("diff --git "):]
    if not rest.startswith("a/"):
        return ""
    body = rest[2:]
    for m in re.finditer(r" b/", body):
        if body[: m.start()] == body[m.end():]:
            return body[: m.start()]
    return ""


def _merge(existing: list[tuple[int, int]], lines: list[int]) -> list[tuple[int, int]]:
    nums = sorted({n for a, b in existing for n in range(a, b + 1)} | set(lines))
    out: list[tuple[int, int]] = []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def _indent(line: str) -> int:
    line = line.expandtabs(4)
    return len(line) - len(line.lstrip())


def _read_hunk(lines: list[str], i: int, m: re.Match, cur: FileChange) -> int:
    """Consume one hunk by its line counts (so '--- x' inside a hunk is never taken for a header)."""
    old_n = int(m.group(2)) if m.group(2) is not None else 1
    new_start = int(m.group(3))
    new_n = int(m.group(4)) if m.group(4) is not None else 1
    new_line = new_start + 1 if new_n == 0 else new_start   # "+c,0" names the line BEFORE the gap
    i += 1

    added: list[int] = []
    block = {"removed": [], "added": 0, "pos": new_line}

    def flush() -> None:
        if block["removed"] and not block["added"]:
            real = [r for r in block["removed"] if r.strip()]
            if real:                                         # deleting only blank lines changes nothing
                cur.removals.append((block["pos"], min(_indent(r) for r in real)))
        block.update(removed=[], added=0, pos=new_line)

    while i < len(lines) and (old_n > 0 or new_n > 0):
        line = lines[i]
        tag = line[:1]
        if tag == "\\":                                      # "\ No newline at end of file"
            i += 1
            continue
        if tag in "-+" and not block["removed"] and not block["added"]:
            block["pos"] = new_line
        if tag == "-":
            block["removed"].append(line[1:])
            old_n -= 1
        elif tag == "+":
            block["added"] += 1
            added.append(new_line)
            new_line += 1
            new_n -= 1
        else:                                                # context line (" " or an emptied one)
            flush()
            new_line += 1
            old_n -= 1
            new_n -= 1
        i += 1
    flush()
    while i < len(lines) and lines[i].startswith("\\"):
        i += 1
    cur.added_ranges = _merge(cur.added_ranges, added)
    return i


def parse_diff(text: str) -> list[FileChange]:
    """Pure parser: files, statuses, added line ranges and deletions. No symbols (see analyze)."""
    changes: list[FileChange] = []
    cur: FileChange | None = None
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            cur = FileChange(path=_header_path(line))
            changes.append(cur)
        elif cur is None:
            pass
        elif line.startswith("new file mode"):
            cur.status = "A"
        elif line.startswith("deleted file mode"):
            cur.status = "D"
        elif line.startswith("rename from "):
            cur.status, cur.old_path = "R", _clean_path(line[len("rename from "):])
        elif line.startswith("rename to "):
            cur.path = _clean_path(line[len("rename to "):]) or cur.path
        elif line.startswith(("Binary files", "GIT binary patch")):
            cur.binary = True
        elif line.startswith("--- "):
            old = _strip_ab(_clean_path(line[4:]))
            if old is None:
                cur.status = "A"
            elif not cur.path:
                cur.path = old
        elif line.startswith("+++ "):
            new = _strip_ab(_clean_path(line[4:]))
            if new is None:
                cur.status = "D"
            else:
                cur.path = new
        elif (m := _HUNK.match(line)):
            i = _read_hunk(lines, i, m, cur)
            continue
        i += 1
    return [c for c in changes if c.path]


# ================================================================ symbols
def _symbols(source: str) -> list[Symbol]:
    tree = ast.parse(source)
    found: list[Symbol] = []

    def walk(node: ast.AST, prefix: str, in_class: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                is_class = isinstance(child, ast.ClassDef)
                kind = "class" if is_class else ("method" if in_class else "function")
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                found.append(Symbol(name, kind, start, child.end_lineno or child.lineno))
                walk(child, name + ".", is_class)
            else:
                walk(child, prefix, in_class)      # defs inside if/try/with blocks keep their scope

    walk(tree, "", False)
    return found


def _attach(change: FileChange, source: str) -> None:
    """Fill change.symbols and change.module_level from the new version of a Python file."""
    try:
        syms = _symbols(source)
    except SyntaxError as exc:
        change.notes.append(f"new content has a syntax error (line {exc.lineno}); symbols unknown")
        return

    src_lines = source.split("\n")
    n = len(src_lines) + 1
    owner: list[Symbol | None] = [None] * (n + 1)
    for s in sorted(syms, key=lambda s: -(s.end - s.start)):        # outer first, inner overrides
        for ln in range(s.start, min(s.end, n) + 1):
            owner[ln] = s

    hit: dict[str, Symbol] = {}
    module_level = False

    for ln in change.changed_lines:
        if 1 <= ln <= n and owner[ln]:
            hit.setdefault(owner[ln].name, owner[ln])
        else:
            text = src_lines[ln - 1].strip() if 1 <= ln <= len(src_lines) else ""
            if text and not text.startswith("#"):
                module_level = True

    def indent_of(s: Symbol) -> int:
        return _indent(src_lines[s.start - 1]) if s.start <= len(src_lines) else 0

    def parent_of(s: Symbol) -> Symbol | None:
        outer = [p for p in syms if p is not s and p.start <= s.start and p.end >= s.end]
        return min(outer, key=lambda p: p.end - p.start) if outer else None

    for pos, removed_indent in change.removals:                      # pure deletions, approximate
        before = owner[pos - 1] if 1 <= pos - 1 <= n else None
        after = owner[pos] if 1 <= pos <= n else None
        if before is not None:
            target = before if removed_indent > indent_of(before) else parent_of(before)
        elif after is not None and removed_indent > indent_of(after):
            target = after
        else:
            target = None
        if target is None:
            module_level = True
        else:
            hit.setdefault(target.name, target)

    change.symbols = sorted(hit.values(), key=lambda s: s.start)
    change.module_level = module_level


# ================================================================ public API
def _read_source(base: Path, rel: str) -> str:
    return filesystem.resolve_safe(base, rel).read_bytes().decode("utf-8").replace("\r\n", "\n")


def analyze(root, diff_text: str) -> list[FileChange]:
    """Parse a diff (from git_tool.diff) and attach changed symbols using the files on disk.

    The diff must be against the current working tree, which is what git_tool.diff gives.
    """
    base = Path(root).resolve()
    changes = parse_diff(diff_text)
    for ch in changes:
        if ch.binary:
            ch.notes.append("binary file")
        elif ch.status != "D" and ch.path.endswith(".py"):
            try:
                _attach(ch, _read_source(base, ch.path))
            except (ToolError, OSError, UnicodeDecodeError) as exc:
                ch.notes.append(f"could not read file for symbol lookup: {exc}")
    return changes


def from_texts(path: str, old: str | None, new: str) -> FileChange:
    """Compare two versions of one file. old=None means a new file."""
    old_lines = [] if old is None else old.replace("\r\n", "\n").splitlines()
    new_text = new.replace("\r\n", "\n")
    diff = list(difflib.unified_diff(
        old_lines, new_text.splitlines(),
        "/dev/null" if old is None else f"a/{path}", f"b/{path}", n=3, lineterm="",
    ))
    if not diff:
        return FileChange(path, notes=["no changes"])
    parsed = parse_diff(f"diff --git a/{path} b/{path}\n" + "\n".join(diff))
    change = parsed[0] if parsed else FileChange(path)
    change.path = path
    if path.endswith(".py"):
        _attach(change, new_text)
    return change


def _apply(content: str, edit: Edit) -> str | None:
    """Same rules as code_modifier.apply_edits for one edit; None if it would not apply."""
    target = edit.target_text.replace("\r\n", "\n")
    if not target or content.count(target) != 1:
        return None
    if edit.action in ("replace", "insert_after") and edit.new_text is None:
        return None
    new = (edit.new_text or "").replace("\r\n", "\n")
    if edit.action == "replace":
        replacement = new
    elif edit.action == "insert_after":
        replacement = target + ("" if target.endswith("\n") or new.startswith("\n") else "\n") + new
    elif edit.action == "remove":
        replacement = ""
    else:
        return None
    return content.replace(target, replacement, 1)


def from_patch(root, edits: list[Edit]) -> list[FileChange]:
    """What a Patch would change, computed in memory BEFORE apply_edits. Edits that would not
    apply are skipped and noted. Keep _apply in step with code_modifier if its rules change."""
    base = Path(root).resolve()
    grouped: dict[str, list[Edit]] = {}
    for e in edits:
        grouped.setdefault(e.file, []).append(e)

    out: list[FileChange] = []
    for rel, group in grouped.items():
        try:
            old = _read_source(base, rel)
        except (ToolError, OSError, UnicodeDecodeError) as exc:
            out.append(FileChange(rel, notes=[f"could not read file: {exc}"]))
            continue
        new, notes = old, []
        for n, e in enumerate(group, 1):
            result = _apply(new, e)
            if result is None:
                notes.append(f"edit {n} would not apply; ignored")
            else:
                new = result
        change = from_texts(rel, old, new)
        change.notes += notes
        out.append(change)
    return out


def _ranges_text(ranges: list[tuple[int, int]]) -> str:
    return ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def summarize(changes: list[FileChange], max_symbols: int = 15) -> str:
    """Short, prompt-ready description of the changes."""
    if not changes:
        return "No changes."
    out = []
    for c in changes:
        label = {"A": "new file", "M": "modified", "D": "deleted",
                 "R": f"renamed from {c.old_path}"}.get(c.status, c.status)
        parts = []
        if c.added_ranges and not (c.status == "A" and c.symbols):
            parts.append(f"changed lines {_ranges_text(c.added_ranges)}")
        shown = c.symbols[:max_symbols]
        parts += [f"{s.kind} {s.name} (lines {s.start}-{s.end})" for s in shown]
        if len(c.symbols) > max_symbols:
            parts.append(f"... and {len(c.symbols) - max_symbols} more")
        if c.module_level:
            parts.append("module-level code changed")
        if c.removals and c.status != "D":
            parts.append("lines removed")
        parts += c.notes
        out.append(f"{c.path} ({label}): " + ("; ".join(parts) if parts else ("file removed" if c.status == "D" else "no content change")))
    return "\n".join(out)


def targets(changes: list[FileChange]) -> list[str]:
    """'path::Qualified.name' for every changed function, method and class, in file order."""
    return [f"{c.path}::{s.name}" for c in changes if c.status != "D" for s in c.symbols]