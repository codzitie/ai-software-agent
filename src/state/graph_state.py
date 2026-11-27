"""The shared LangGraph state.

total=False means every key is optional, so nodes can use state.get(...)
and the first turn does not need every key present.
"""
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from src.state.schemas import (
    CodebaseSummary,
    DevTask,
    GeneratedFile,
    IssueReport,
    Patch,
    Plan,
    RootCause,
    Task,
    TestPlan,
)
from src.tools.models import ProjectInfo


class AgentState(TypedDict, total=False):
    # ---- conversation (kept across turns) ----
    messages: Annotated[list[AnyMessage], add_messages]
    user_query: str
    repo_path: str | None

    # ---- planner ----
    plan: Plan | None
    query_type: Literal["bug_fix", "new_project", "new_feature", "chat"] | None
    skipped_tasks: list[Task]

    # ---- codebase agent ----
    repo_tree: str | None
    docs: dict[str, str]
    candidate_files: list[str]
    codebase_summary: CodebaseSummary | None

    # ---- issue agent ----
    issue_report: IssueReport | None
    root_cause: RootCause | None
    patch: Patch | None
    backup_id: str | None
    step_error: str | None
    feedback: list[str]
    attempt: int
    issue_status: Literal["fixed", "not_reproducible", "failed"] | None
    error_context: str | None
    error_line: int | None

    # ---- developer agent ----
    dev_task: DevTask | None
    project_info: ProjectInfo | None
    file_index: int
    generated_file: GeneratedFile | None
    created_files: list[str]
    step_written: list[str]
    step_manifest: list[str]
    touched_files: list[str]
    applied_backups: list[str]
    installed_packages: list[str]
    declined_packages: list[str]
    pending_install: list[str]
    git_task: dict | None
    last_good_sha: str | None
    tools_checked: bool
    format_enabled: bool
    dev_status: Literal["done", "failed"] | None
    dev_report: str | None

    # ---- tester agent ----
    test_plan: TestPlan | None
    test_queue: list[str]
    tests_written: list[str]
    test_generated: GeneratedFile | None
    tester_attempt: int
    tester_error: str | None
    tester_feedback: list[str]
    tester_step_written: list[str]
    file_notes: dict[str, str]
    failure_records: list[dict]
    tester_action: str | None
    test_summary: str
    test_fix_rounds: int
    tester_env_rounds: int
    coverage_gaps: str
    coverage_note: str
    coverage_rounds: int
    coverage_declined: bool
    tester_status: Literal["passed", "skipped", "implementation_bug", "blocked", "failed"] | None
    tester_report: str | None