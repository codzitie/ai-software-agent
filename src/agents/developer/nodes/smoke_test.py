"""Deterministic: after the last file, check all imports and run the plan's test command."""
from src.state.graph_state import AgentState
from src.tools import import_checker, test_runner
from src.tools.test_result_parser import parse_pytest_output
from src.utils.errors import ToolError, UnsafeCommandError


def _fail(message: str) -> dict:
    return {"step_error": message, "attempt": 99}     # 99: do not retry, go to finalize


def smoke_test_node(state: AgentState) -> dict:
    root, task = state["repo_path"], state["dev_task"]
    touched = [p for p in state.get("touched_files", []) if p.endswith(".py")]

    if touched:
        try:
            issues = import_checker.check_imports(root, touched)
        except ToolError as exc:
            return _fail(f"Import check failed: {exc}")
        if issues:
            return _fail("Imports do not resolve after all files were written:\n"
                         + "\n".join(f"{i.path}:{i.line}: {i.message}" for i in issues[:10]))

    command = task.test_command.strip() or "pytest -q"
    if command.startswith("pytest") and "--tb" not in command:
        command += " --tb=short"
    try:
        result = test_runner.run(root, command)
    except UnsafeCommandError:
        command = "pytest -q --tb=short"
        result = test_runner.run(root, command)

    if result.exit_code is None and "No test command" not in result.output:
        return _fail(f"The test command did not finish:\n{result.output[-1500:]}")
    if not command.startswith("pytest"):
        return {"step_error": None} if result.passed else _fail(result.output[-2000:])

    parsed = parse_pytest_output(result.output, result.exit_code, root=str(root), changed_files=touched)
    if parsed.no_tests or parsed.ok:           # the Tester agent adds tests later
        return {"step_error": None}
    return _fail("Tests failed after the changes:\n" + parsed.format_for_llm())