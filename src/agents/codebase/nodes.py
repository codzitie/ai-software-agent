"""Codebase Agent nodes: read docs -> locate files -> summarize context."""
from collections import Counter

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from config.settings import load_prompt
from src.llm.provider import get_llm
from src.state.graph_state import AgentState
from src.tools import filesystem, semantic_search, text_search
from src.state.schemas import CodebaseSummary

DOC_PATTERNS = ["README*", "ARCHITECTURE*", "CONTRIBUTING*", "docs/**/*.md", "*.md"]
MAX_DOC_CHARS = 6000
MAX_DOCS = 8
MAX_CANDIDATES = 8
MAX_FILE_CHARS = 5000


# ---------- structured outputs ----------
class SearchHints(BaseModel):
    keywords: list[str] = Field(description="Exact strings: error messages, identifiers, config keys")
    semantic_queries: list[str] = Field(description="Natural-language descriptions of the relevant code")
    file_hints: list[str] = Field(default_factory=list, description="File paths mentioned in the issue or docs")



# ---------- node 1: deterministic ----------
def read_docs_node(state: AgentState) -> dict:
    root = state["repo_path"]
    doc_paths = filesystem.glob_find(root, DOC_PATTERNS)

    # README first, then others, de-duplicated and capped.
    doc_paths = sorted(set(doc_paths), key=lambda p: (not p.lower().startswith("readme"), p))
    docs = {
        p: filesystem.read_file(root, p, max_chars=MAX_DOC_CHARS)
        for p in doc_paths[:MAX_DOCS]
    }
    return {"repo_tree": filesystem.tree(root), "docs": docs}


# ---------- node 2: LLM for hints, then deterministic search ----------
def locate_files_node(state: AgentState) -> dict:
    root = state["repo_path"]
    docs = state.get("docs", {})

    docs_text = "\n\n".join(f"### {p}\n{c[:1500]}" for p, c in docs.items()) or "No documentation found."
    llm = get_llm().with_structured_output(SearchHints)
    hints: SearchHints = llm.invoke(
        [
            SystemMessage(content=load_prompt("codebase")),
            HumanMessage(
                content=(
                    f"Issue / request:\n{state['user_query']}\n\n"
                    f"Project tree:\n{state['repo_tree']}\n\n"
                    f"Documentation excerpts:\n{docs_text}"
                )
            ),
        ]
    )

    scores: Counter[str] = Counter()

    for kw in hints.keywords:
        for hit in text_search.search(root, kw, max_hits=20):
            scores[hit.path] += 2  # exact matches weigh more

    for query in hints.semantic_queries:
        for rank, hit in enumerate(semantic_search.search(root, query, k=5)):
            scores[hit.path] += max(1, 5 - rank)

    for path in hints.file_hints:
        try:
            filesystem.read_file(root, path, max_chars=1)  # existence check
            scores[path] += 5
        except (FileNotFoundError, OSError):
            continue

    candidates = [p for p, _ in scores.most_common(MAX_CANDIDATES)]
    return {"candidate_files": candidates}


# ---------- node 3: LLM ----------
def summarize_context_node(state: AgentState) -> dict:
    root = state["repo_path"]
    files_text = "\n\n".join(
        f"### {p}\n{filesystem.read_file(root, p, max_chars=MAX_FILE_CHARS)}"
        for p in state.get("candidate_files", [])
    ) or "No candidate files were found."

    llm = get_llm().with_structured_output(CodebaseSummary)
    summary: CodebaseSummary = llm.invoke(
        [
            SystemMessage(content=load_prompt("codebase")),
            HumanMessage(
                content=(
                    f"Issue / request:\n{state['user_query']}\n\n"
                    f"Candidate files:\n{files_text}\n\n"
                    "Summarize which files matter, why, and where the problem most likely lives."
                )
            ),
        ]
    )
    return {"codebase_summary": summary}