"""The shared LangGraph state.

total=False means every key is optional, so nodes can use state.get(...)
and the first turn does not need every key present.
"""
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from src.state.schemas import (
    CodebaseSummary,
    IssueReport,
    Patch,
    Plan,
    RootCause,
    Task,
)


class AgentState(TypedDict, total=False):
    # ---- conversation (kept across turns) ----
    messages: Annotated[list[AnyMessage], add_messages]   # reducer appends instead of overwriting
    user_query: str
    repo_path: str | None

    # ---- planner ----
    plan: Plan | None
    query_type: Literal["bug_fix", "new_project", "chat"] | None
    skipped_tasks: list[Task]          # planned for agents that are not built yet

    # ---- codebase agent ----
    repo_tree: str | None
    docs: dict[str, str]               # relative path -> content
    candidate_files: list[str]
    codebase_summary: CodebaseSummary | None

    # ---- issue agent ----
    issue_report: IssueReport | None
    root_cause: RootCause | None
    patch: Patch | None
    backup_id: str | None
    step_error: str | None             # set by any failing deterministic node
    feedback: list[str]                # failure notes fed to the next patch attempt
    attempt: int
    issue_status: Literal["fixed", "not_reproducible", "failed"] | None
    error_context: str | None          # real error + code around it, from the syntax checker
    error_line: int | None