"""Tester Agent subgraph."""
from langgraph.graph import END, START, StateGraph

from src.agents.tester.nodes.advance_test import advance_test_node
from src.agents.tester.nodes.check_coverage import check_coverage_node
from src.agents.tester.nodes.check_test import check_test_node
from src.agents.tester.nodes.collect_changes import collect_changes_node
from src.agents.tester.nodes.diagnose import diagnose_node
from src.agents.tester.nodes.finalize import finalize_node
from src.agents.tester.nodes.generate_test import generate_test_node
from src.agents.tester.nodes.plan_tests import plan_tests_node
from src.agents.tester.nodes.prepare_retry import tester_prepare_retry_node
from src.agents.tester.nodes.prepare_test_fix import prepare_test_fix_node
from src.agents.tester.nodes.resolve_env import resolve_env_node
from src.agents.tester.nodes.run_tests import run_tests_node
from src.agents.tester.nodes.write_test import write_test_node
from src.agents.tester.routing import (
    on_tester_step, route_after_advance, route_after_collect, route_after_coverage,
    route_after_env, route_after_fix_prep, route_after_plan, route_after_run,
)
from src.state.graph_state import AgentState


def build_tester_graph():
    g = StateGraph(AgentState)

    g.add_node("collect_changes", collect_changes_node)
    g.add_node("plan_tests", plan_tests_node)                # LLM
    g.add_node("generate_test", generate_test_node)          # LLM
    g.add_node("write_test", write_test_node)
    g.add_node("check_test", check_test_node)
    g.add_node("advance_test", advance_test_node)
    g.add_node("prepare_retry", tester_prepare_retry_node)
    g.add_node("run_tests", run_tests_node)
    g.add_node("diagnose", diagnose_node)                    # LLM, ambiguous failures only
    g.add_node("resolve_env", resolve_env_node)              # may pause for the user
    g.add_node("prepare_test_fix", prepare_test_fix_node)
    g.add_node("check_coverage", check_coverage_node)        # may pause for the user
    g.add_node("finalize", finalize_node)

    g.add_edge(START, "collect_changes")
    g.add_conditional_edges("collect_changes", route_after_collect)
    g.add_conditional_edges("plan_tests", route_after_plan)
    g.add_edge("generate_test", "write_test")
    g.add_conditional_edges("write_test", on_tester_step("write_test", "check_test"))
    g.add_conditional_edges("check_test", on_tester_step("check_test", "advance_test"))
    g.add_conditional_edges("advance_test", route_after_advance)
    g.add_edge("prepare_retry", "generate_test")
    g.add_conditional_edges("run_tests", route_after_run)
    g.add_conditional_edges("diagnose", route_after_run)
    g.add_conditional_edges("resolve_env", route_after_env)
    g.add_conditional_edges("prepare_test_fix", route_after_fix_prep)
    g.add_conditional_edges("check_coverage", route_after_coverage)
    g.add_edge("finalize", END)
    return g.compile()