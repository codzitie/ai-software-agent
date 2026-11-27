"""Developer Agent subgraph."""
from langgraph.graph import END, START, StateGraph

from src.agents.developer.nodes.advance import advance_node
from src.agents.developer.nodes.check_imports import check_imports_node
from src.agents.developer.nodes.check_syntax import check_syntax_node
from src.agents.developer.nodes.commit_step import commit_step_node
from src.agents.developer.nodes.confirm_install import confirm_install_node
from src.agents.developer.nodes.ensure_tools import ensure_tools_node
from src.agents.developer.nodes.finalize import finalize_node
from src.agents.developer.nodes.format_code import format_code_node
from src.agents.developer.nodes.generate_file import generate_file_node
from src.agents.developer.nodes.inspect_project import inspect_project_node
from src.agents.developer.nodes.install_packages import install_packages_node
from src.agents.developer.nodes.plan_dev import plan_dev_node
from src.agents.developer.nodes.prepare_retry import dev_prepare_retry_node
from src.agents.developer.nodes.reconcile_plan import reconcile_plan_node
from src.agents.developer.nodes.scaffold import scaffold_node
from src.agents.developer.nodes.smoke_test import smoke_test_node
from src.agents.developer.nodes.start_git import start_git_node
from src.agents.developer.nodes.write_file import write_file_node
from src.agents.developer.routing import (
    on_step_result, route_after_advance, route_after_reconcile, route_after_scaffold,
    route_after_start_git, route_after_tools,
)
from src.state.graph_state import AgentState


def build_developer_graph():
    g = StateGraph(AgentState)

    g.add_node("inspect_project", inspect_project_node)
    g.add_node("plan_dev", plan_dev_node)                 # LLM
    g.add_node("start_git", start_git_node)
    g.add_node("scaffold", scaffold_node)
    g.add_node("reconcile_plan", reconcile_plan_node)
    g.add_node("ensure_tools", ensure_tools_node)         # may pause for the user
    g.add_node("generate_file", generate_file_node)       # LLM
    g.add_node("write_file", write_file_node)
    g.add_node("check_syntax", check_syntax_node)
    g.add_node("check_imports", check_imports_node)
    g.add_node("confirm_install", confirm_install_node)   # may pause for the user
    g.add_node("install_packages", install_packages_node)
    g.add_node("format_code", format_code_node)
    g.add_node("commit_step", commit_step_node)
    g.add_node("advance", advance_node)
    g.add_node("smoke_test", smoke_test_node)
    g.add_node("prepare_retry", dev_prepare_retry_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "inspect_project")
    g.add_edge("inspect_project", "plan_dev")
    g.add_edge("plan_dev", "start_git")
    g.add_conditional_edges("start_git", route_after_start_git)
    g.add_conditional_edges("scaffold", route_after_scaffold)
    g.add_conditional_edges("reconcile_plan", route_after_reconcile)
    g.add_conditional_edges("ensure_tools", route_after_tools)

    g.add_edge("generate_file", "write_file")
    g.add_conditional_edges("write_file", on_step_result("write_file", "check_syntax"))
    g.add_conditional_edges("check_syntax", on_step_result("check_syntax", "check_imports"))
    g.add_conditional_edges("check_imports", on_step_result("check_imports", "confirm_install"))
    g.add_conditional_edges("confirm_install", on_step_result("confirm_install", "install_packages"))
    g.add_conditional_edges("install_packages", on_step_result("install_packages", "format_code"))
    g.add_conditional_edges("format_code", on_step_result("format_code", "commit_step"))
    g.add_conditional_edges("commit_step", on_step_result("commit_step", "advance"))
    g.add_conditional_edges("advance", route_after_advance)
    g.add_conditional_edges("smoke_test", on_step_result("smoke_test", "finalize"))

    g.add_edge("prepare_retry", "generate_file")
    g.add_edge("finalize", END)
    return g.compile()