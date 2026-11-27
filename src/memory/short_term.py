"""Short-term memory: what the current run/thread needs.

Holds issue details, errors, stage outputs and the conversation summary.
Scoped by thread_id, so each chat session has its own.
"""
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from config import settings
from config.settings import load_prompt
from src.llm.provider import get_llm
from src.memory.store import Store, get_store
from src.utils.text import content_to_text


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    return obj


def _format_messages(messages: list[BaseMessage]) -> str:
    return "\n".join(f"{m.type}: {content_to_text(m.content)}" for m in messages)


class ShortTermMemory:
    def __init__(self, thread_id: str, store: Store | None = None):
        self.thread_id = thread_id
        self.store = store or get_store()

    # ---- stage outputs and issue details ----
    def record(self, agent: str, stage: str, payload: Any, kind: str = "output") -> None:
        self.store.append_record(self.thread_id, agent, stage, kind, _jsonable(payload))

    def save_issue(self, query: str, repo_path: str | None) -> None:
        self.record("user", "issue", {"query": query, "repo_path": repo_path}, kind="issue")

    def latest_issue(self) -> dict | None:
        rows = self.store.list_records(self.thread_id, kind="issue", limit=1)
        return rows[-1]["payload"] if rows else None

    def outputs(self, agent: str | None = None, limit: int = 20) -> list[dict]:
        return self.store.list_records(self.thread_id, agent=agent, kind="output", limit=limit)

    def latest(self, agent: str, stage: str) -> Any | None:
        for row in reversed(self.outputs(agent=agent, limit=50)):
            if row["stage"] == stage:
                return row["payload"]
        return None

    # ---- errors ----
    def record_error(self, agent: str, stage: str, error: str) -> None:
        self.record(agent, stage, {"error": error}, kind="error")

    def errors(self, limit: int = 5) -> list[str]:
        rows = self.store.list_records(self.thread_id, kind="error", limit=limit)
        return [f"[{r['agent']}/{r['stage']}] {r['payload']['error']}" for r in rows]

    # ---- conversation summary ----
    def get_summary(self) -> str | None:
        return self.store.get_summary(self.thread_id)

    def compact_history(self, messages: list[BaseMessage]) -> tuple[str | None, list[BaseMessage]]:
        """Return (summary, recent_messages).

        Once the history exceeds SUMMARY_TRIGGER_MESSAGES, older messages are folded
        into the stored summary and only the latest SUMMARY_KEEP_LAST stay verbatim.
        """
        if len(messages) <= settings.SUMMARY_TRIGGER_MESSAGES:
            return self.get_summary(), messages

        old = messages[: -settings.SUMMARY_KEEP_LAST]
        recent = messages[-settings.SUMMARY_KEEP_LAST :]
        previous = self.get_summary() or "No earlier summary."

        reply = get_llm().invoke(
            [
                SystemMessage(content=load_prompt("conversation_summary")),
                HumanMessage(
                    content=f"Existing summary:\n{previous}\n\nNew messages:\n{_format_messages(old)}"
                ),
            ]
        )
        summary = content_to_text(reply.content).strip()
        self.store.put_summary(self.thread_id, summary)
        return summary, recent