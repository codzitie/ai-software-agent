"""Install packages into the repo's own environment, never globally."""
import re
import subprocess

from config import settings
from src.tools import runtime
from src.tools.models import InstallResult

# name, optional extras, optional version specifiers. Blocks URLs, paths and pip flags.
_PACKAGE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,_-]+\])?([=<>!~]=?[A-Za-z0-9.*+!_-]+)*$"
)


def install(root, packages: list[str]) -> InstallResult:
    bad = [p for p in packages if not _PACKAGE.match(p)]
    if bad:
        return InstallResult(False, f"Refused to install invalid package names: {bad}")
    if not packages:
        return InstallResult(True, "Nothing to install.")

    try:
        python = runtime.python_for(root)
        proc = runtime.pip_install(python, packages, settings.PIP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return InstallResult(False, f"pip timed out after {settings.PIP_TIMEOUT}s")
    except OSError as exc:
        return InstallResult(False, str(exc))

    return InstallResult(proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:])

def install_requirements(root, filename: str = "requirements.txt") -> InstallResult:
    """Install from a requirements file inside the repo. Call only after the user approved it."""
    from src.tools import filesystem
    from src.utils.errors import ToolError

    try:
        path = filesystem.resolve_safe(root, filename)
    except ToolError as exc:
        return InstallResult(False, str(exc))
    if not path.is_file() or path.suffix not in (".txt", ".in"):
        return InstallResult(False, f"Not a requirements file: {filename}")
    try:
        proc = runtime.pip_install(runtime.python_for(root), ["-r", str(path)], settings.PIP_TIMEOUT)
    except subprocess.TimeoutExpired:
        return InstallResult(False, f"pip timed out after {settings.PIP_TIMEOUT}s")
    except OSError as exc:
        return InstallResult(False, str(exc))
    return InstallResult(proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:])