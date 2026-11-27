"""One place that asks the user before anything is installed (LangGraph interrupt)."""
from langgraph.types import interrupt


def as_bool(answer) -> bool:
    if isinstance(answer, dict):
        answer = answer.get("approved", False)
    if isinstance(answer, str):
        return answer.strip().lower() in {"y", "yes", "true", "1", "ok"}
    return bool(answer)


def ask(packages: list[str], reason: str, root) -> bool:
    """Pause the graph. The CLI shows the payload and resumes with True/False."""
    answer = interrupt({
        "kind": "confirm_install",
        "packages": list(packages),
        "reason": reason,
        "repo": str(root),
    })
    return as_bool(answer)