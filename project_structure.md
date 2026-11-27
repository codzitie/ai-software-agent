<!-- Old Structrure (before starting development in developer and tester agents) -->

ai_software_agent/
├── pyproject.toml / requirements.txt
├── .env.example                  # API keys, DB config
├── README.md
│
├── config/
│   ├── settings.py               # env loading, model names, limits, paths
│   └── prompts/                  # prompts kept out of code
│       ├── planner.md
│       ├── codebase.md
│       ├── verify_issue.md
│       ├── root_cause.md
│       └── patch_generation.md
│
├── src/
│   ├── state/
│   │   ├── schemas.py            # Pydantic models: Plan, Task, IssueReport, RootCause, Patch, TestResult
│   │   └── graph_state.py        # main LangGraph TypedDict state
│   │
│   ├── llm/
│   │   └── provider.py           # one place to create the LLM (swap providers easily)
│   │
│   ├── tools/                    # SHARED TOOL LAYER (agent-agnostic)
│   │   ├── filesystem.py         # list_dir, tree, glob_find, read_file, ignore rules
│   │   ├── text_search.py        # exact text/regex search (ripgrep wrapper)
│   │   ├── semantic_search.py    # embeddings + vector store retrieval
│   │   ├── syntax_checker.py     # per-language syntax validation
│   │   ├── dependency.py         # identify deps, build graph, detect cycles
│   │   ├── installer.py          # install dependencies (sandboxed)
│   │   ├── code_modifier.py      # insert / remove / replace at location, with backup
│   │   ├── test_runner.py        # run repro scripts / test suites, capture output
│   │   └── registry.py           # exposes tool sets per agent
│   │
│   ├── agents/
│   │   ├── planner/
│   │   │   ├── node.py           # classify query + build plan + allocate tasks
│   │   │   └── router.py         # conditional edges: bug_fix vs new_project vs chat
│   │   │
│   │   ├── codebase/
│   │   │   ├── nodes.py          # read_docs, locate_files, summarize_context
│   │   │   └── graph.py          # codebase subgraph
│   │   │
│   │   └── issue/
│   │       ├── nodes/
│   │       │   ├── verify_issue.py     # LLM: does the issue really exist?
│   │       │   ├── root_cause.py       # LLM: why does it happen?
│   │       │   ├── generate_patch.py   # LLM: produce the code change
│   │       │   ├── apply_patch.py      # deterministic
│   │       │   ├── check_syntax.py     # deterministic
│   │       │   ├── check_deps.py       # deterministic (install if missing)
│   │       │   └── run_tests.py        # deterministic
│   │       ├── routing.py        # retry loop / give-up / success logic
│   │       └── graph.py          # issue subgraph
│   │
│   ├── memory/
│   │   ├── short_term.py         # per-run context: issue details, errors, summaries
│   │   ├── long_term.py          # persistent project info, markdown docs
│   │   ├── store.py              # DB interface (SQLite now, MySQL/Firestore later)
│   │   └── checkpointer.py       # LangGraph checkpointer (also enables pause/resume later)
│   │
│   ├── graph/
│   │   └── main_graph.py         # parent graph wiring planner → codebase → issue
│   │
│   ├── chat/
│   │   ├── session.py            # thread IDs, history, runs the graph per message
│   │   └── cli.py                # terminal chat loop
│   │
│   └── utils/
│       ├── logging.py
│       └── errors.py
│
├── workspace/                    # repos the agent operates on (git-ignored)
├── data/                         # SQLite DB, vector index (git-ignored)
├── tests/
│   ├── tools/
│   ├── agents/
│   └── fixtures/sample_buggy_repo/   # small repo with a known bug for end-to-end testing
└── main.py                       # entry point