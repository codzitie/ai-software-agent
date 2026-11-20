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
    }


def chat_reply_node(state: AgentState, config: RunnableConfig) -> dict:
    """General chat, or a polite request for what a bug fix is missing."""
    if state.get("query_type") == "bug_fix":
        if not state.get("repo_path"):
            text = (
                "I can look into that, but I need the repository first. "
                "Set it with `/repo <path>` and send your request again."
            )
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


def unsupported_node(state: AgentState) -> dict:
    plan = state.get("plan")
    planned = f"\nPlan I would follow: {plan.summary}" if plan else ""
    text = (
        "This looks like a request to build a new project. "
        "That needs the Developer Agent, which is not built yet, so for now I can only "
        f"fix bugs in existing repositories.{planned}"
    )
    return {"messages": [AIMessage(content=text)]}


@traced_router("after_codebase")
def route_after_codebase(state: AgentState) -> Literal["issue", "chat_reply"]:
    summary = state.get("codebase_summary")
    return "issue" if summary and summary.relevant_files else "chat_reply"