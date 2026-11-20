"""All configuration in one place. Values that change per machine come from .env."""
import os
from functools import lru_cache
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# ---- folders ----
DATA_DIR = ROOT_DIR / "data"
WORKSPACE_DIR = ROOT_DIR / "workspace"

# ---- LLM ----
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")   # anthropic | openai | google
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
LLM_TEMPERATURE = 0.0          # deterministic: the agents need consistent edits
LLM_MAX_TOKENS = 4096
LLM_TIMEOUT = 120              # seconds per call
LLM_MAX_RETRIES = 3            # network / rate-limit retries inside the client

# API key variable required for each provider (used by main.py)
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
}

# ---- storage and checkpoints ----
STORE_BACKEND = "sqlite"            # later: "mysql" | "firestore"
STORE_DB_PATH = DATA_DIR / "agent.db"
CHECKPOINT_BACKEND = "sqlite"       # "sqlite" | "memory"
CHECKPOINT_DB_PATH = DATA_DIR / "checkpoints.db"

# ---- conversation memory ----
SUMMARY_TRIGGER_MESSAGES = 12       # summarize history after this many messages
SUMMARY_KEEP_LAST = 6               # recent messages kept verbatim

# ---- issue agent ----
MAX_PATCH_ATTEMPTS = 3

# ---- graph ----
RECURSION_LIMIT = 100               # LangGraph's default (25) is too low for the retry loop

# ---- logging ----
LOG_LEVEL = "INFO"                  # file level
CONSOLE_LOG_LEVEL = "WARNING"       # keeps the chat screen quiet
LOG_FILE = DATA_DIR / "agent.log"

# ---- tools ----
IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".tox", ".eggs",
}
MAX_FILE_BYTES = 1_000_000
BACKUP_DIR = DATA_DIR / "backups"
ENV_DIR = DATA_DIR / "envs"
VECTOR_DIR = DATA_DIR / "vector"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
CHUNK_LINES = 40
CHUNK_OVERLAP = 10
MAX_INDEX_CHUNKS = 8000
PIP_TIMEOUT = 600
TEST_OUTPUT_CHARS = 8000

# Pinecone
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv(
    "PINECONE_INDEX_NAME", "Coding Agent"
)
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")

# ---- tracing ----
TRACE_ARGS_CHARS = 600       # tool arguments and results are cut to this length
TRACE_LLM_CHARS = 6000       # prompts and replies are cut to this length (0 = no limit)

@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Read config/prompts/<name>.md"""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()