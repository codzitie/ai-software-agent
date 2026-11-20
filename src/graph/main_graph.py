"""Parent graph: intake -> planner -> (codebase -> issue) | chat_reply | unsupported."""
from langgraph.graph import END, START, StateGraph

from src.agents.codebase.graph import build_codebase_graph
from src.agents.issue.graph import build_issue_graph
from src.agents.planner.node import planner_node
from src.agents.planner.router import route_after_planner
from src.graph.nodes import (
    chat_reply_node,
    intake_node,
    route_after_codebase,
    unsupported_node,
)
from src.graph.remember import remember
from src.memory.checkpointer import get_checkpointer
from src.state.graph_state import AgentState


def build_main_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("intake", intake_node)
    g.add_node("planner", remember("planner", "plan")(planner_node))
    g.add_node("codebase", build_codebase_graph())   # subgraphs are added as nodes
    g.add_node("issue", build_issue_graph())
    g.add_node("chat_reply", remember("chat", "reply")(chat_reply_node))
    g.add_node("unsupported", remember("planner", "unsupported")(unsupported_node))

    g.add_edge(START, "intake")
    g.add_edge("intake", "planner")
    g.add_conditional_edges("planner", route_after_planner)       # codebase | chat_reply | unsupported
    g.add_conditional_edges("codebase", route_after_codebase)     # issue | chat_reply
    g.add_edge("issue", END)
    g.add_edge("chat_reply", END)
    g.add_edge("unsupported", END)

    return g.compile(checkpointer=checkpointer or get_checkpointer())