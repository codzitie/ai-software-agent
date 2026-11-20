"""Run a reproduction command or the test suite, under strict command rules.

Allowed: `pytest [-x -q -v -s -k EXPR -m EXPR --tb=... --maxfail=N] [paths[::test]]`
and `python <script inside repo>.py [args]`. No shell is used.
"""
import os
import re
import shlex
import subprocess
from pathlib import Path

from config import settings
from src.state.schemas import TestResult
from src.tools import filesystem, runtime
from src.utils.errors import ToolError, UnsafeCommandError

_FORBIDDEN = re.compile(r"[;&|<>`$\n\r(){}]")
_PYTEST_FLAGS = {"-x", "-q", "-v", "-vv", "-s", "-l", "--lf", "--ff"}
_PYTEST_PREFIXES = ("--tb=", "--maxfail=")
_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def run(root, command: str | None, timeout: int = 120) -> TestResult:
    base = Path(root).resolve()

    if command is None:
        command = _default_command(base)
        if command is None:
            return TestResult(
                passed=False, command=None, exit_code=None,
                output="No test command was given and no test suite was found, "
                       "so the result cannot be confirmed.",
            )

    argv = _build_argv(base, command)
    python = runtime.python_for(base)

    try:
        proc = subprocess.run(
            [str(python), *argv], cwd=base, env=_clean_env(),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return TestResult(
            passed=False, command=command, exit_code=None,
            output=f"Timed out after {timeout}s.\n{partial[-settings.TEST_OUTPUT_CHARS:]}",
        )

    output = (proc.stdout + proc.stderr)[-settings.TEST_OUTPUT_CHARS:]
    return TestResult(passed=proc.returncode == 0, output=output, command=command, exit_code=proc.returncode)


# ---------- command validation ----------
def _build_argv(base: Path, command: str) -> list[str]:
    if _FORBIDDEN.search(command):
        raise UnsafeCommandError("Shell operators are not allowed in test commands.")
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        raise UnsafeCommandError(f"Could not parse command: {exc}")
    if not parts:
        raise UnsafeCommandError("Empty command.")

    head, rest = parts[0], parts[1:]
    if head == "python" or head == "python3":
        if rest[:2] == ["-m", "pytest"]:
            head, rest = "pytest", rest[2:]
        elif rest[:2] == ["-m", "py_compile"] and len(rest) == 3 and rest[2].endswith(".py"):
            if not _inside(base, rest[2]):
                raise UnsafeCommandError(f"File is outside the repository: {rest[2]}")
            return rest
        elif rest and rest[0].endswith(".py"):
            if not _inside(base, rest[0]):
                raise UnsafeCommandError(f"Script is outside the repository: {rest[0]}")
            return rest
        else:
            raise UnsafeCommandError("Only 'pytest ...' or 'python <script>.py' are allowed.")

    if head != "pytest":
        raise UnsafeCommandError(f"Command not allowed: {head}")

    _check_pytest_args(base, rest)
    return ["-m", "pytest", "-p", "no:cacheprovider", *rest]


def _check_pytest_args(base: Path, args: list[str]) -> None:
    it = iter(args)
    for arg in it:
        if arg in ("-k", "-m"):
            if next(it, None) is None:
                raise UnsafeCommandError(f"Option {arg} needs a value.")
        elif arg in _PYTEST_FLAGS or arg.startswith(_PYTEST_PREFIXES):
            continue
        elif arg.startswith("-"):
            raise UnsafeCommandError(f"pytest option not allowed: {arg}")
        elif not _inside(base, arg):
            raise UnsafeCommandError(f"Path is outside the repository: {arg}")


def _inside(base: Path, arg: str) -> bool:
    try:
        filesystem.resolve_safe(base, arg.split("::")[0])
        return True
    except ToolError:
        return False


def _default_command(base: Path) -> str | None:
    for rel in filesystem.iter_files(base):
        name = rel.rsplit("/", 1)[-1]
        if rel.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py")):
            return "pytest -x -q"
    return None


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not any(h in k.upper() for h in _SECRET_HINTS)}
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env