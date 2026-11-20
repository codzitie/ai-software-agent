"""Tracing: logs LLM calls, tool calls, node outputs and routing decisions."""
import dataclasses
import functools
import json
import time
from pathlib import Path

from distro import name
from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel
import re
from config import settings
from src.utils.logging import get_logger

log = get_logger("trace")


def _default(o):
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return dataclasses.asdict(o)
    if isinstance(o, Path):
        return str(o)
    return repr(o)


def _fmt(obj, limit: int) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=_default, ensure_ascii=False)
    if limit and len(text) > limit:
        text = text[:limit] + f"… [{len(text) - limit} more chars]"
    return text
FILE_LINES_KEPT = 2
_FILE_BLOCK = re.compile(r"(### [^\n]+\n)(.*?)(?=\n\n### |\Z)", re.S)
_BULKY_KEYS = {"docs", "repo_tree"}


def _head(text: str, keep: int = FILE_LINES_KEPT) -> str:
    lines = text.split("\n")
    if len(lines) <= keep:
        return text
    return "\n".join(lines[:keep]) + f"\n… [{len(lines) - keep} more lines hidden]"


def _shorten_files(text: str) -> str:
    """Cut every '### path' file block in a prompt down to its first lines."""
    return _FILE_BLOCK.sub(lambda m: m.group(1) + _head(m.group(2)), text)


def _slim_update(update: dict) -> dict:
    out = {}
    for k, v in update.items():
        if k in _BULKY_KEYS:
            out[k] = f"<{len(v)} chars/items hidden>"
        else:
            out[k] = v
    return out

# ---------------- tools ----------------
def traced_tool(name: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            lim = settings.TRACE_ARGS_CHARS
            log.info("TOOL  %s  args=%s", name, _fmt({"args": args, "kwargs": kwargs}, lim))
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                log.error("TOOL  %s  FAILED %.2fs  %r", name, time.perf_counter() - start, exc)
                raise
            shown = _head(result) if name.endswith("read_file") and isinstance(result, str) else result
            log.info("TOOL  %s  ok %.2fs  result=%s", name, time.perf_counter() - start, _fmt(shown, lim))
            return result

        return wrapper

    return deco


_instrumented = False


def instrument_tools() -> None:
    """Wrap every tool the nodes call. Nodes use module.function, so no node code changes."""
    global _instrumented
    if _instrumented:
        return
    from src.tools import (code_modifier, dependency, filesystem, installer,
                           semantic_search, syntax_checker, test_runner, text_search)

    targets = {
        filesystem: ["tree", "glob_find", "read_file"],
        text_search: ["search"],
        semantic_search: ["search"],
        syntax_checker: ["check_files"],
        dependency: ["find_missing", "find_cycles"],
        installer: ["install"],
        code_modifier: ["apply_edits", "rollback"],
        test_runner: ["run"],
    }
    for module, names in targets.items():
        for n in names:
            setattr(module, n, traced_tool(f"{module.__name__.split('.')[-1]}.{n}")(getattr(module, n)))
    _instrumented = True


# ---------------- nodes and routing ----------------
def node_start(agent: str, stage: str) -> float:
    log.info("NODE  %s/%s  started", agent, stage)
    return time.perf_counter()


def node_end(agent: str, stage: str, started: float, update: dict) -> None:
    log.info("NODE  %s/%s  done %.2fs  output=%s", agent, stage, time.perf_counter() - started,
             _fmt(_slim_update(update), settings.TRACE_LLM_CHARS))


def route(name: str, destination: str, reason: str = "") -> None:
    log.info("ROUTE %s -> %s%s", name, destination, f"  ({reason})" if reason else "")


def traced_router(name: str):
    def deco(fn):
        @functools.wraps(fn)   # keeps the Literal return type that LangGraph reads
        def wrapper(state):
            dest = fn(state)
            route(name, dest)
            return dest

        return wrapper

    return deco


# ---------------- LLM ----------------
def _text(content) -> str:
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


class LLMTrace(BaseCallbackHandler):
    def __init__(self):
        self._start: dict = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._start[run_id] = time.perf_counter()
        for batch in messages:
            for m in batch:
                log.info("LLM   >> %s:\n%s", m.type,
         _fmt(_shorten_files(_text(m.content)), settings.TRACE_LLM_CHARS))

    def on_llm_end(self, response, *, run_id, **kwargs):
        took = time.perf_counter() - self._start.pop(run_id, time.perf_counter())
        for gens in response.generations:
            for g in gens:
                msg = getattr(g, "message", None)
                if msg is None:
                    log.info("LLM   << %s", _fmt(g.text, settings.TRACE_LLM_CHARS))
                    continue
                for tc in getattr(msg, "tool_calls", []) or []:   # structured output = a decision
                    log.info("LLM   << DECISION %s: %s", tc["name"], _fmt(tc["args"], settings.TRACE_LLM_CHARS))
                if text := _text(msg.content).strip():
                    log.info("LLM   << %s", _fmt(text, settings.TRACE_LLM_CHARS))
                usage = getattr(msg, "usage_metadata", None)
                log.info("LLM   << %.2fs  tokens=%s", took, usage)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._start.pop(run_id, None)
        log.error("LLM   FAILED %r", error)