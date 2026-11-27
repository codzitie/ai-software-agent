"""Entry point used only by LangGraph Studio.

Graphs are compiled WITHOUT a checkpointer: Studio supplies its own.
The CLI (ChatSession) builds its own copy with a real checkpointer.
"""
from config import settings
from src.agents.codebase.graph import build_codebase_graph
from src.agents.developer.graph import build_developer_graph
from src.agents.issue.graph import build_issue_graph
from src.agents.tester.graph import build_tester_graph
from src.graph.main_graph import build_main_graph

_cfg = {"recursion_limit": settings.RECURSION_LIMIT}

graph = build_main_graph().with_config(_cfg)
codebase_graph = build_codebase_graph().with_config(_cfg)
issue_graph = build_issue_graph().with_config(_cfg)
developer_graph = build_developer_graph().with_config(_cfg)
tester_graph = build_tester_graph().with_config(_cfg)