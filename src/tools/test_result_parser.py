"""Parse pytest console output into structured results.

Two jobs:
  1. Extract counts and per-failure details (nodeid, error type, crash location).
  2. Decide, heuristically, whether each failure points at a faulty TEST, a
     faulty IMPLEMENTATION, the ENVIRONMENT, or is AMBIGUOUS (needs an LLM
     or human judgement).

Heuristics are deliberately conservative. The key idea is that a test which
already existed and passed before the change, but fails now, is far more
likely to expose an implementation bug than a test bug. A freshly generated
test that fails an assertion is genuinely ambiguous.

Recommended pytest flags:  -rfE --tb=short --color=no -p no:cacheprovider
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

# ---- verdicts -------------------------------------------------------------
TEST_BUG = "test_bug"
IMPL_BUG = "implementation_bug"
ENVIRONMENT = "environment"
AMBIGUOUS = "ambiguous"

# ---- recommended actions (see ParsedResults.primary_action) ---------------
ACTION_DONE = "done"
ACTION_NO_TESTS = "no_tests"
ACTION_FIX_ENV = "fix_environment"
ACTION_FIX_TESTS = "fix_tests"
ACTION_FIX_IMPL = "fix_implementation"
ACTION_REVIEW = "review_ambiguous"

# ---- regexes --------------------------------------------------------------
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_SECTION = re.compile(r"^={3,} (?P<title>.+?) ={3,}$")
_CASE = re.compile(r"^_{2,} (?P<title>.+?) _{2,}$")
_FRAME = re.compile(r"^(?P<path>(?:[A-Za-z]:)?[^\s:]+\.py):(?P<line>\d+): ?(?P<rest>.*)$")
_ERRLINE = re.compile(r"^E(?:\s+(?P<text>.*))?$")
_SHORT = re.compile(
    r"^(?P<status>FAILED|ERROR|PASSED|SKIPPED|XFAIL|XPASS) (?P<nodeid>.+?)(?: - (?P<msg>.*))?$"
)
_COUNT = re.compile(r"(\d+) (failed|passed|skipped|deselected|xfailed|xpassed|warnings?|errors?|rerun)")
_DURATION = re.compile(r" in (\d+(?:\.\d+)?)s")
_FILE_LINE_IN_E = re.compile(r'File "(?P<path>.+?)", line (?P<line>\d+)')
_ERR_TYPE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::|$)")
_NO_MODULE = re.compile(r"No module named '(?P<mod>[\w.]+)'")
_CANNOT_IMPORT = re.compile(r"cannot import name '(?P<name>\w+)'")
_INTERNAL_PATH = re.compile(r"(site-packages|/lib/python\d|\\lib\\python|importlib|_pytest|pluggy)")

_ENV_TYPES = {
    "ConnectionError", "ConnectionRefusedError", "TimeoutError", "PermissionError",
    "BrokenPipeError", "KeyboardInterrupt", "MemoryError", "Timeout",
}
_TEST_ONLY_TYPES = {"NameError", "UnboundLocalError", "FixtureLookupError"}
_SIGNATURE_HINTS = ("unexpected keyword argument", "positional argument", "required positional")
_ENV_HINTS = ("Permission denied", "No space left", "Connection refused", "timed out")


# ---- data classes ---------------------------------------------------------
@dataclass
class FailedTest:
    nodeid: str
    file: str
    outcome: str                      # "failed" | "error" | "collection_error"
    error_type: str | None = None
    message: str = ""
    traceback: str = ""
    crash_file: str | None = None     # last project frame (where it blew up)
    crash_line: int | None = None
    crash_func: str | None = None
    verdict: str = AMBIGUOUS
    confidence: str = "low"           # "high" | "medium" | "low"
    reason: str = ""


@dataclass
class ParsedResults:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    deselected: int = 0
    duration: float | None = None
    exit_code: int | None = None
    failures: list[FailedTest] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped + self.xfailed + self.xpassed

    @property
    def no_tests(self) -> bool:
        return self.exit_code == 5 or (self.total == 0 and not self.failures)

    @property
    def ok(self) -> bool:
        if self.no_tests:
            return False
        if self.exit_code is not None:
            return self.exit_code == 0
        return self.failed == 0 and self.errors == 0 and self.passed > 0

    def by_verdict(self) -> dict[str, list[FailedTest]]:
        out: dict[str, list[FailedTest]] = {TEST_BUG: [], IMPL_BUG: [], ENVIRONMENT: [], AMBIGUOUS: []}
        for f in self.failures:
            out[f.verdict].append(f)
        return out

    @property
    def primary_action(self) -> str:
        """What the caller should do next. Order: env, tests, implementation, review."""
        if self.ok:
            return ACTION_DONE
        groups = self.by_verdict()
        if groups[ENVIRONMENT]:
            return ACTION_FIX_ENV
        if groups[TEST_BUG]:
            return ACTION_FIX_TESTS
        if groups[IMPL_BUG]:
            return ACTION_FIX_IMPL
        if groups[AMBIGUOUS]:
            return ACTION_REVIEW
        if self.no_tests:
            return ACTION_NO_TESTS
        return ACTION_REVIEW

    def summary(self) -> str:
        parts = [f"{n} {label}" for n, label in (
            (self.failed, "failed"), (self.errors, "errors"), (self.passed, "passed"),
            (self.skipped, "skipped"), (self.xfailed, "xfailed"), (self.xpassed, "xpassed"),
        ) if n]
        text = ", ".join(parts) or "no tests ran"
        return f"{text} in {self.duration:.2f}s" if self.duration is not None else text

    def format_for_llm(self, max_chars: int = 6000, per_failure_chars: int = 900) -> str:
        """Compact, verdict-annotated report suitable for an LLM prompt."""
        lines = [f"Result: {self.summary()} (action: {self.primary_action})"]
        for f in self.failures:
            loc = f"{f.crash_file}:{f.crash_line}" if f.crash_file else "unknown location"
            block = [
                f"\n- {f.nodeid}  [{f.outcome}]",
                f"  verdict: {f.verdict} ({f.confidence}) - {f.reason}",
                f"  error: {f.error_type or '?'} at {loc}",
            ]
            if f.message:
                block.append("  message: " + f.message.replace("\n", "\n    "))
            text = "\n".join(block)
            lines.append(text[:per_failure_chars])
            if sum(len(x) for x in lines) > max_chars:
                lines.append("\n... (more failures truncated)")
                break
        return "\n".join(lines)


@dataclass
class _Ctx:
    root: str | None
    changed_files: set[str]
    new_test_files: set[str]
    defined_symbols: set[str] | None


# ---- public API -----------------------------------------------------------
def parse_pytest_output(
    output: str,
    exit_code: int | None = None,
    *,
    root: str | None = None,
    changed_files: Iterable[str] | None = None,
    new_test_files: Iterable[str] | None = None,
    defined_symbols: Iterable[str] | None = None,
) -> ParsedResults:
    """Parse pytest output.

    changed_files:   source files touched by the diff (from diff_reader).
    new_test_files:  test files generated in THIS task (their failures are
                     ambiguous; pre-existing tests that fail point at the code).
    defined_symbols: functions/classes defined in the changed files; lets us
                     spot tests importing names that do not exist.
    """
    lines = _ANSI.sub("", output or "").splitlines()
    res = ParsedResults(exit_code=exit_code)
    _parse_counts(lines, res)

    short = _parse_short_summary(lines)
    seen: set[str] = set()
    for title, body in _split_sections(lines):
        if title.upper() in ("FAILURES", "ERRORS"):
            for case_title, case_body in _split_cases(body):
                f = _build_failure(case_title, case_body, short)
                res.failures.append(f)
                seen.add(f.nodeid)

    # -q / missing detail sections: fall back to the short summary
    for status, nodeid, msg in short:
        if status in ("FAILED", "ERROR") and nodeid not in seen:
            res.failures.append(_failure_from_short(status, nodeid, msg))

    # exit code 2 + "error during collection" but no parsed detail
    if exit_code == 2 and not res.failures and "error" in (output or "").lower():
        res.failures.append(FailedTest(
            nodeid="<collection>", file="", outcome="collection_error",
            message=(output or "")[-800:],
        ))

    ctx = _Ctx(
        root=root.replace("\\", "/").rstrip("/") if root else None,
        changed_files={_norm(p, root) for p in (changed_files or [])},
        new_test_files={_norm(p, root) for p in (new_test_files or [])},
        defined_symbols=set(defined_symbols) if defined_symbols is not None else None,
    )
    for f in res.failures:
        _classify(f, ctx)
    if exit_code == 4 and not res.failures:     # pytest usage error (bad CLI args)
        res.failures.append(FailedTest(
            nodeid="<pytest>", file="", outcome="error", message=(output or "")[-600:],
            verdict=ENVIRONMENT, confidence="high", reason="pytest usage error (bad arguments)",
        ))
    return res


def from_test_result(test_result, **ctx) -> ParsedResults:
    """Convenience wrapper for the project's TestResult model (duck-typed)."""
    return parse_pytest_output(test_result.output, getattr(test_result, "exit_code", None), **ctx)


# ---- parsing helpers ------------------------------------------------------
def _parse_counts(lines: list[str], res: ParsedResults) -> None:
    for line in reversed(lines):
        stripped = line.strip("= ").strip()
        d = _DURATION.search(stripped)
        if not d:
            continue
        counts = _COUNT.findall(stripped)
        if not counts and "no tests ran" not in stripped:
            continue
        res.duration = float(d.group(1))
        for n, label in counts:
            n = int(n)
            if label.startswith("error"):
                res.errors = n
            elif label.startswith("warning") or label == "rerun":
                continue
            else:
                setattr(res, label, n)
        return


def _parse_short_summary(lines: list[str]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    in_block = False
    for line in lines:
        m = _SECTION.match(line)
        if m:
            in_block = m.group("title").lower().startswith("short test summary")
            continue
        if in_block:
            s = _SHORT.match(line.strip())
            if s:
                out.append((s.group("status"), s.group("nodeid"), s.group("msg") or ""))
    return out


def _split_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    for line in lines:
        m = _SECTION.match(line)
        if m:
            sections.append((m.group("title"), []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def _split_cases(body: list[str]) -> list[tuple[str, list[str]]]:
    cases: list[tuple[str, list[str]]] = []
    for line in body:
        m = _CASE.match(line)
        if m:
            cases.append((m.group("title"), []))
        elif cases:
            cases[-1][1].append(line)
    return cases


def _resolve_nodeid(name: str, short: list[tuple[str, str, str]]) -> str:
    base, sep, params = name.partition("[")
    cand = base.replace(".", "::") + (sep + params if sep else "")
    for _, nodeid, _ in short:
        if nodeid.endswith(cand):
            return nodeid
    return name


def _build_failure(title: str, body: list[str], short) -> FailedTest:
    outcome, name = "failed", title
    if title.startswith("ERROR collecting "):
        outcome, name = "collection_error", title[len("ERROR collecting "):].strip()
        nodeid = name
    elif title.startswith("ERROR at "):
        outcome = "error"
        m = re.match(r"ERROR at (?:setup|teardown) of (.+)", title)
        name = m.group(1) if m else title
        nodeid = _resolve_nodeid(name, short)
    else:
        nodeid = _resolve_nodeid(name, short)

    frames = [
        (m.group("path").replace("\\", "/"), int(m.group("line")), m.group("rest").strip())
        for m in (_FRAME.match(l) for l in body) if m
    ]
    frames = [fr for fr in frames if not _INTERNAL_PATH.search(fr[0])]

    blocks: list[list[str]] = []
    prev_err = False
    for l in body:
        m = _ERRLINE.match(l)
        if m:
            if not prev_err:
                blocks.append([])
            blocks[-1].append((m.group("text") or "").rstrip())
        prev_err = bool(m)
    last = blocks[-1] if blocks else []
    msg_lines = [x for x in last if not x.lstrip().startswith("+")][:6] or last[:6]

    f = FailedTest(
        nodeid=nodeid, file=nodeid.split("::")[0], outcome=outcome,
        message="\n".join(msg_lines).strip(),
        traceback="\n".join(body).strip()[-2500:],
    )
    f.error_type = _error_type(last[0] if last else "")
    if not f.error_type:
        for _, nid, msg in short:
            if nid == nodeid and msg:
                f.error_type = _error_type(msg)
                f.message = f.message or msg
                break

    if frames:
        f.crash_file, f.crash_line, rest = frames[-1]
        m = re.match(r"in (\S+)", rest)
        f.crash_func = m.group(1) if m else None
    else:                                           # e.g. SyntaxError: path only appears in E lines
        for text in last:
            m = _FILE_LINE_IN_E.search(text)
            if m:
                f.crash_file, f.crash_line = m.group("path").replace("\\", "/"), int(m.group("line"))
                break
    return f


def _failure_from_short(status: str, nodeid: str, msg: str) -> FailedTest:
    return FailedTest(
        nodeid=nodeid, file=nodeid.split("::")[0],
        outcome="error" if status == "ERROR" else "failed",
        error_type=_error_type(msg), message=msg,
    )


def _error_type(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if text.startswith("assert"):
        return "AssertionError"
    if text.startswith("fixture '"):
        return "FixtureLookupError"
    if text.startswith("Failed:"):
        return "Failed"
    m = _ERR_TYPE.match(text)
    if not m:
        return None
    t = m.group("type").split(".")[-1]
    ok = t.endswith(("Error", "Exception", "Exit", "Interrupt", "Warning")) or t in ("Failed", "Timeout")
    return t if ok else None


# ---- path helpers ---------------------------------------------------------
def _norm(path: str, root: str | None) -> str:
    p = path.replace("\\", "/")
    if root:
        r = root.replace("\\", "/").rstrip("/") + "/"
        if p.startswith(r):
            p = p[len(r):]
    return p[2:] if p.startswith("./") else p


def _in(path: str | None, group: set[str]) -> bool:
    if not path:
        return False
    return any(path == g or path.endswith("/" + g) or g.endswith("/" + path) for g in group)


def _is_test_file(path: str | None) -> bool:
    if not path:
        return False
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    return (name.startswith("test_") or name.endswith("_test.py")
            or name == "conftest.py" or "tests" in parts[:-1] or "test" in parts[:-1])


# ---- classification -------------------------------------------------------
def _set(f: FailedTest, verdict: str, confidence: str, reason: str) -> None:
    f.verdict, f.confidence, f.reason = verdict, confidence, reason


def _classify(f: FailedTest, ctx: _Ctx) -> None:
    if f.verdict != AMBIGUOUS or f.reason:          # already decided (e.g. usage error)
        return
    etype = f.error_type or ""
    msg = f.message
    crash = _norm(f.crash_file, ctx.root) if f.crash_file else None
    test_file = _norm(f.file, ctx.root) if f.file else None
    crash_in_test = _is_test_file(crash)
    is_new = _in(test_file, ctx.new_test_files) or _in(crash, ctx.new_test_files)

    # 1. environment
    if etype in _ENV_TYPES or any(h in msg for h in _ENV_HINTS):
        return _set(f, ENVIRONMENT, "medium", f"{etype or 'system'} error, not a logic problem")
    m = _NO_MODULE.search(msg)
    if m:
        top = m.group("mod").split(".")[0]
        if _is_local_module(top, ctx.root):
            return _set(f, AMBIGUOUS, "low",
                        f"local module '{top}' not importable: wrong import path in test, or file missing")
        return _set(f, ENVIRONMENT, "high", f"third-party package '{top}' is not installed")

    # 2. syntax errors: blame the file that contains them
    if etype in ("SyntaxError", "IndentationError", "TabError"):
        if _is_test_file(crash):
            return _set(f, TEST_BUG, "high", "syntax error in a test file")
        return _set(f, IMPL_BUG, "high", "syntax error in source file")

    # 3. imports of names that do not exist
    m = _CANNOT_IMPORT.search(msg)
    if m and ctx.defined_symbols is not None:
        if m.group("name") not in ctx.defined_symbols:
            return _set(f, TEST_BUG, "medium",
                        f"test imports '{m.group('name')}', which the changed code does not define")
        return _set(f, IMPL_BUG, "medium",
                    f"'{m.group('name')}' is defined but cannot be imported (circular import or earlier error)")
    if etype in ("ImportError", "ModuleNotFoundError") and f.outcome == "collection_error":
        return _set(f, AMBIGUOUS, "low", "test cannot import the target; check name vs implementation")

    # 4. mistakes that can only be the test's fault
    if etype in _TEST_ONLY_TYPES and (crash_in_test or etype == "FixtureLookupError"):
        return _set(f, TEST_BUG, "high", f"{etype} inside test code or fixtures")

    # 5. wrong call signature at the call site in a test
    if etype == "TypeError" and any(h in msg for h in _SIGNATURE_HINTS) and crash_in_test:
        if is_new:
            return _set(f, TEST_BUG, "medium", "new test calls the API with the wrong signature")
        return _set(f, IMPL_BUG, "medium", "existing test no longer matches the changed signature")

    # 6. unexpected exception raised inside project (non-test) code
    if crash and not crash_in_test and etype != "AssertionError":
        note = "" if not ctx.changed_files or _in(crash, ctx.changed_files) \
            else " (file not in the diff: possible regression elsewhere)"
        return _set(f, IMPL_BUG, "high", f"{etype or 'exception'} raised in source code{note}")

    # 7. failures raised in test code (assertions etc.)
    if crash_in_test or crash is None:
        if not is_new:
            return _set(f, IMPL_BUG, "medium", "pre-existing test now fails: likely a regression")
        if etype in ("AssertionError", "Failed"):
            return _set(f, AMBIGUOUS, "low",
                        "new test fails an assertion: verify expected values against the requirement")
        return _set(f, AMBIGUOUS, "low", f"{etype or 'error'} in a new test; check test and return types")

    _set(f, AMBIGUOUS, "low", "could not classify")


def _is_local_module(name: str, root: str | None) -> bool:
    if not root:
        return False
    from pathlib import Path
    r = Path(root)
    return any((r / base / f"{name}.py").exists() or (r / base / name).is_dir()
               for base in ("", "src"))