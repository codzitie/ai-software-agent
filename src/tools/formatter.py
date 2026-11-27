"""Format and lint-fix Python files with ruff, using the project's own venv.

Never installs anything. If ruff is missing the result says so, and the caller
decides (the Developer agent asks the user before installing).

All-or-nothing: if ruff fails, every file is put back exactly as it was.
Ruff's cache is switched off so no .ruff_cache folder appears in the repo.
"""
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from src.tools import filesystem, runtime
from src.utils.logging import get_logger

log = get_logger("formatter")

TIMEOUT = 60
_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_LINT_LINE = re.compile(r"^\S+:\d+:\d+:")      # "path.py:3:1: F401 ..." in concise output


@dataclass
class FormatResult:
    available: bool                 # False only when ruff was looked for and not found
    ok: bool                        # ruff ran without an error of its own
    changed: list[str] = field(default_factory=list)     # files whose content changed
    remaining: list[str] = field(default_factory=list)   # lint problems ruff could not fix
    output: str = ""


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not any(h in k.upper() for h in _SECRET_HINTS)}
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    return env


def _ruff(base: Path, python: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(python), "-m", "ruff", *args], cwd=base, env=_env(),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT,
    )


def _has_ruff(base: Path, python: Path) -> bool:
    try:
        return _ruff(base, python, ["--version"]).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def is_available(root) -> bool:
    """Is ruff installed in the project's environment? (Creates the venv if there is none.)"""
    base = Path(root).resolve()
    return _has_ruff(base, runtime.python_for(base))


def _select(base: Path, files: list[str]) -> list[str]:
    """Existing .py files, as unique repo-relative posix paths. Raises ToolError outside the repo."""
    out = set()
    for rel in files:
        path = filesystem.resolve_safe(base, rel)
        if path.suffix == ".py" and path.is_file():
            out.add(path.relative_to(base).as_posix())
    return sorted(out)


def format_files(root, files: list[str], lint_fix: bool = True,
                 line_length: int | None = None) -> FormatResult:
    """Lint-fix (safe fixes only) then format the given files.

    line_length: pass it only when the project has no ruff config of its own;
    otherwise ruff reads the project's pyproject.toml / ruff.toml.
    __init__.py files are formatted but not lint-fixed, because removing "unused"
    imports there would break re-exports.
    """
    base = Path(root).resolve()
    targets = _select(base, files)
    if not targets:
        return FormatResult(True, True, output="No Python files to format.")

    python = runtime.python_for(base)
    if not _has_ruff(base, python):
        return FormatResult(
            False, False,
            output="ruff is not installed in this project's environment. "
                   "Install it (with the user's approval) or skip formatting.",
        )

    before = {rel: (base / rel).read_bytes() for rel in targets}
    opts = ["--line-length", str(line_length)] if line_length else []
    remaining: list[str] = []
    notes: list[str] = []

    def restore() -> None:
        for rel, data in before.items():
            (base / rel).write_bytes(data)

    try:
        lint_targets = [t for t in targets if not t.endswith("__init__.py")]
        if lint_fix and lint_targets:
            proc = _ruff(base, python, ["check", "--fix", "--no-cache", "--output-format", "concise",
                                        *opts, "--", *lint_targets])
            if proc.returncode >= 2:                       # 1 just means "problems remain"
                restore()
                return FormatResult(True, False, output=f"ruff check failed:\n{proc.stderr[-1500:]}")
            remaining = [ln for ln in proc.stdout.splitlines() if _LINT_LINE.match(ln)]
            notes.append(f"lint: {len(remaining)} problem(s) left")

        proc = _ruff(base, python, ["format", "--no-cache", *opts, "--", *targets])
        if proc.returncode != 0:
            restore()
            return FormatResult(True, False, output=f"ruff format failed:\n{proc.stderr[-1500:]}")
        notes.append(proc.stdout.strip() or "format: done")
    except (subprocess.TimeoutExpired, OSError) as exc:
        restore()
        return FormatResult(True, False, output=f"ruff could not run: {exc!r}")

    changed = [rel for rel in targets if (base / rel).read_bytes() != before[rel]]
    log.info("formatted %d file(s), %d changed", len(targets), len(changed))
    return FormatResult(True, True, changed, remaining, "\n".join(notes))