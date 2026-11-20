"""Which tools each agent is allowed to use."""
from typing import Callable

from src.tools import (
    code_modifier, dependency, filesystem, installer,
    semantic_search, syntax_checker, test_runner, text_search,
)

TOOLSETS: dict[str, dict[str, Callable]] = {
    "codebase": {
        "tree": filesystem.tree,
        "glob_find": filesystem.glob_find,
        "read_file": filesystem.read_file,
        "text_search": text_search.search,
        "semantic_search": semantic_search.search,
    },
    "issue": {
        "read_file": filesystem.read_file,
        "check_syntax": syntax_checker.check_files,
        "find_missing_deps": dependency.find_missing,
        "build_dependency_graph": dependency.build_graph,
        "find_cycles": dependency.find_cycles,
        "install": installer.install,
        "apply_edits": code_modifier.apply_edits,
        "rollback": code_modifier.rollback,
        "run_tests": test_runner.run,
    },
    "tester": {
        "read_file": filesystem.read_file,
        "glob_find": filesystem.glob_find,
        "run_tests": test_runner.run,
    },
}


def tools_for(agent: str) -> dict[str, Callable]:
    if agent not in TOOLSETS:
        raise KeyError(f"No toolset defined for agent '{agent}'")
    return TOOLSETS[agent]