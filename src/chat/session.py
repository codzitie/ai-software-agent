"""One chat session = one thread_id. Runs the graph for each message."""
import uuid
from pathlib import Path
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage

from config import settings
from src.graph.main_graph import build_main_graph
from src.memory.checkpointer import thread_config
from src.utils.errors import AgentError, InvalidRepoError
from src.utils.logging import get_logger

log = get_logger("chat")


class ChatSession:
    def __init__(self, thread_id: str | None = None, graph=None):
        self.thread_id = thread_id or uuid.uuid4().hex[:8]
        self.graph = graph or build_main_graph()
        self.config = {**thread_config(self.thread_id), "recursion_limit": settings.RECURSION_LIMIT}

        # Resuming an existing thread: pick the repo back up from the checkpoint.
        values = self.graph.get_state(self.config).values or {}
        self.repo_path: str | None = values.get("repo_path")

    # ---- repository ----
    def set_repo(self, path: str) -> str:
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise InvalidRepoError(f"'{path}' is not a directory.")
        self.repo_path = str(p)
        return self.repo_path

    # ---- talking to the agent ----
    def send(self, text: str, on_step: Callable[[str], None] | None = None) -> str:
        log.info("USER  %s", text)
        inputs: dict = {"messages": [HumanMessage(content=text)], "user_query": text}
        if self.repo_path:
            inputs["repo_path"] = self.repo_path
        return self._run(inputs, on_step)

    def resume(self, on_step: Callable[[str], None] | None = None) -> str:
        """Continue an interrupted run from its last saved step."""
        if not self.graph.get_state(self.config).next:
            return "Nothing to resume."
        return self._run(None, on_step)

    # ---- internals ----
    def _run(self, inputs, on_step) -> str:
        try:
            for _ns, update in self.graph.stream(
                inputs, self.config, stream_mode="updates", subgraphs=True
            ):
                if on_step and isinstance(update, dict):
                    for node in update:
                        on_step(node)
        except KeyboardInterrupt:
            return "Stopped. Progress is saved; type /resume to continue."
        except AgentError as exc:
            return f"Error: {exc}"
        except Exception:
            log.exception("Run failed")
            return "Something went wrong. Details are in data/agent.log."
        return self._last_reply()

    def _last_reply(self) -> str:
        values = self.graph.get_state(self.config).values or {}
        for msg in reversed(values.get("messages", [])):
            if isinstance(msg, AIMessage):
                return msg.content
        return "(no reply)"