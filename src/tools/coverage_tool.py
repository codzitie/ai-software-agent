"""Were the changed lines actually executed by the tests?

    report = coverage_tool.check_changed(root, changes, "pytest -q tests/test_calc.py")
    if not report.available:   ...   # coverage not installed: ask the user before installing
    report.fully_covered, report.files[0].uncovered_symbols, coverage_tool.summarize(report)

`changes` are the FileChange objects from diff_reader.analyze (they carry the changed line
numbers and the changed functions).

How it works:
  * runs `python -m coverage run --source=. -m pytest ...` with the project's own venv python
  * the command is validated by test_runner (same rules: pytest only, a short list of flags,
    paths inside the repo, no shell), so the safety rules live in one place
  * the coverage data file lives in a temp folder, never in the repo; project coverage config
    ([tool.coverage], .coveragerc) is still honoured (omit, source, ...)
  * a changed line counts as covered/uncovered only if coverage can measure it; blank lines,
    comments and docstrings are ignored. A changed file that coverage did not report at all
    is flagged measured=False and all its changed lines count as uncovered.
  * installs nothing: if the coverage package is missing, the report says so
"""
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.tools import runtime
from src.tools.diff_reader import FileChange
from src.tools.test_runner import _build_argv, _clean_env     # reuse the one set of command rules
from src.utils.logging import get_logger

log = get_logger("coverage")

REPORT_TIMEOUT = 60
OUTPUT_CHARS = 4000


@dataclass
class FileCoverage:
    path: str
    measured: bool                                  # False: coverage did not report this file
    changed_total: int = 0                          # changed lines coverage can measure
    changed_covered: int = 0
    uncovered: list[tuple[int, int]] = field(default_factory=list)   # ranges of changed, unexecuted lines
    uncovered_symbols: list[str] = field(default_factory=list)       # innermost changed symbol, or "module level"

    @property
    def percent(self) -> float | None:
        return round(100 * self.changed_covered / self.changed_total, 1) if self.changed_total else None


@dataclass
class CoverageReport:
    available: bool                                 # False: the coverage package is not installed
    tests_ran: bool = False                         # pytest ran (exit 0 or 1)
    tests_passed: bool = False
    output: str = ""                                # tail of the test output, or the reason it failed
    files: list[FileCoverage] = field(default_factory=list)

    @property
    def fully_covered(self) -> bool:
        """Tests ran and every changed file was measured with no uncovered changed line.
        True also when there was nothing to measure (check `files` if that matters)."""
        return self.available and self.tests_ran and all(f.measured and not f.uncovered for f in self.files)

    @property
    def overall(self) -> float | None:
        total = sum(f.changed_total for f in self.files)
        return round(100 * sum(f.changed_covered for f in self.files) / total, 1) if total else None


# ---------------------------------------------------------------- helpers
def _is_test_file(path: str) -> bool:
    p = Path(path)
    return (p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py"
            or any(part in ("tests", "test") for part in p.parts[:-1]))


def _ranges(lines: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for n in sorted(set(lines)):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def _run(base: Path, python: Path, args: list[str], env: dict, timeout: int):
    return subprocess.run([str(python), *args], cwd=base, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def is_available(root) -> bool:
    """Is the coverage package installed in the project's environment? (Creates the venv if none.)"""
    base = Path(root).resolve()
    try:
        return _run(base, runtime.python_for(base), ["-m", "coverage", "--version"],
                    _clean_env(), 30).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _owner(symbols, line: int) -> str:
    inside = [s for s in symbols if s.start <= line <= s.end]
    return min(inside, key=lambda s: s.end - s.start).name if inside else "module level"


def _file_coverage(ch: FileChange, data: dict | None) -> FileCoverage:
    changed = ch.changed_lines
    if data is None:                                 # not in coverage's report at all
        return FileCoverage(ch.path, False, len(changed), 0, _ranges(changed),
                            sorted({_owner(ch.symbols, n) for n in changed}))
    executed, missing = set(data["executed_lines"]), set(data["missing_lines"])
    measurable = [n for n in changed if n in executed or n in missing]
    uncovered = [n for n in measurable if n in missing]
    return FileCoverage(
        ch.path, True, len(measurable), len(measurable) - len(uncovered), _ranges(uncovered),
        sorted({_owner(ch.symbols, n) for n in uncovered}),
    )


# ---------------------------------------------------------------- main entry point
def check_changed(root, changes: list[FileChange], command: str = "pytest -q",
                  timeout: int = 300, ignore_tests: bool = True) -> CoverageReport:
    """Run the tests under coverage and report how much of the changed code they executed.

    command: a pytest command, validated by test_runner (UnsafeCommandError if not allowed).
    ignore_tests: skip changed test files, so only real code is judged.
    """
    base = Path(root).resolve()
    argv = _build_argv(base, command)                # raises UnsafeCommandError for anything unsafe
    if argv[:2] != ["-m", "pytest"]:
        return CoverageReport(True, output="Coverage runs pytest commands only.")

    targets = [c for c in changes
               if c.path.endswith(".py") and c.status != "D" and not c.binary
               and not (ignore_tests and _is_test_file(c.path))]

    python = runtime.python_for(base)
    if not is_available(base):
        return CoverageReport(
            False, output="The coverage package is not installed in this project's environment. "
                          "Install it (with the user's approval) or skip the coverage check.")

    with tempfile.TemporaryDirectory(prefix="agent-cov-") as tmp:
        env = {**_clean_env(), "COVERAGE_FILE": str(Path(tmp) / "data")}   # wins over project config
        out_json = Path(tmp) / "report.json"
        try:
            proc = _run(base, python, ["-m", "coverage", "run", "--source=.", *argv], env, timeout)
        except subprocess.TimeoutExpired:
            return CoverageReport(True, output=f"Tests timed out after {timeout}s under coverage.")

        text = (proc.stdout + proc.stderr)[-OUTPUT_CHARS:]
        ran = proc.returncode in (0, 1)              # 1 = tests failed; still measured
        if not ran or not (Path(tmp) / "data").exists():
            return CoverageReport(True, False, False, text)

        try:
            rep = _run(base, python, ["-m", "coverage", "json", "-o", str(out_json)], env, REPORT_TIMEOUT)
            files = json.loads(out_json.read_text(encoding="utf-8"))["files"]
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
            return CoverageReport(True, True, proc.returncode == 0,
                                  text + "\n[could not read the coverage report]")
        if rep.returncode != 0:
            return CoverageReport(True, True, proc.returncode == 0,
                                  text + f"\n[coverage json failed: {rep.stderr.strip()[:300]}]")

    by_path = {}                                     # normalise coverage's keys to repo-relative posix paths
    for key, data in files.items():
        p = Path(key)
        try:
            by_path[(p if p.is_absolute() else base / p).resolve().relative_to(base).as_posix()] = data
        except ValueError:                           # outside the project folder
            by_path[key] = data

    result = [_file_coverage(c, by_path.get(c.path)) for c in targets]
    log.info("coverage: %s", {f.path: f.percent for f in result})
    return CoverageReport(True, True, proc.returncode == 0, text, result)


def summarize(report: CoverageReport) -> str:
    """Short text for a prompt: what is covered and exactly which changed code is not."""
    if not report.available:
        return report.output
    if not report.tests_ran:
        return f"Tests did not run under coverage:\n{report.output}"
    head = "Tests passed." if report.tests_passed else "Some tests FAILED."
    if not report.files:
        return f"{head} No changed Python source files to measure."
    lines = [f"{head} Coverage of changed lines: "
             f"{report.overall if report.overall is not None else 'n/a'}%"]
    for f in report.files:
        if not f.measured:
            lines.append(f"- {f.path}: not measured by coverage (never imported, or omitted by config)")
        elif f.uncovered:
            spans = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in f.uncovered)
            lines.append(f"- {f.path}: {f.percent}% - uncovered lines {spans} (in {', '.join(f.uncovered_symbols)})")
        else:
            lines.append(f"- {f.path}: {f.percent if f.percent is not None else 'n/a'}% - all measurable changed lines covered")
    return "\n".join(lines)