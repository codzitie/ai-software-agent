"""Python dependency tools: missing packages, import graph, circular imports."""
import ast
import itertools
import json
import subprocess
import sys
from pathlib import Path

import networkx as nx

from src.tools import filesystem, runtime
from src.utils.errors import ToolError
from src.utils.logging import get_logger

log = get_logger("dependency")

# import name -> pip name, where they differ
PIP_ALIASES = {
    "yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv-python", "sklearn": "scikit-learn",
    "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "jwt": "pyjwt", "dateutil": "python-dateutil",
    "attr": "attrs", "serial": "pyserial", "Crypto": "pycryptodome", "magic": "python-magic",
}


def _parse(root, rel: str):
    try:
        path = filesystem.resolve_safe(root, rel)
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, OSError, ToolError):
        return None


# ---------- missing third-party packages ----------
def imports_of(root, files: list[str]) -> set[str]:
    """Top-level absolute module names imported by the given Python files."""
    names: set[str] = set()
    for rel in files:
        if not rel.endswith(".py"):
            continue
        tree = _parse(root, rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def _local_names(root) -> set[str]:
    base = Path(root).resolve()
    names: set[str] = set()
    for parent in (base, base / "src"):
        if not parent.is_dir():
            continue
        for p in parent.iterdir():
            if p.is_dir() and ((p / "__init__.py").exists() or any(p.glob("*.py"))):
                names.add(p.name)
            elif p.suffix == ".py":
                names.add(p.stem)
    return names


def find_missing(root, files: list[str]) -> list[str]:
    """Pip package names that the files import but the repo's environment lacks."""
    local = _local_names(root)
    candidates = sorted(
        n for n in imports_of(root, files) if n not in sys.stdlib_module_names and n not in local
    )
    if not candidates:
        return []

    code = (
        "import importlib.util, json, sys;"
        "print(json.dumps([n for n in sys.argv[1:] if importlib.util.find_spec(n) is None]))"
    )
    try:
        proc = subprocess.run(
            [str(runtime.python_for(root)), "-c", code, *candidates],
            capture_output=True, text=True, timeout=60,
        )
        missing = json.loads(proc.stdout.strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, OSError, ValueError, IndexError):
        log.exception("Could not check installed packages")
        return []   # never install blindly
    return sorted({PIP_ALIASES.get(n, n) for n in missing})


# ---------- import graph and cycles ----------
def _module_name(rel: str) -> str:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _absolute(node: ast.ImportFrom, pkg: str) -> str | None:
    if node.level == 0:
        return node.module
    parts = pkg.split(".") if pkg else []
    up = node.level - 1
    if up > len(parts):
        return None
    parts = parts[: len(parts) - up]
    if node.module:
        parts += node.module.split(".")
    return ".".join(parts) or None


def build_graph(root) -> dict[str, set[str]]:
    """module -> set of repo modules it imports."""
    files = [f for f in filesystem.iter_files(root) if f.endswith(".py")]
    modules = {_module_name(f): f for f in files}
    aliases = {m[4:]: m for m in modules if m.startswith("src.")}   # src layout

    def exact(name: str) -> str | None:
        return name if name in modules else aliases.get(name)

    def resolve(name: str) -> str | None:
        parts = name.split(".")
        while parts:
            if found := exact(".".join(parts)):
                return found
            parts.pop()
        return None

    graph: dict[str, set[str]] = {m: set() for m in modules}
    for mod, rel in modules.items():
        tree = _parse(root, rel)
        if tree is None:
            continue
        pkg = mod if rel.endswith("__init__.py") else mod.rpartition(".")[0]
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _absolute(node, pkg)
                if base is None:
                    continue
                for a in node.names:   # "from pkg import sub" depends on pkg.sub when that is a module
                    targets.append(f"{base}.{a.name}" if exact(f"{base}.{a.name}") else base)
            for t in targets:
                dep = resolve(t)
                if dep and dep != mod:
                    graph[mod].add(dep)
    return graph


def find_cycles(root, limit: int = 20) -> list[list[str]]:
    g = nx.DiGraph((src, dst) for src, deps in build_graph(root).items() for dst in deps)
    return [cycle for cycle in itertools.islice(nx.simple_cycles(g), limit)]