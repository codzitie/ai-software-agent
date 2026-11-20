"""Exact text / regex search. Uses ripgrep when installed, pure Python otherwise."""
import re
import shutil
import subprocess
from pathlib import Path

from config import settings
from src.tools import filesystem
from src.tools.models import Hit

MAX_LINE_CHARS = 300
MAX_PER_FILE = 5


def search(root, pattern: str, max_hits: int = 50, regex: bool = False, ignore_case: bool = True) -> list[Hit]:
    if not pattern.strip():
        return []
    if shutil.which("rg"):
        hits = _ripgrep(root, pattern, max_hits, regex, ignore_case)
        if hits is not None:
            return hits
    return _python_search(root, pattern, max_hits, regex, ignore_case)


def _ripgrep(root, pattern, max_hits, regex, ignore_case) -> list[Hit] | None:
    cmd = ["rg", "--line-number", "--no-heading", "--color", "never",
           "--max-columns", str(MAX_LINE_CHARS), "--max-count", str(MAX_PER_FILE)]
    for d in settings.IGNORE_DIRS:
        cmd += ["--glob", f"!{d}"]
    if not regex:
        cmd.append("--fixed-strings")
    if ignore_case:
        cmd.append("--ignore-case")
    cmd += ["-e", pattern, "."]

    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode not in (0, 1):      # 2 = error, e.g. invalid regex -> use the fallback
        return None

    hits: list[Hit] = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        num, _, text = rest.partition(":")
        if not num.isdigit():
            continue
        path = path.removeprefix("./").replace("\\", "/")
        hits.append(Hit(path, int(num), text.strip()[:MAX_LINE_CHARS]))
        if len(hits) >= max_hits:
            break
    return hits


def _python_search(root, pattern, max_hits, regex, ignore_case) -> list[Hit]:
    try:
        rx = re.compile(pattern if regex else re.escape(pattern), re.IGNORECASE if ignore_case else 0)
    except re.error:
        return []

    base = Path(root).resolve()
    hits: list[Hit] = []
    for rel in filesystem.iter_files(base):
        path = base / rel
        try:
            if path.stat().st_size > settings.MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        in_file = 0
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append(Hit(rel, n, line.strip()[:MAX_LINE_CHARS]))
                in_file += 1
                if len(hits) >= max_hits:
                    return hits
                if in_file >= MAX_PER_FILE:
                    break
    return hits