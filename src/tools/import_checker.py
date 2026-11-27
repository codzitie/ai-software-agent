"""Find imports that do not resolve, without running any project code.

Local and relative imports are resolved by reading the files. Everything else is
looked up with importlib.util.find_spec inside the project's own environment
(find_spec does not import the package).
"""
import ast
import json
import subprocess
from pathlib import Path
from src.tools.dependency import PIP_ALIASES
from src.tools import filesystem, runtime
from src.tools.models import SyntaxIssue
from src.utils.errors import ToolError

_TIMEOUT = 30
_OPTIONAL_EXC = {"ImportError", "ModuleNotFoundError", "Exception"}

_LOOKUP_SCRIPT = (
    "import sys, json, importlib.util\n"
    "missing = []\n"
    "for name in json.load(sys.stdin):\n"
    "    try:\n"
    "        if importlib.util.find_spec(name) is None:\n"
    "            missing.append(name)\n"
    "    except (ImportError, ValueError, AttributeError):\n"
    "        missing.append(name)\n"
    "print(json.dumps(missing))\n"
)


def check_imports(root, files: list[str] | None = None) -> list[SyntaxIssue]:
    """Check `files` (relative paths) or every .py file in the repo."""
    base = Path(root).resolve()
    rels = files if files is not None else [f for f in filesystem.iter_files(base) if f.endswith(".py")]
    roots = [base] + ([base / "src"] if (base / "src").is_dir() else [])
    checker = _Checker(base, roots)

    issues: list[SyntaxIssue] = []
    external: dict[str, list[tuple[str, int]]] = {}

    for rel in rels:
        if not rel.endswith(".py"):
            continue
        path = filesystem.resolve_safe(base, rel)
        tree = _parse(path)
        if tree is None:
            continue                      # syntax errors are reported by syntax_checker
        collector = _Collector()
        collector.visit(tree)
        for line, module, names, level in collector.imports:
            if level:
                issues.extend(checker.check_local(rel, line, module, names, level, path))
                continue
            top = module.split(".")[0]
            if checker.is_local(top):
                issues.extend(checker.check_local(rel, line, module, names, 0, path))
            else:
                external.setdefault(top, []).append((rel, line))

    if external:
        for top in _missing_in_env(base, sorted(external)):
            pip_name = PIP_ALIASES.get(top, top)
            for rel, line in external[top]:
                issues.append(SyntaxIssue(
                    rel, line,
                    f"No module named '{top}': it is not part of the project and not installed "
                    f"in the project's environment. If it is a real package, add '{pip_name}' to "
                    f"the dependencies and install it; otherwise fix the import.",
                ))

    return sorted(issues, key=lambda i: (i.path, i.line))


# ---------- third-party / stdlib lookup ----------
def _missing_in_env(base: Path, names: list[str]) -> list[str]:
    python = runtime.python_for(base)
    try:
        proc = subprocess.run(
            [str(python), "-I", "-c", _LOOKUP_SCRIPT],
            input=json.dumps(names), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ToolError(f"Could not check imports in the project environment: {exc}")
    if proc.returncode != 0:
        raise ToolError(f"Import lookup failed: {proc.stderr[-500:]}")
    try:
        return list(json.loads(proc.stdout))
    except json.JSONDecodeError:
        raise ToolError(f"Unexpected output from import lookup: {proc.stdout[-200:]}")


# ---------- collecting imports from a file ----------
class _Collector(ast.NodeVisitor):
    """Collects (line, module, names, level). names is None for a plain `import x`."""

    def __init__(self) -> None:
        self.imports: list[tuple[int, str, list[str] | None, int]] = []
        self._optional = 0

    def visit_Import(self, node: ast.Import) -> None:
        if not self._optional:
            for alias in node.names:
                self.imports.append((node.lineno, alias.name, None, 0))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._optional or node.module == "__future__":
            return
        self.imports.append((node.lineno, node.module or "", [a.name for a in node.names], node.level))

    def visit_Try(self, node: ast.Try) -> None:
        optional = any(_catches_import_error(h) for h in node.handlers)
        self._optional += optional
        for stmt in node.body:
            self.visit(stmt)
        self._optional -= optional
        for handler in node.handlers:
            self.visit(handler)
        for stmt in node.orelse + node.finalbody:
            self.visit(stmt)

    visit_TryStar = visit_Try

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            self._optional += 1
            for stmt in node.body:
                self.visit(stmt)
            self._optional -= 1
            for stmt in node.orelse:
                self.visit(stmt)
        else:
            self.generic_visit(node)


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    exc = handler.type
    if exc is None:
        return True
    items = exc.elts if isinstance(exc, ast.Tuple) else [exc]
    return any(isinstance(i, ast.Name) and i.id in _OPTIONAL_EXC for i in items)


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError, OSError):
        return None


# ---------- resolving local and relative imports ----------
class _Checker:
    def __init__(self, base: Path, roots: list[Path]) -> None:
        self.base = base
        self.roots = roots
        self._names: dict[Path, set[str] | None] = {}

    def is_local(self, top: str) -> bool:
        return any((r / top).is_dir() or (r / f"{top}.py").is_file() for r in self.roots)

    def check_local(self, rel, line, module, names, level, path) -> list[SyntaxIssue]:
        parts = [p for p in module.split(".") if p]
        shown = "." * level + module

        if level:
            folder = path.parent
            for _ in range(level - 1):
                folder = folder.parent
            if folder != self.base and self.base not in folder.parents:
                return [SyntaxIssue(rel, line, f"Relative import '{shown}' goes above the project root.")]
            target = folder if not parts else _find([folder], parts)
        else:
            target = _find(self.roots, parts)

        if target is None:
            return [SyntaxIssue(rel, line, f"Cannot find module '{shown}' in the project.")]

        issues = []
        for name in names or []:
            if name != "*" and not self._has_name(target, name):
                issues.append(SyntaxIssue(rel, line, f"Cannot import name '{name}' from '{shown}': it is not defined there."))
        return issues

    def _has_name(self, target: Path, name: str) -> bool:
        if target.is_dir():
            if (target / name).is_dir() or (target / f"{name}.py").is_file():
                return True
            init = target / "__init__.py"
            if not init.is_file():
                return False
            return self._defined(init, name)
        return self._defined(target, name)

    def _defined(self, path: Path, name: str) -> bool:
        if path not in self._names:
            self._names[path] = _top_level_names(path)
        names = self._names[path]
        return True if names is None else name in names     # None = cannot tell, assume ok


def _find(search: list[Path], parts: list[str]) -> Path | None:
    """Return the module file or package folder for dotted `parts`, or None."""
    for start in search:
        cur = start
        for i, part in enumerate(parts):
            if (cur / part).is_dir():
                cur = cur / part
            elif i == len(parts) - 1 and (cur / f"{part}.py").is_file():
                return cur / f"{part}.py"
            else:
                break
        else:
            return cur
    return None


def _top_level_names(path: Path) -> set[str] | None:
    """Names a module defines at its top level, or None when that cannot be known."""
    tree = _parse(path)
    if tree is None:
        return None
    names: set[str] = set()
    unknown = False

    def targets(node: ast.expr) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                targets(item)

    def walk(body: list[ast.stmt]) -> None:
        nonlocal unknown
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                if node.name == "__getattr__":
                    unknown = True
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    targets(t)
            elif isinstance(node, ast.AnnAssign):
                targets(node.target)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    names.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    if a.name == "*":
                        unknown = True
                    else:
                        names.add(a.asname or a.name)
            elif isinstance(node, ast.If):
                walk(node.body)
                walk(node.orelse)
            elif isinstance(node, (ast.Try, getattr(ast, "TryStar", ast.Try))):
                walk(node.body)
                for h in node.handlers:
                    walk(h.body)
                walk(node.orelse)
                walk(node.finalbody)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                walk(node.body)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                walk(node.body)
                walk(node.orelse)

    walk(tree.body)
    return None if unknown else names