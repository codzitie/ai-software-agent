"""Deterministic: this test file is done, move to the next one."""
from src.state.graph_state import AgentState


def advance_test_node(state: AgentState) -> dict:
    return {"test_queue": state.get("test_queue", [])[1:], "tester_attempt": 0,
            "tester_feedback": [], "tester_step_written": [], "test_generated": None,
            "tester_error": None}