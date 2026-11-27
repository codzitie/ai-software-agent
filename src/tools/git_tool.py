"""Git safety net for multi-file changes.

Flow for one task:
    task = start_task(root, "add login")      # refuses if tracked files have uncommitted changes
    ... agent writes files ...
    commit(root, "Add login form", paths)     # after each good step; only the named files
    ... a step fails ...
    reset_to(root, sha)                       # back to the last good commit
    finish_task(root, task)                   # back on the user's branch; agent branch kept for review
    abandon_task(root, task)                  # or: throw the whole attempt away

Rules that keep the user's work safe:
  * every change happens on a branch named agent/<task>-<id>, never on the user's branch
  * start_task refuses when tracked files have uncommitted changes (untracked files are fine)
  * commit() takes explicit file paths, never "add everything", so the user's untracked
    files are never swept in; folders, .git and .env* are refused
  * reset_to() and abandon_task() only run while on an agent/ branch
  * the project folder must be the git top level, not a subfolder of a bigger repo
  * nothing is pushed, merged, or rebased. Merging is the user's decision.
  * no shell; paths are literal (no glob expansion); diff drivers and prompts are off
Repo hooks are skipped for agent commits (--no-verify) and GPG signing is switched off.
If git has no user.name/email configured, the agent commits as "AI Software Agent"
(set per command, nothing written to any git config).
"""
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from src.tools import filesystem
from src.utils.errors import ToolError
from src.utils.logging import get_logger

log = get_logger("git")

TIMEOUT = 60
BRANCH_PREFIX = "agent/"
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_REF = re.compile(r"^[A-Za-z0-9._/~^-]+$")        # HEAD, sha, branch name; never starts with '-'
_IDENTITY = ["-c", "user.name=AI Software Agent", "-c", "user.email=agent@localhost"]


@dataclass
class GitStatus:
    is_repo: bool
    branch: str | None = None                      # None: detached HEAD or not a repo
    has_commits: bool = False
    tracked_changes: list[str] = field(default_factory=list)   # modified, staged, deleted, conflicted
    untracked: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """Clean = no changes to tracked files. Untracked files do not count."""
        return not self.tracked_changes


@dataclass
class TaskBranch:
    branch: str                                    # agent/<slug>-<id>
    base_branch: str | None                        # branch the user was on (None if detached)
    base_sha: str                                  # commit the task started from


@dataclass
class ChangedFile:
    path: str
    status: str                                    # A added/new, M modified, D deleted


# ---------------------------------------------------------------- plumbing
def is_available() -> bool:
    return shutil.which("git") is not None


def _git(base: Path, args: list[str], check: bool = True, timeout: int = TIMEOUT):
    if not is_available():
        raise ToolError("git is not installed or not on PATH")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LITERAL_PATHSPECS": "1", "LC_ALL": "C"}
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=off", *args], cwd=base, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"git {args[0]} timed out after {timeout}s")
    if check and proc.returncode != 0:
        raise ToolError(f"git {args[0]} failed: {(proc.stderr or proc.stdout).strip()[:500]}")
    return proc


def _commit_opts(base: Path) -> list[str]:
    """Options for an agent commit: no hooks, no signing, identity only if git has none."""
    name = _git(base, ["config", "user.name"], check=False).stdout.strip()
    email = _git(base, ["config", "user.email"], check=False).stdout.strip()
    ident = [] if (name and email) else _IDENTITY
    return [*ident, "-c", "commit.gpgsign=false"]


def _toplevel(base: Path) -> Path | None:
    proc = _git(base, ["rev-parse", "--show-toplevel"], check=False)
    return Path(proc.stdout.strip()).resolve() if proc.returncode == 0 and proc.stdout.strip() else None


def _ref(value: str) -> str:
    if not _REF.match(value) or value.startswith("-"):
        raise ToolError(f"Invalid git reference: {value!r}")
    return value


def _paths(base: Path, paths: list[str]) -> list[str]:
    """Repo-relative file paths. Refuses folders, '.', .git and .env* files."""
    out = []
    for p in paths:
        path = filesystem.resolve_safe(base, p)
        rel = path.relative_to(base)
        if rel == Path(".") or path.is_dir():
            raise ToolError(f"Give file paths, not folders: {p}")
        if ".git" in rel.parts or rel.name.startswith(".env"):
            raise ToolError(f"Refusing protected path: {rel.as_posix()}")
        out.append(rel.as_posix())
    return sorted(set(out))


# ---------------------------------------------------------------- repo state
def status(root) -> GitStatus:
    base = Path(root).resolve()
    top = _toplevel(base)
    if top is None or top != base:
        return GitStatus(is_repo=False)

    branch = _git(base, ["symbolic-ref", "--short", "-q", "HEAD"], check=False).stdout.strip() or None
    has_commits = _git(base, ["rev-parse", "--verify", "-q", "HEAD"], check=False).returncode == 0

    out = _git(base, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]).stdout
    tracked, untracked = [], []
    tokens = iter(out.split("\0"))
    for token in tokens:
        if len(token) < 4:
            continue
        xy, path = token[:2], token[3:]
        if xy[0] in "RC":
            next(tokens, None)                        # rename/copy entries carry the old path next
        if xy == "??":
            untracked.append(path)
        elif xy != "!!":
            tracked.append(path)
    return GitStatus(True, branch, has_commits, sorted(tracked), sorted(untracked))


def current_sha(root) -> str:
    return _git(Path(root).resolve(), ["rev-parse", "HEAD"]).stdout.strip()


def init(root) -> bool:
    """git init in a folder that is not yet a repo. Returns False if it already is one."""
    base = Path(root).resolve()
    top = _toplevel(base)
    if top == base:
        return False
    if top is not None:
        raise ToolError(f"{base} is inside another git repository ({top}); refusing to create a nested one")
    if _git(base, ["init", "-q", "-b", "main"], check=False).returncode != 0:   # git < 2.28
        _git(base, ["init", "-q"])
    return True


def _require_clean_repo(base: Path) -> GitStatus:
    st = status(base)
    if not st.is_repo:
        top = _toplevel(base)
        where = f" (it is inside the repository at {top})" if top else ""
        raise ToolError(f"{base} is not the top level of a git repository{where}")
    if not st.clean:
        shown = ", ".join(st.tracked_changes[:5]) + (" ..." if len(st.tracked_changes) > 5 else "")
        raise ToolError(f"The repository has uncommitted changes to tracked files ({shown}). "
                        "Commit or stash them first.")
    return st


def _on_agent_branch(base: Path) -> str:
    branch = status(base).branch
    if not branch or not branch.startswith(BRANCH_PREFIX):
        raise ToolError(f"Refusing: current branch is {branch!r}, not an {BRANCH_PREFIX}* branch")
    return branch


# ---------------------------------------------------------------- task flow
def start_task(root, name: str) -> TaskBranch:
    """Create and switch to agent/<slug>-<id>. Raises if tracked files have uncommitted changes."""
    base = Path(root).resolve()
    st = _require_clean_repo(base)

    if not st.has_commits:                            # fresh repo: HEAD must exist to branch from
        _git(base, [*_commit_opts(base), "commit", "-q", "--allow-empty", "--no-verify",
                    "-m", "Initial commit (AI Software Agent)"])

    base_sha = current_sha(base)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "task"
    branch = f"{BRANCH_PREFIX}{slug}-{uuid.uuid4().hex[:6]}"
    _git(base, ["checkout", "-q", "-b", branch])
    log.info("task branch %s from %s", branch, base_sha[:8])
    return TaskBranch(branch, st.branch, base_sha)


def commit(root, message: str, paths: list[str]) -> str | None:
    """Commit exactly these files on the agent branch. Returns the new sha, or None if nothing changed."""
    base = Path(root).resolve()
    _on_agent_branch(base)
    if not message.strip():
        raise ToolError("Commit message is empty")

    rels = _paths(base, paths)
    tracked = set(_git(base, ["ls-files", "-z", "--", *rels]).stdout.split("\0")) if rels else set()
    usable = [r for r in rels if (base / r).exists() or r in tracked]   # a deleted tracked file is fine
    if not usable:
        return None

    _git(base, ["add", "-A", "--", *usable])
    if _git(base, ["diff", "--cached", "--quiet", "--", *usable], check=False).returncode == 0:
        return None                                   # nothing differs from HEAD
    _git(base, [*_commit_opts(base), "commit", "-q", "--no-verify", "-m", message.strip()[:200],
                "--", *usable])
    sha = current_sha(base)
    log.info("committed %s: %s", sha[:8], usable)
    return sha


def reset_to(root, sha: str | None = None) -> None:
    """Hard-reset the agent branch to a commit (default: HEAD, i.e. drop uncommitted edits).

    Files the agent committed after `sha` disappear. Untracked files are left alone:
    remove ones the agent created with file_writer.remove_created.
    """
    base = Path(root).resolve()
    _on_agent_branch(base)
    target = "HEAD" if sha is None else sha
    if target != "HEAD" and not _SHA.match(target):
        raise ToolError(f"Invalid commit id: {sha!r}")
    _git(base, ["reset", "-q", "--hard", target])


def finish_task(root, task: TaskBranch) -> str:
    """Go back to the user's branch. The agent branch and its commits stay for review/merge."""
    base = Path(root).resolve()
    _require_clean_repo(base)
    if task.base_branch:
        _git(base, ["checkout", "-q", task.base_branch])
    else:
        _git(base, ["checkout", "-q", "--detach", task.base_sha])
    return task.branch


def abandon_task(root, task: TaskBranch) -> None:
    """Throw the attempt away: back to the starting commit, back on the user's branch, branch deleted."""
    base = Path(root).resolve()
    if _on_agent_branch(base) != task.branch:
        raise ToolError(f"Not on {task.branch}; refusing to abandon")
    _git(base, ["reset", "-q", "--hard", task.base_sha])
    if task.base_branch:
        _git(base, ["checkout", "-q", task.base_branch])
    else:
        _git(base, ["checkout", "-q", "--detach", task.base_sha])
    _git(base, ["branch", "-D", task.branch])


# ---------------------------------------------------------------- reading changes
def diff(root, since: str = "HEAD", paths: list[str] | None = None, max_chars: int = 20000) -> str:
    """Unified diff of tracked files, working tree vs `since`. New untracked files are not in it
    (use changed_files, then read them). External diff drivers and textconv are disabled."""
    base = Path(root).resolve()
    args = ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U3", _ref(since)]
    if paths:
        args += ["--", *_paths(base, paths)]
    text = _git(base, args).stdout
    if len(text) > max_chars:
        cut = text.rfind("\n", 0, max_chars)
        text = text[: cut if cut > 0 else max_chars] + "\n[diff cut: too long]"
    return text


def changed_files(root, since: str = "HEAD") -> list[ChangedFile]:
    """Files changed vs `since`: tracked changes plus untracked new files (status A)."""
    base = Path(root).resolve()
    out = _git(base, ["diff", "--name-status", "-z", "--no-renames", _ref(since)]).stdout
    tokens = [t for t in out.split("\0") if t]
    found = {path: ChangedFile(path, code[0]) for code, path in zip(tokens[0::2], tokens[1::2])}
    for path in status(base).untracked:
        found.setdefault(path, ChangedFile(path, "A"))
    return sorted(found.values(), key=lambda c: c.path)