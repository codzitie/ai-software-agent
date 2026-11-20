"""Codebase Agent subgraph."""
from langgraph.graph import END, START, StateGraph

from src.agents.codebase.nodes import (
    locate_files_node,
    read_docs_node,
    summarize_context_node,
)
from src.state.graph_state import AgentState


def build_codebase_graph():
    g = StateGraph(AgentState)
    g.add_node("read_docs", read_docs_node)
    g.add_node("locate_files", locate_files_node)
    g.add_node("summarize_context", summarize_context_node)

    g.add_edge(START, "read_docs")
    g.add_edge("read_docs", "locate_files")
    g.add_edge("locate_files", "summarize_context")
    g.add_edge("summarize_context", END)
    return g.compile()