"""Record new dependencies in the project's manifest files.

Without this, a feature that adds a package leaves the repo broken for everyone else.

Where it writes:
  * pyproject.toml   only if it has a static [project] dependencies = [...] list
  * requirements.txt if it exists
  * neither exists   -> a new requirements.txt is created

Safe by design:
  * only names already listed (PEP 503 normalised) are skipped, nothing is ever removed
  * pyproject.toml is edited as text, so comments and layout survive; the result is
    re-parsed and must equal old list + new entries, otherwise nothing is written
  * every changed file's original bytes are kept in the result, so undo() restores them
  * installs nothing, runs no shell
"""
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from src.tools import runtime
from src.utils.logging import get_logger

try:
    import tomllib   # Python 3.11+
except ImportError:
    tomllib = None

log = get_logger("manifest")

# Same rule as installer.py: name, optional extras, optional version specifiers.
_SPEC = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,_-]+\])?([=<>!~]=?[A-Za-z0-9.*+!_-]+)*$")
_PINNABLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,_-]+\])?$")   # no specifier yet
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


@dataclass
class ManifestResult:
    added: list[str] = field(default_factory=list)      # spec strings written, e.g. "requests>=2.31.0"
    skipped: list[str] = field(default_factory=list)    # already listed (normalised names)
    files: list[str] = field(default_factory=list)      # repo-relative files that changed
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    originals: dict[str, bytes | None] = field(default_factory=dict)   # None = file did not exist

    @property
    def ok(self) -> bool:
        return not self.errors


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _name_of(spec: str) -> str | None:
    m = _NAME.match(spec)
    return _norm(m.group(1)) if m else None


# ---------------------------------------------------------------- versions
def installed_version(root, name: str) -> str | None:
    """Version of a package in the project's venv, or None. Runs python in isolated mode (-I)."""
    try:
        proc = subprocess.run(
            [str(runtime.python_for(root)), "-I", "-c",
             "import importlib.metadata as m, sys; print(m.version(sys.argv[1]))", name],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and out else None


def _with_pins(base: Path, packages: list[str], pin: str) -> dict[str, str]:
    """normalised name -> spec to write. pin: 'min' (>=), 'exact' (==) or 'none'."""
    out: dict[str, str] = {}
    for spec in packages:
        key = _name_of(spec)
        if key is None or key in out:
            continue
        if pin != "none" and _PINNABLE.match(spec):
            version = installed_version(base, _NAME.match(spec).group(1))
            if version:
                spec = f"{spec}{'==' if pin == 'exact' else '>='}{version}"
        out[key] = spec
    return out


# ---------------------------------------------------------------- requirements.txt
def _update_requirements(base: Path, path: Path, new: dict[str, str], result: ManifestResult) -> None:
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        result.errors.append(f"{path.name} is not valid UTF-8; left unchanged")
        return

    existing = {
        key for line in text.splitlines()
        if not line.lstrip().startswith(("#", "-")) and (key := _name_of(line))
    }
    todo = {k: s for k, s in new.items() if k not in existing}
    result.skipped += [k for k in new if k in existing and k not in result.skipped]
    if not todo:
        return

    nl = "\r\n" if "\r\n" in text else "\n"
    if text and not text.endswith("\n"):
        text += nl
    text += nl.join(todo.values()) + nl

    rel = path.relative_to(base).as_posix()
    result.originals.setdefault(rel, path.read_bytes())
    path.write_bytes(text.encode("utf-8"))
    result.files.append(rel)
    result.added += [s for s in todo.values() if s not in result.added]


# ---------------------------------------------------------------- pyproject.toml
def _scan_array(text: str, o: int):
    """For the '[' at text[o]: return (index of matching ']', end of last string) or None."""
    depth, i, last, n = 1, o + 1, None, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if (ch == '"' and text[j] == "\\") else 1
            if j >= n:
                return None
            if depth == 1:
                last = j + 1
            i = j + 1
            continue
        if ch == "#":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i, last
        i += 1
    return None


def _locate_dependencies(text: str):
    """(open, close, last_string_end) of the [project] dependencies array, or None."""
    header = re.search(r"^\[project\][ \t]*(#.*)?$", text, re.M)
    if not header:
        return None
    start = header.end()
    nxt = re.search(r"^\[", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    key = re.search(r"^dependencies[ \t]*=[ \t]*\[", text[start:end], re.M)
    if not key:
        return None
    o = start + key.end() - 1
    scanned = _scan_array(text, o)
    return (o, *scanned) if scanned else None


def _insert(text: str, o: int, c: int, last: int | None, specs: list[str]) -> str:
    quoted = [f'"{s}"' for s in specs]
    body = text[o + 1:c]

    if "\n" not in body:                                   # inline array: ["a", "b"]
        if last is None:
            return text[:o + 1] + ", ".join(quoted) + text[c:]
        return text[:last] + ", " + ", ".join(quoted) + text[last:]

    indent = "    "                                        # multi-line array
    if last is not None:
        line_start = text.rfind("\n", 0, last) + 1
        if line_start > o:
            first = text[line_start:last]
            indent = first[: len(first) - len(first.lstrip())] or indent
    new_lines = "".join(f"\n{indent}{q}," for q in quoted)

    if last is None:                                       # empty array
        return text[:o + 1] + new_lines + text[o + 1:]
    comma = "" if text[last:c].lstrip().startswith(",") else ","
    eol = text.find("\n", last, c)                         # end of the last entry's line
    eol = c if eol == -1 else eol
    return text[:last] + comma + text[last:eol] + new_lines + text[eol:]


def _pyproject_state(path: Path, result: ManifestResult):
    """The current dependency list, or None when pyproject.toml should not be edited."""
    if not path.is_file():
        return None
    if tomllib is None:
        result.notes.append("pyproject.toml not updated: needs Python 3.11+ to read it safely")
        return None
    try:
        data = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        result.errors.append(f"pyproject.toml could not be parsed, left unchanged: {exc}")
        return None
    project = data.get("project", {})
    if "dependencies" in project.get("dynamic", []):
        result.notes.append("pyproject.toml uses dynamic dependencies; not edited")
        return None
    deps = project.get("dependencies")
    return deps if isinstance(deps, list) else None


def _update_pyproject(base: Path, path: Path, current: list[str], new: dict[str, str],
                      result: ManifestResult) -> None:
    existing = {k for d in current if (k := _name_of(d))}
    todo = {k: s for k, s in new.items() if k not in existing}
    result.skipped += [k for k in new if k in existing and k not in result.skipped]
    if not todo:
        return

    raw = path.read_bytes()
    text = raw.decode("utf-8")
    spot = _locate_dependencies(text)
    if spot is None:
        result.errors.append("pyproject.toml: could not find the dependencies list to edit")
        return
    o, c, last = spot
    updated = _insert(text, o, c, last, list(todo.values()))

    try:                                                   # prove the edit is exactly what we meant
        parsed = tomllib.loads(updated)["project"]["dependencies"]
    except (tomllib.TOMLDecodeError, KeyError):
        parsed = None
    if parsed != current + list(todo.values()):
        result.errors.append("pyproject.toml edit did not verify; left unchanged")
        return

    rel = path.relative_to(base).as_posix()
    result.originals.setdefault(rel, raw)
    path.write_bytes(updated.encode("utf-8"))
    result.files.append(rel)
    result.added += [s for s in todo.values() if s not in result.added]


# ---------------------------------------------------------------- public API
def record_dependencies(root, packages: list[str], pin: str = "min") -> ManifestResult:
    """Add packages (pip names, e.g. from dependency.find_missing) to the manifest files.

    pin: 'min' writes name>=installed_version, 'exact' writes ==, 'none' writes the bare name.
    A package that already has a specifier (e.g. 'requests>=2') is written as given.
    Call it after a successful install so the installed version is known.
    """
    base = Path(root).resolve()
    result = ManifestResult()

    bad = [p for p in packages if not _SPEC.match(p)]
    if bad:
        result.errors.append(f"Refused invalid package name(s): {bad}")
        return result
    if pin not in ("min", "exact", "none"):
        result.errors.append(f"pin must be 'min', 'exact' or 'none', not '{pin}'")
        return result
    if not packages:
        return result

    new = _with_pins(base, packages, pin)
    pyproject, requirements = base / "pyproject.toml", base / "requirements.txt"

    py_deps = _pyproject_state(pyproject, result)
    if py_deps is not None:
        _update_pyproject(base, pyproject, py_deps, new, result)
    if requirements.is_file():
        _update_requirements(base, requirements, new, result)

    if py_deps is None and not requirements.is_file() and not result.errors:
        requirements.write_bytes(("\n".join(new.values()) + "\n").encode("utf-8"))
        result.originals["requirements.txt"] = None
        result.files.append("requirements.txt")
        result.added += list(new.values())
        result.notes.append("no manifest listed dependencies, so requirements.txt was created")

    log.info("manifest: added=%s skipped=%s files=%s", result.added, result.skipped, result.files)
    return result


def undo(root, result: ManifestResult) -> None:
    """Put every changed manifest file back exactly as it was (or remove one we created)."""
    base = Path(root).resolve()
    for rel, original in result.originals.items():
        path = base / rel
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)