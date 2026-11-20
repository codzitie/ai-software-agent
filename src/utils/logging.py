"""Logging setup. Console stays quiet; details go to a rotating log file."""
import logging
import sys
from logging.handlers import RotatingFileHandler

from config import settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    root = logging.getLogger("agent")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(settings.CONSOLE_LOG_LEVEL)
    console.setFormatter(fmt)
    root.addHandler(console)

    settings.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    file = RotatingFileHandler(settings.LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file.setLevel(settings.LOG_LEVEL)
    file.setFormatter(fmt)
    root.addHandler(file)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"agent.{name}")