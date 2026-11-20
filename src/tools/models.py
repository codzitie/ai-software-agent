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