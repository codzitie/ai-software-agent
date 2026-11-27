"""Parent graph: intake -> planner -> codebase -> issue | developer -> tester | chat_reply."""
from langgraph.graph import END, START, StateGraph

from src.agents.codebase.graph import build_codebase_graph
from src.agents.developer.graph import build_developer_graph
from src.agents.issue.graph import build_issue_graph
from src.agents.planner.node import planner_node
from src.agents.planner.router import route_after_planner
from src.agents.tester.graph import build_tester_graph
from src.graph.nodes import (
    chat_reply_node,
    intake_node,
    route_after_codebase,
    route_after_developer,
)
from src.graph.remember import remember
from src.state.graph_state import AgentState


def build_main_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("intake", intake_node)
    g.add_node("planner", remember("planner", "plan")(planner_node))
    g.add_node("codebase", build_codebase_graph())
    g.add_node("issue", build_issue_graph())
    g.add_node("developer", build_developer_graph())
    g.add_node("tester", build_tester_graph())
    g.add_node("chat_reply", remember("chat", "reply")(chat_reply_node))

    g.add_edge(START, "intake")
    g.add_edge("intake", "planner")
    g.add_conditional_edges("planner", route_after_planner)        # codebase | developer | chat_reply
    g.add_conditional_edges("codebase", route_after_codebase)      # issue | developer | chat_reply
    g.add_edge("issue", END)
    g.add_conditional_edges("developer", route_after_developer, {"tester": "tester", "end": END})
    g.add_edge("tester", END)
    g.add_edge("chat_reply", END)

    return g.compile(checkpointer=checkpointer)