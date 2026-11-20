"""Wrapper that records each node's output and errors to short-term memory.

Nodes stay unchanged. The wrapper reads the thread_id from LangGraph's config.
Keep src/graph/__init__.py empty so agents can import this without a cycle.
"""
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from src.memory.short_term import ShortTermMemory
from src.state.graph_state import AgentState
from src.utils.logging import get_logger
import inspect
from src.utils.trace import node_end, node_start

log = get_logger("memory")

SKIP_KEYS = {"messages", "docs", "repo_tree"}  # large or already stored elsewhere
MAX_STR = 2000


def _compact(update: dict) -> dict:
    out = {}
    for key, value in update.items():
        if key in SKIP_KEYS:
            continue
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        elif isinstance(value, list):
            value = [v.model_dump(mode="json") if isinstance(v, BaseModel) else v for v in value]
        if isinstance(value, str) and len(value) > MAX_STR:
            value = value[:MAX_STR] + "…"
        out[key] = value
    return out


def remember(agent: str, stage: str):
    def decorator(fn):
        # Does the wrapped node want LangGraph's config too? (e.g. chat_reply_node)
        accepts_config = "config" in inspect.signature(fn).parameters

        # No functools.wraps: it would hide the `config` parameter from LangGraph.
        def wrapped(state: AgentState, config: RunnableConfig) -> dict:
            thread_id = (config or {}).get("configurable", {}).get("thread_id")
            started = node_start(agent, stage)
            try:
                update = (fn(state, config) if accepts_config else fn(state)) or {}
            except Exception as exc:
                _safe(thread_id, lambda m: m.record_error(agent, stage, repr(exc)))
                raise
            node_end(agent, stage, started, update)

            def write(m: ShortTermMemory):
                m.record(agent, stage, _compact(update))
                if update.get("step_error"):
                    m.record_error(agent, stage, update["step_error"])

            _safe(thread_id, write)
            return update

        wrapped.__name__ = fn.__name__
        return wrapped

    return decorator


def _safe(thread_id, action) -> None:
    """A memory failure must never crash the run."""
    if not thread_id:
        return
    try:
        action(ShortTermMemory(thread_id))
    except Exception:
        log.exception("Could not write to short-term memory")