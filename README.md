# AI Software Agent

LangGraph-based agent that fixes bugs in an existing repository
(Planner -> Codebase Agent -> Issue Agent, with a terminal chat).

## Setup
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then add your API key
```

## Run
```bash
python main.py --repo /path/to/your/repo
```

Logs: `data/agent.log`. The agent edits files in the target repo, so use a copy or a git branch.