"""Long-term memory: persistent, per-project knowledge.

Holds instructions given at project creation, project facts, and the
repository's Markdown documentation. Survives across threads and restarts.
"""
import hashlib
from pathlib import Path

from src.memory.store import Store, get_store
from src.tools import filesystem

DOC_PATTERNS = ["README*", "ARCHITECTURE*", "CONTRIBUTING*", "docs/**/*.md", "*.md"]
MAX_DOC_CHARS = 20000

INSTRUCTION = "instruction"
INFO = "info"
DOC = "doc"


def project_id_for(repo_path: str) -> str:
    """Stable id derived from the repository's absolute path."""
    return hashlib.sha1(str(Path(repo_path).resolve()).encode()).hexdigest()[:12]


class LongTermMemory:
    def __init__(self, project_id: str, store: Store | None = None):
        self.project_id = project_id
        self.store = store or get_store()

    @classmethod
    def for_repo(cls, repo_path: str, store: Store | None = None) -> "LongTermMemory":
        return cls(project_id_for(repo_path), store)

    # ---- instructions given when the project was created ----
    def add_instruction(self, text: str) -> None:
        key = hashlib.sha1(text.encode()).hexdigest()[:10]  # same text is stored once
        self.store.put_memory(self.project_id, INSTRUCTION, key, text)

    def instructions(self) -> list[str]:
        return [m["content"] for m in self.store.list_memories(self.project_id, INSTRUCTION)]

    # ---- persistent project facts (language, test command, conventions) ----
    def set_info(self, key: str, value: str) -> None:
        self.store.put_memory(self.project_id, INFO, key, value)

    def get_info(self) -> dict[str, str]:
        return {m["key"]: m["content"] for m in self.store.list_memories(self.project_id, INFO)}

    # ---- Markdown documentation ----
    def sync_docs(self, repo_path: str) -> int:
        """Copy repo docs into memory. Returns how many were new or changed."""
        paths = set(filesystem.glob_find(repo_path, DOC_PATTERNS))
        changed = 0
        for rel in paths:
            content = filesystem.read_file(repo_path, rel, max_chars=MAX_DOC_CHARS)
            if self.store.put_memory(self.project_id, DOC, rel, content):
                changed += 1
        # Drop docs that no longer exist in the repo.
        for m in self.store.list_memories(self.project_id, DOC):
            if m["key"] not in paths:
                self.store.delete_memory(self.project_id, DOC, m["key"])
        return changed

    def docs(self) -> dict[str, str]:
        return {m["key"]: m["content"] for m in self.store.list_memories(self.project_id, DOC)}

    # ---- ready-to-use prompt text ----
    def context_block(self, max_chars: int = 6000) -> str:
        parts: list[str] = []
        if instr := self.instructions():
            parts.append("Project instructions:\n" + "\n".join(f"- {i}" for i in instr))
        if info := self.get_info():
            parts.append("Project facts:\n" + "\n".join(f"- {k}: {v}" for k, v in info.items()))
        for path, content in self.docs().items():
            parts.append(f"### {path}\n{content[:1500]}")
        return "\n\n".join(parts)[:max_chars]