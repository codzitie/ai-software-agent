"""Issue Agent subgraph."""
from langgraph.graph import END, START, StateGraph

from src.agents.issue.nodes.apply_patch import apply_patch_node
from src.agents.issue.nodes.check_deps import check_deps_node
from src.agents.issue.nodes.check_syntax import check_syntax_node
from src.agents.issue.nodes.finalize import finalize_node
from src.agents.issue.nodes.generate_patch import generate_patch_node
from src.agents.issue.nodes.prepare_retry import prepare_retry_node
from src.agents.issue.nodes.root_cause import root_cause_node
from src.agents.issue.nodes.run_tests import run_tests_node
from src.agents.issue.nodes.verify_issue import verify_issue_node
from src.agents.issue.routing import on_step_result, route_after_verify
from src.state.graph_state import AgentState


def build_issue_graph():
    g = StateGraph(AgentState)

    g.add_node("verify_issue", verify_issue_node)      # LLM
    g.add_node("find_root_cause", root_cause_node)          # LLM
    g.add_node("generate_patch", generate_patch_node)  # LLM
    g.add_node("apply_patch", apply_patch_node)
    g.add_node("check_syntax", check_syntax_node)
    g.add_node("check_deps", check_deps_node)
    g.add_node("run_tests", run_tests_node)
    g.add_node("prepare_retry", prepare_retry_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "verify_issue")
    g.add_conditional_edges("verify_issue", route_after_verify)
    g.add_edge("find_root_cause", "generate_patch")
    g.add_edge("generate_patch", "apply_patch")

    g.add_conditional_edges("apply_patch", on_step_result("apply_patch", "check_syntax"))
    g.add_conditional_edges("check_syntax", on_step_result("check_syntax", "check_deps"))
    g.add_conditional_edges("check_deps", on_step_result("check_deps", "run_tests"))
    g.add_conditional_edges("run_tests", on_step_result("run_tests", "finalize"))

    g.add_edge("prepare_retry", "generate_patch")
    g.add_edge("finalize", END)
    return g.compile()