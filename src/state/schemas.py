"""Pydantic models passed between agents.

Rule: anything an LLM must return in a fixed shape (with_structured_output)
or anything stored in graph state lives here.
"""
from typing import Literal

from pydantic import BaseModel, Field


# ---------- planner ----------
class Task(BaseModel):
    id: int
    agent: Literal["codebase", "issue", "tester", "developer", "documentation"]
    description: str


class Plan(BaseModel):
    query_type: Literal["bug_fix", "new_project", "chat"]
    summary: str
    tasks: list[Task] = Field(default_factory=list)


# ---------- codebase agent ----------
class FileNote(BaseModel):
    path: str
    why_relevant: str
    key_symbols: list[str] = Field(default_factory=list)


class CodebaseSummary(BaseModel):
    architecture_notes: str
    suspected_area: str
    relevant_files: list[FileNote] = Field(default_factory=list)


# ---------- issue agent ----------
class IssueReport(BaseModel):
    reproducible: bool
    evidence: str
    repro_command: str | None = None   # e.g. "pytest tests/test_x.py::test_y -x"


class RootCause(BaseModel):
    file: str
    explanation: str
    affected_symbols: list[str] = Field(default_factory=list)


class Edit(BaseModel):
    file: str
    action: Literal["replace", "insert_after", "remove"]
    target_text: str = Field(description="Exact text already in the file; must appear exactly once")
    new_text: str | None = Field(default=None, description="Used by replace and insert_after")


class Patch(BaseModel):
    explanation: str
    edits: list[Edit]


class TestResult(BaseModel):
    __test__ = False   # stops pytest from trying to collect this as a test class

    passed: bool
    output: str
    command: str | None = None
    exit_code: int | None = None