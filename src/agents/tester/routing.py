"""Routing for the tester subgraph. Own counters, so the Issue Agent's attempt/step_error are untouched."""
from config import settings
from src.state.graph_state import AgentState
from src.utils.trace import route, traced_router


def max_attempts() -> int:
    return getattr(settings, "MAX_TEST_ATTEMPTS", settings.MAX_PATCH_ATTEMPTS)


def max_coverage_rounds() -> int:
    return getattr(settings, "MAX_COVERAGE_ROUNDS", 1)


def on_tester_step(current: str, next_node: str):
    def router(state: AgentState) -> str:
        err = state.get("tester_error")
        if not err:
            route(f"after_{current}", next_node, "step ok")
            return next_node
        if state.get("tester_attempt", 0) >= max_attempts():
            route("tester_retry_limit", "finalize", err[:200])
            return "finalize"
        route("tester_retry", "prepare_retry", err[:200])
        return "prepare_retry"

    return router


@traced_router("after_collect")
def route_after_collect(state: AgentState) -> str:
    if state.get("tester_status") == "skipped":
        return "finalize"
    return "run_tests" if state.get("tests_written") else "plan_tests"      # tests kept: re-run them


@traced_router("after_plan_tests")
def route_after_plan(state: AgentState) -> str:
    return "finalize" if state.get("tester_error") else "generate_test"


@traced_router("after_advance_test")
def route_after_advance(state: AgentState) -> str:
    return "generate_test" if state.get("test_queue") else "run_tests"


@traced_router("after_run_tests")
def route_after_run(state: AgentState) -> str:
    if state.get("tester_status"):                         # blocked
        return "finalize"
    action = state.get("tester_action")
    if action == "done":
        return "check_coverage"
    if action == "fix_environment":
        return "resolve_env"
    if action == "review_ambiguous":
        return "diagnose"
    if action in ("fix_tests", "no_tests"):
        return "prepare_test_fix" if state.get("test_fix_rounds", 0) < max_attempts() else "finalize"
    return "finalize"                                      # fix_implementation


@traced_router("after_env")
def route_after_env(state: AgentState) -> str:
    return "finalize" if state.get("tester_status") else "run_tests"


@traced_router("after_test_fix")
def route_after_fix_prep(state: AgentState) -> str:
    return "finalize" if state.get("tester_status") else "generate_test"


@traced_router("after_coverage")
def route_after_coverage(state: AgentState) -> str:
    if state.get("coverage_gaps") and state.get("coverage_rounds", 0) <= max_coverage_rounds():
        return "plan_tests"
    return "finalize"