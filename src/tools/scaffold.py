"""Create the skeleton of a NEW Python project.

Writes config files, a package and a smoke test. Installs nothing: dependencies
are only listed in the files; installing goes through installer.install (with
the user's confirmation).
"""
import json
import keyword
import re
import sys
from pathlib import Path

from src.tools import file_writer
from src.utils.errors import ToolError

# Same shape as installer._PACKAGE: name, optional extras, optional version specifiers.
_DEP = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,_-]+\])?([=<>!~]=?[A-Za-z0-9.*+!_-]+)*$"
)
_RESERVED_PACKAGE_NAMES = {"test", "tests", "src"}


def package_name(project_name: str) -> str:
    """'My Todo App' -> 'my_todo_app' (a valid, importable package name)."""
    name = re.sub(r"[^0-9a-zA-Z]+", "_", project_name).strip("_").lower()
    if not name:
        raise ToolError(f"Cannot make a package name from {project_name!r}.")
    if name[0].isdigit():
        name = f"p_{name}"
    if keyword.iskeyword(name) or name in _RESERVED_PACKAGE_NAMES:
        name = f"{name}_app"
    return name


def project_dir(workspace, project_name: str) -> Path:
    """Folder for a new project, always directly inside `workspace`."""
    slug = re.sub(r"[^0-9a-zA-Z._-]+", "-", project_name.strip()).strip("-._").lower()
    if not slug:
        raise ToolError(f"Cannot make a folder name from {project_name!r}.")
    base = Path(workspace).resolve()
    target = (base / slug).resolve()
    if target.parent != base:
        raise ToolError(f"Project folder would be outside the workspace: {project_name!r}")
    return target


def create(
    root,
    project_name: str,
    description: str = "",
    layout: str = "flat",
    dependencies: list[str] | None = None,
    with_tests: bool = True,
) -> list[str]:
    """Create the skeleton at `root`. Returns the relative paths created."""
    if layout not in ("flat", "src"):
        raise ToolError("layout must be 'flat' or 'src'.")
    deps = _clean_dependencies(dependencies or [])
    pkg = package_name(project_name)

    base = Path(root).resolve()
    if base.exists():
        if not base.is_dir():
            raise ToolError(f"Not a directory: {root}")
        if any(p.name != ".git" for p in base.iterdir()):
            raise ToolError(f"Folder is not empty, refusing to scaffold into it: {root}")
    else:
        base.mkdir(parents=True)

    pkg_dir = f"src/{pkg}" if layout == "src" else pkg
    files = {
        "pyproject.toml": _pyproject(pkg, description, layout, deps),
        "requirements.txt": _requirements(deps),
        ".gitignore": _GITIGNORE,
        "README.md": _readme(project_name, description),
        f"{pkg_dir}/__init__.py": f'"""{_one_line(description) or project_name}"""\n\n__version__ = "0.1.0"\n',
    }
    if with_tests:
        files["tests/test_smoke.py"] = (
            f"import {pkg}\n\n\n"
            "def test_package_imports():\n"
            f"    assert {pkg}.__version__\n"
        )
    return file_writer.write_files(base, files)


# ---------- helpers ----------
def _clean_dependencies(deps: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in deps:
        dep = raw.strip()
        if not _DEP.match(dep):
            raise ToolError(f"Invalid dependency: {raw!r}")
        key = re.split(r"[\[=<>!~]", dep, maxsplit=1)[0].lower().replace("_", "-")
        if key not in seen:
            seen.add(key)
            cleaned.append(dep)
    return cleaned


def _one_line(text: str) -> str:
    return " ".join(text.replace('"', "'").split())[:120]


def _requirements(deps: list[str]) -> str:
    if not deps:
        return "# Add runtime dependencies here, one per line.\n"
    return "\n".join(deps) + "\n"


def _pyproject(pkg: str, description: str, layout: str, deps: list[str]) -> str:
    python = f">={sys.version_info.major}.{sys.version_info.minor}"
    dist_name = pkg.replace("_", "-")
    if deps:
        items = "".join(f"    {json.dumps(d)},\n" for d in deps)
        deps_block = f"dependencies = [\n{items}]"
    else:
        deps_block = "dependencies = []"
    if layout == "src":
        find = '[tool.setuptools.packages.find]\nwhere = ["src"]'
        pythonpath = '["src"]'
    else:
        find = f'[tool.setuptools.packages.find]\ninclude = ["{pkg}*"]'
        pythonpath = '["."]'

    return (
        "[build-system]\n"
        'requires = ["setuptools>=68"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        f"name = {json.dumps(dist_name)}\n"
        'version = "0.1.0"\n'
        f"description = {json.dumps(_one_line(description), ensure_ascii=False)}\n"
        f"requires-python = {json.dumps(python)}\n"
        f"{deps_block}\n\n"
        f"{find}\n\n"
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        f"pythonpath = {pythonpath}\n\n"
        "[tool.ruff]\n"
        "line-length = 100\n"
    )


def _readme(project_name: str, description: str) -> str:
    about = f"{description.strip()}\n\n" if description.strip() else ""
    return (
        f"# {project_name}\n\n"
        f"{about}"
        "## Setup\n\n"
        "```\n"
        "python -m venv .venv\n"
        "pip install -r requirements.txt\n"
        "```\n\n"
        "## Run the tests\n\n"
        "```\n"
        "pytest\n"
        "```\n"
    )


_GITIGNORE = """\
__pycache__/
*.py[cod]
.venv/
venv/
.env
.pytest_cache/
.coverage
htmlcov/
*.egg-info/
build/
dist/
.ruff_cache/
"""