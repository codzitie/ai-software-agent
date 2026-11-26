"""Entry point used only by LangGraph Studio."""
from src.graph.main_graph import build_main_graph   # <-- adjust to your real name
from src.agents.codebase.graph import build_codebase_graph
from src.agents.issue.graph import build_issue_graph

graph = build_main_graph()   # compiled WITHOUT your own checkpointer
codebase_graph = build_codebase_graph()
issue_graph = build_issue_graph()