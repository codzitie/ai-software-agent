"""Apply edits atomically with a backup, and roll them back.

Edits are validated in memory first. If any edit fails, nothing is written.
Backups live in data/backups/, outside the repository.
"""
import hashlib
import json
import shutil
import time
import uuid
from pathlib import Path

from config import settings
from src.state.schemas import Edit
from src.tools import filesystem
from src.tools.models import ApplyResult
from src.utils.errors import ToolError


def _backup_root(root) -> Path:
    pid = hashlib.sha1(str(Path(root).resolve()).encode()).hexdigest()[:12]
    return settings.BACKUP_DIR / pid


def apply_edits(root, edits: list[Edit]) -> ApplyResult:
    base = Path(root).resolve()
    errors: list[str] = []
    updated: dict[str, str] = {}   # rel path -> new content (LF endings)
    crlf: set[str] = set()

    for i, edit in enumerate(edits, 1):
        label = f"Edit {i} ({edit.file})"
        try:
            path = filesystem.resolve_safe(base, edit.file)
        except ToolError as exc:
            errors.append(f"{label}: {exc}")
            continue
        if not path.is_file():
            errors.append(f"{label}: file not found")
            continue

        key = path.relative_to(base).as_posix()
        if key not in updated:
            try:
                raw = path.read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                errors.append(f"{label}: file is not valid UTF-8")
                continue
            if "\r\n" in raw:
                crlf.add(key)
            updated[key] = raw.replace("\r\n", "\n")

        content = updated[key]
        target = edit.target_text.replace("\r\n", "\n")
        if not target:
            errors.append(f"{label}: target_text is empty")
            continue
        if "[truncated]" in target:
            errors.append(f"{label}: target_text contains a '[truncated]' marker. "
                          "That text is not in the file. Copy only real file content.")
            continue
        if edit.action in ("replace", "insert_after") and edit.new_text is None:
            errors.append(f"{label}: new_text is required for '{edit.action}'")
            continue

        count = content.count(target)
        if count == 0:
            errors.append(
                f"{label}: target_text not found. Copy it exactly from the file, including indentation."
            )
            continue
        if count > 1:
            errors.append(
                f"{label}: target_text appears {count} times. Include more surrounding lines to make it unique."
            )
            continue

        idx = content.find(target)
        end = idx + len(target)
        starts_ok = idx == 0 or content[idx - 1] == "\n"
        ends_ok = end == len(content) or target.endswith("\n") or content[end] == "\n"
        if not (starts_ok and ends_ok):
            errors.append(f"{label}: target_text must be whole lines. "
                          "It starts or ends in the middle of a line; include the full line(s).")
            continue

        new = (edit.new_text or "").replace("\r\n", "\n")
        if edit.action == "replace":
            replacement = new
        elif edit.action == "insert_after":
            sep = "" if target.endswith("\n") or new.startswith("\n") else "\n"
            replacement = target + sep + new
        else:   # remove
            replacement = ""
        updated[key] = content.replace(target, replacement, 1)

    if errors or not updated:
        return ApplyResult(None, errors or ["The patch contained no edits."])

    # ---- backup, then write ----
    backup_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    bdir = _backup_root(base) / backup_id
    for key in updated:
        dst = bdir / "files" / key
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / key, dst)
    (bdir / "manifest.json").write_text(json.dumps({"files": sorted(updated)}), encoding="utf-8")

    try:
        for key, text in updated.items():
            if key in crlf:
                text = text.replace("\n", "\r\n")
            (base / key).write_bytes(text.encode("utf-8"))   # bytes: no newline translation
    except OSError as exc:
        rollback(base, backup_id)
        return ApplyResult(None, [f"Write failed, changes undone: {exc}"])

    return ApplyResult(backup_id, [])


def rollback(root, backup_id: str) -> None:
    base = Path(root).resolve()
    bdir = _backup_root(base) / backup_id
    manifest = bdir / "manifest.json"
    if not manifest.is_file():
        raise ToolError(f"Backup '{backup_id}' not found.")
    for key in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        shutil.copy2(bdir / "files" / key, base / key)