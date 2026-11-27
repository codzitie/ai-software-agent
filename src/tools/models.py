"""Small return types shared by the tools."""
from dataclasses import dataclass, field


@dataclass
class Hit:
    path: str
    line: int
    text: str


@dataclass
class SyntaxIssue:
    path: str
    line: int
    message: str


@dataclass
class ApplyResult:
    backup_id: str | None
    errors: list[str] = field(default_factory=list)


@dataclass
class InstallResult:
    ok: bool
    output: str

@dataclass
class ProjectInfo:
    is_empty: bool
    python_files: int
    layout: str                                   # "src", "flat" or "none"
    packages: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    dependency_files: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    test_framework: str | None = None             # "pytest", "unittest" or None
    test_dirs: list[str] = field(default_factory=list)
    test_file_count: int = 0
    python_version: str | None = None
    line_length: int | None = None
    has_own_venv: bool = False
    is_git_repo: bool = False
    has_readme: bool = False