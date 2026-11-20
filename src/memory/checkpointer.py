"""LangGraph checkpointer: saves graph state after every node.

This is what makes the thread resumable after a crash, a restart,
or (later) a user pause.
"""
import sqlite3

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from config import settings


def get_checkpointer():
    if settings.CHECKPOINT_BACKEND == "memory":
        return MemorySaver()  # tests only; lost on exit

    settings.CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.CHECKPOINT_DB_PATH, check_same_thread=False)
    return SqliteSaver(conn)


def thread_config(thread_id: str) -> dict:
    """Config to pass on every graph.invoke / graph.stream call."""
    return {"configurable": {"thread_id": thread_id}}