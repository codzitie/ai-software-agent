"""Entry point for the AI Software Agent.

Usage:
    python main.py
    python main.py --repo ./workspace/my_project
    python main.py --thread a1b2c3d4          # resume an earlier chat
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Must run before importing modules that read environment variables.
load_dotenv()

from config import settings                      # noqa: E402
from src.chat.cli import run_cli                 # noqa: E402
from src.utils.errors import AgentError          # noqa: E402

# Change this to match the provider you use in src/llm/provider.py.
REQUIRED_ENV = ["ANTHROPIC_API_KEY"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Software Agent")
    parser.add_argument("--repo", help="path to the repository to work on")
    parser.add_argument("--thread", help="resume an existing thread id")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="override the log-file level from settings",
    )
    return parser.parse_args()


def check_environment() -> None:
    key = settings.PROVIDER_KEYS.get(settings.LLM_PROVIDER.lower())
    if key is None:
        sys.exit(f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}'.")
    if not os.getenv(key):
        sys.exit(f"Missing environment variable: {key}\nCopy .env.example to .env and fill it in.")


def prepare_folders() -> None:
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path("workspace").mkdir(exist_ok=True)


def main() -> None:
    args = parse_args()
    if args.log_level:
        settings.LOG_LEVEL = args.log_level

    check_environment()
    prepare_folders()

    try:
        run_cli(repo=args.repo, thread_id=args.thread)
    except AgentError as exc:       # e.g. invalid --repo path
        sys.exit(f"Error: {exc}")
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()