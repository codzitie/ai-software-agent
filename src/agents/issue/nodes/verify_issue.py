"""LLM node 1: decide whether the issue is real, backed by an actual run."""
from langchain_core.messages import HumanMessage, SystemMessage

from config.settings import load_prompt
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.state.schemas import IssueReport
from src.tools import filesystem, syntax_checker, test_runner

MAX_FILE_CHARS = 5000


def verify_issue_node(state: AgentState) -> dict:
    root = state["repo_path"]
    summary = state["codebase_summary"]

    files_text = "\n\n".join(
        f"### {n.path}\n{filesystem.read_file(root, n.path, max_chars=MAX_FILE_CHARS)}"
        for n in summary.relevant_files
    )

    llm = get_llm().with_structured_output(IssueReport)
    report: IssueReport = llm.invoke(
        [
            SystemMessage(content=load_prompt("verify_issue")),
            HumanMessage(
                content=(
                    f"Issue:\n{state['user_query']}\n\n"
                    f"Architecture notes:\n{summary.architecture_notes}\n\n"
                    f"Suspected area:\n{summary.suspected_area}\n\n"
                    f"Relevant code:\n{files_text}\n\n"
                    "Propose a command that reproduces the issue (a failing test or script). "
                    "If no command is possible, judge from the code alone."
                )
            ),
        ]
    )

    from src.utils.errors import UnsafeCommandError

    syntax_issues = syntax_checker.check_files(
        root, [n.path for n in summary.relevant_files]
    )

    error_context, error_line = None, None

    if syntax_issues:
        first = syntax_issues[0]
        window = ""

        if first.line:
            window = filesystem.read_window(
                root, first.path, first.line, radius=15, numbered=True
            )

        error_context = (
            f"Syntax checker found: {first.path}:{first.line}: {first.message}\n"
            f"(line numbers below are for reference only, never include them in an edit)\n{window}"
        )

        error_line = first.line
        report.reproducible = True
        report.evidence = error_context
        report.repro_command = None

    if report.repro_command and not syntax_issues:
        try:
            result = test_runner.run(
                root, report.repro_command, timeout=120
            )
        except UnsafeCommandError as exc:
            report.evidence += (
                f"\n\nReproduction command was blocked ({exc}). "
                "Judged from the code only."
            )
            report.repro_command = None
        else:
            if result.exit_code == 1:
                report.reproducible = True
            elif result.exit_code == 0:
                report.reproducible = False

            report.evidence += (
                f"\n\nCommand output (exit {result.exit_code}):\n"
                f"{result.output[-2000:]}"
            )

    # Initialize update AFTER all verification logic
    update: dict = {
        "issue_report": report,
        "attempt": 0,
        "feedback": [],
        "error_context": error_context,
        "error_line": error_line,
    }

    if not report.reproducible:
        update["issue_status"] = "not_reproducible"

    return update
