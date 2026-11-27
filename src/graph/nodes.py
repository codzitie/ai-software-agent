"""Parent-graph nodes: intake, chat reply, unsupported reply, and a post-codebase router."""
from pathlib import Path
from typing import Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from config.settings import load_prompt
from src.llm.provider import get_llm
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from src.state.graph_state import AgentState
from src.utils.logging import get_logger
from src.utils.trace import route, traced_router

log = get_logger("graph")


def _thread_id(config: RunnableConfig) -> str | None:
    return (config or {}).get("configurable", {}).get("thread_id")


def intake_node(state: AgentState, config: RunnableConfig) -> dict:
    """Start of every turn: reset per-run keys, save the issue, sync repo docs to memory."""
    repo = state.get("repo_path")
    thread_id = _thread_id(config)

    try:
        if thread_id:
            ShortTermMemory(thread_id).save_issue(state["user_query"], repo)
        if repo and Path(repo).is_dir():
            LongTermMemory.for_repo(repo).sync_docs(repo)
    except Exception:
        log.exception("Intake memory step failed")  # non-fatal

    # The checkpoint keeps old values between messages, so clear everything run-specific.
    return {
        "plan": None, "query_type": None, "skipped_tasks": [],
        "repo_tree": None, "docs": {}, "candidate_files": [], "codebase_summary": None,
        "issue_report": None, "root_cause": None, "patch": None, "backup_id": None,
        "step_error": None, "feedback": [], "attempt": 0, "issue_status": None,
        "error_context": None, "error_line": None,
        # developer
        "dev_task": None, "project_info": None, "file_index": 0, "generated_file": None,
        "created_files": [], "step_written": [], "step_manifest": [], "touched_files": [],
        "applied_backups": [], "installed_packages": [], "declined_packages": [],
        "pending_install": [], "git_task": None, "last_good_sha": None,
        "tools_checked": False, "format_enabled": False, "dev_status": None, "dev_report": None,
        # tester
        "test_plan": None, "test_queue": [], "tests_written": [], "test_generated": None,
        "tester_attempt": 0, "tester_error": None, "tester_feedback": [],
        "tester_step_written": [], "file_notes": {}, "failure_records": [],
        "tester_action": None, "test_summary": "", "test_fix_rounds": 0,
        "tester_env_rounds": 0, "coverage_gaps": "", "coverage_note": "", "coverage_rounds": 0,
        "coverage_declined": False, "tester_status": None, "tester_report": None,
    }


def chat_reply_node(state: AgentState, config: RunnableConfig) -> dict:
    """General chat, or a polite request for what a bug fix is missing."""
    qt = state.get("query_type")
    if qt in ("bug_fix", "new_feature", "new_project"):
        repo = state.get("repo_path")
        if not repo:
            text = (
                "I can do that, but I need a repository path first. "
                "Set it with `/repo <path>` and send your request again."
                + (" For a new project, use a folder that does not exist yet or is empty."
                   if qt == "new_project" else "")
            )
        elif not Path(repo).is_dir():
            text = (f"The folder `{repo}` does not exist. Set an existing repository with "
                    "`/repo <path>` and send your request again.")
        else:
            text = (
                "I searched the repository but could not find code related to this. "
                "Can you mention a file name, function, or the exact error message?"
            )
        return {"messages": [AIMessage(content=text)]}

    thread_id = _thread_id(config)
    messages = state["messages"]
    summary, recent = (None, messages)
    if thread_id:
        summary, recent = ShortTermMemory(thread_id).compact_history(messages)

    system = load_prompt("chat")
    repo = state.get("repo_path")
    if repo:
        system += f"\n\nSelected repository path: {repo}"
    else:
        system += "\n\nRepository status: no repository is selected."

    if summary:
        system += f"\n\nConversation summary so far:\n{summary}"
    if repo:
        if context := LongTermMemory.for_repo(repo).context_block():
            system += f"\n\nProject context:\n{context}"

    reply = get_llm().invoke([SystemMessage(content=system), *recent])
    return {"messages": [AIMessage(content=reply.content)]}

@traced_router("after_codebase")
def route_after_codebase(state: AgentState) -> Literal["issue", "developer", "chat_reply"]:
    if state.get("query_type") == "new_feature":
        return "developer"                      # a feature may not touch any existing file
    summary = state.get("codebase_summary")
    return "issue" if summary and summary.relevant_files else "chat_reply"


@traced_router("after_developer")
def route_after_developer(state: AgentState) -> Literal["tester", "end"]:
    return "tester" if state.get("dev_status") == "done" else "end"