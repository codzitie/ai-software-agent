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
    query_type: Literal["bug_fix", "new_project", "new_feature", "chat"]
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

class PlannedFile(BaseModel):
    path: str
    action: Literal["create", "edit"]
    purpose: str
    depends_on: list[str] = Field(default_factory=list)


class DevTask(BaseModel):
    summary: str
    project_name: str | None = None
    layout: Literal["flat", "src"] = "flat"
    files: list[PlannedFile]
    dependencies: list[str] = Field(default_factory=list)
    test_command: str = "pytest -q"


class GeneratedFile(BaseModel):
    path: str
    content: str
    imports_local: list[str] = Field(default_factory=list)
    imports_third_party: list[str] = Field(default_factory=list)

class TestCase(BaseModel):
    __test__ = False
    id: str
    target: str                       # path/to/file.py::symbol
    kind: Literal["happy_path", "edge_case", "error_case", "regression"]
    description: str
    inputs: str
    expected: str
    test_file: str


class TestPlan(BaseModel):
    __test__ = False
    summary: str
    cases: list[TestCase]
    needs_fixtures: list[str] = Field(default_factory=list)


class TestDiagnosis(BaseModel):
    __test__ = False
    verdict: Literal["test_bug", "implementation_bug"]
    confidence: Literal["high", "medium", "low"]
    reason: str
    fix_hint: str = ""


# ---------- developer agent ----------
class PlannedFile(BaseModel):
    path: str
    action: Literal["create", "edit"]
    purpose: str
    depends_on: list[str] = Field(default_factory=list)


class DevTask(BaseModel):
    summary: str
    project_name: str | None = None
    layout: Literal["flat", "src"] = "flat"
    files: list[PlannedFile]
    dependencies: list[str] = Field(default_factory=list)
    test_command: str = "pytest -q"


class GeneratedFile(BaseModel):
    path: str
    content: str
    imports_local: list[str] = Field(default_factory=list)
    imports_third_party: list[str] = Field(default_factory=list)


# ---------- tester agent ----------
class TestCase(BaseModel):
    __test__ = False
    id: str
    target: str
    kind: Literal["happy_path", "edge_case", "error_case", "regression"]
    description: str
    inputs: str
    expected: str
    test_file: str


class TestPlan(BaseModel):
    __test__ = False
    summary: str
    cases: list[TestCase]
    needs_fixtures: list[str] = Field(default_factory=list)


class TestDiagnosis(BaseModel):
    __test__ = False
    verdict: Literal["test_bug", "implementation_bug"]
    confidence: Literal["high", "medium", "low"]
    reason: str
    fix_hint: str = ""