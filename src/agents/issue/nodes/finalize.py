"""Deterministic: set the final status and write the reply to the user."""
from langchain_core.messages import AIMessage

from src.state.graph_state import AgentState
from src.tools import code_modifier


def finalize_node(state: AgentState) -> dict:
    status = state.get("issue_status") or ("failed" if state.get("step_error") else "fixed")

    if status == "fixed":
        files = sorted({e.file for e in state["patch"].edits})
        text = (
            f"Issue fixed after {state['attempt']} attempt(s).\n"
            f"Cause: {state['root_cause'].explanation}\n"
            f"Change: {state['patch'].explanation}\n"
            f"Files changed: {', '.join(files)}"
        )
        t_status, t_report = state.get("tester_status"), state.get("tester_report")
        if t_status == "passed":
            text += f"\nTests added and passing:\n{t_report}"
        elif t_status in ("blocked", "failed"):
            text += ("\nNote: I could not add new tests for this fix, so only the original "
                     f"reproduction was checked.\n{(t_report or '')[:600]}")
    elif status == "not_reproducible":
        text = (
            "I could not reproduce this issue.\n"
            f"{state['issue_report'].evidence}\n"
            "Can you share steps, an error message, or a failing input?"
        )
    else:
        if state.get("backup_id"):  # leave the repo clean when giving up
            code_modifier.rollback(state["repo_path"], state["backup_id"])
        last = state.get("step_error") or "unknown error"
        text = (
            f"I could not fix this after {state.get('attempt', 0)} attempt(s). "
            f"Changes were rolled back.\nLast failure:\n{last}"
        )

    return {"issue_status": status, "messages": [AIMessage(content=text)]}