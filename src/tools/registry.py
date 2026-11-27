"""Which tools each agent is allowed to use."""
from typing import Callable

from src.tools import (
    code_modifier, coverage_tool, dependency, diff_reader, file_writer, filesystem,
    formatter, git_tool, import_checker, installer, manifest, project_inspector,
    scaffold, semantic_search, syntax_checker, test_result_parser, test_runner, text_search,
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
    "developer": {
        "inspect_project": project_inspector.inspect,
        "write_files": file_writer.write_files,
        "remove_created": file_writer.remove_created,
        "scaffold": scaffold.create,
        "apply_edits": code_modifier.apply_edits,
        "rollback": code_modifier.rollback,
        "check_imports": import_checker.check_imports,
        "format_files": formatter.format_files,
        "install": installer.install,
        "record_dependencies": manifest.record_dependencies,
        "undo_manifest": manifest.undo,
        "start_task": git_tool.start_task,
        "commit": git_tool.commit,
        "reset_to": git_tool.reset_to,
        "abandon_task": git_tool.abandon_task,
        "run_tests": test_runner.run,
        "check_coverage": coverage_tool.check_changed,
    },
    "tester": {
        "read_file": filesystem.read_file,
        "glob_find": filesystem.glob_find,
        "write_files": file_writer.write_files,
        "remove_created": file_writer.remove_created,
        "analyze_diff": diff_reader.analyze,
        "changes_from_texts": diff_reader.from_texts,
        "diff": git_tool.diff,
        "check_imports": import_checker.check_imports,
        "run_tests": test_runner.run,
        "parse_results": test_result_parser.parse_pytest_output,
        "check_coverage": coverage_tool.check_changed,
        "install": installer.install,
    },
}


def tools_for(agent: str) -> dict[str, Callable]:
    if agent not in TOOLSETS:
        raise KeyError(f"No toolset defined for agent '{agent}'")
    return TOOLSETS[agent]