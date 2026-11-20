"""Per-repository Python environment.

If the repo has its own .venv/venv, use it. Otherwise create a dedicated venv under
data/envs/. Installs and test runs always go through this python, never the agent's own.
"""
import hashlib
import os
import subprocess
import venv
from pathlib import Path

from config import settings
from src.utils.logging import get_logger

log = get_logger("runtime")

_BIN = "Scripts" if os.name == "nt" else "bin"
_EXE = "python.exe" if os.name == "nt" else "python"


def _py(env: Path) -> Path:
    return env / _BIN / _EXE


def env_dir(root) -> Path:
    pid = hashlib.sha1(str(Path(root).resolve()).encode()).hexdigest()[:12]
    return settings.ENV_DIR / pid


def pip_install(python: Path, args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def python_for(root) -> Path:
    base = Path(root).resolve()
    for name in (".venv", "venv"):
        candidate = _py(base / name)
        if candidate.exists():
            return candidate

    env = env_dir(base)
    python = _py(env)
    if not python.exists():
        log.info("Creating environment for %s", base)
        venv.create(env, with_pip=True)

    marker = env / ".bootstrapped"
    if not marker.exists():
        _bootstrap(base, python)
        marker.write_text("ok")   # written even on failure, so we never retry in a loop
    return python


def _bootstrap(base: Path, python: Path) -> None:
    try:
        pip_install(python, ["pytest"], settings.PIP_TIMEOUT)
        req = base / "requirements.txt"
        if req.is_file():
            result = pip_install(python, ["-r", str(req)], settings.PIP_TIMEOUT)
            if result.returncode:
                log.warning("requirements.txt install failed:\n%s", result.stderr[-1500:])
    except subprocess.TimeoutExpired:
        log.warning("Environment bootstrap timed out")
        