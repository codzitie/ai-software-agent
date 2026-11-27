"""Describe a Python repository so the Developer agent can follow its conventions.

Read-only: never creates a venv, installs anything or writes any file.
"""
import re
from itertools import islice
from pathlib import Path

from src.tools import filesystem
from src.tools.models import ProjectInfo
from src.utils.errors import ToolError

try:
    import tomllib
except ImportError:            # Python < 3.11: dependency parsing of pyproject is skipped
    tomllib = None

_MAX_FILES = 5000
_DEP_FILES = ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile")
_ENTRY_NAMES = {"main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "cli.py", "__main__.py"}
_KNOWN = (
    "django", "flask", "fastapi", "streamlit", "click", "typer", "sqlalchemy",
    "pydantic", "langgraph", "langchain", "requests", "numpy", "pandas",
)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def inspect(root) -> ProjectInfo:
    base = Path(root).resolve()
    if not base.is_dir():
        raise ToolError(f"Not a directory: {root}")

    files = list(islice(filesystem.iter_files(base), _MAX_FILES))   # relative posix paths
    names = set(files)
    py_files = [f for f in files if f.endswith(".py")]
    test_files = [f for f in py_files if _is_test(f)]
    dep_files = [n for n in _DEP_FILES if n in names]

    layout, packages = _layout(py_files)
    deps = _read_dependencies(base, dep_files)
    dep_names = {_norm(d) for d in deps}
    pyproject = _read(base / "pyproject.toml")

    return ProjectInfo(
        is_empty=not files,
        python_files=len(py_files),
        layout=layout,
        packages=packages,
        entry_points=[f for f in files if f.rsplit("/", 1)[-1] in _ENTRY_NAMES and f.count("/") <= 2],
        dependency_files=dep_files,
        dependencies=deps,
        frameworks=[k for k in _KNOWN if k in dep_names],
        test_framework=_test_framework(base, names, test_files, dep_names, pyproject),
        test_dirs=sorted({f.rsplit("/", 1)[0] if "/" in f else "." for f in test_files}),
        test_file_count=len(test_files),
        python_version=_python_version(base, pyproject),
        line_length=_line_length(pyproject),
        has_own_venv=any((base / n / "pyvenv.cfg").is_file() for n in (".venv", "venv")),
        is_git_repo=(base / ".git").exists(),
        has_readme=any(n.lower().startswith("readme") for n in files if "/" not in n),
    )


def summarize(info: ProjectInfo) -> str:
    """Short text for the Developer/Tester prompts."""
    if info.is_empty:
        return "The repository is empty."
    lines = [
        f"Layout: {info.layout}; packages: {', '.join(info.packages) or 'none'}",
        f"Python files: {info.python_files}; entry points: {', '.join(info.entry_points) or 'none'}",
        f"Dependency files: {', '.join(info.dependency_files) or 'none'}",
        f"Dependencies: {', '.join(info.dependencies[:40]) or 'none'}",
        f"Test framework: {info.test_framework or 'none found'}; "
        f"test files: {info.test_file_count} in {', '.join(info.test_dirs) or 'n/a'}",
    ]
    if info.python_version:
        lines.append(f"Python version hint: {info.python_version}")
    if info.line_length:
        lines.append(f"Configured line length: {info.line_length}")
    return "\n".join(lines)


# ---------- helpers ----------
def _is_test(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def _layout(py_files: list[str]) -> tuple[str, list[str]]:
    top: set[str] = set()
    in_src: set[str] = set()
    for f in py_files:
        parts = f.split("/")
        if parts[-1] != "__init__.py":
            continue
        if len(parts) == 2:
            top.add(parts[0])
        elif len(parts) == 3 and parts[0] == "src":
            in_src.add(parts[1])
    if in_src and "src" not in top:          # real src-layout (src/ itself is not a package)
        return "src", sorted(in_src - {"tests"})
    if py_files:
        return "flat", sorted(top - {"tests", "test"})
    return "none", []


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _dep_name(spec: str) -> str | None:
    match = _NAME.match(spec.strip())
    return match.group(0) if match else None


def _read_dependencies(base: Path, dep_files: list[str]) -> list[str]:
    found: list[str] = []
    if "requirements.txt" in dep_files:
        for line in _read(base / "requirements.txt").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                name = _dep_name(line)
                if name:
                    found.append(name)
    if "pyproject.toml" in dep_files and tomllib is not None:
        try:
            data = tomllib.loads(_read(base / "pyproject.toml"))
        except tomllib.TOMLDecodeError:
            data = {}
        for spec in data.get("project", {}).get("dependencies", []):
            name = _dep_name(spec)
            if name:
                found.append(name)
        poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        found.extend(k for k in poetry if k.lower() != "python")
    return sorted(set(found), key=str.lower)


def _test_framework(base, names, test_files, dep_names, pyproject) -> str | None:
    pytest_hint = (
        "pytest" in dep_names
        or "pytest.ini" in names
        or "conftest.py" in names
        or "[tool.pytest" in pyproject
    )
    if pytest_hint:
        return "pytest"
    if not test_files:
        return None
    for rel in test_files[:5]:
        text = _read(base / rel)
        if "import unittest" in text or "unittest.TestCase" in text:
            return "unittest"
    return "pytest"


def _python_version(base: Path, pyproject: str) -> str | None:
    text = _read(base / ".python-version").strip()
    if text:
        return text.splitlines()[0].strip()
    match = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', pyproject)
    return match.group(1) if match else None


def _line_length(pyproject: str) -> int | None:
    match = re.search(r"line-length\s*=\s*(\d+)", pyproject)
    return int(match.group(1)) if match else None