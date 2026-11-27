"""Render all agent graphs as PNG. Usage: python scripts/visualize_graph.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

# <-- adjust these names to whatever your files actually export
from src.graph.main_graph import build_main_graph
from src.agents.codebase.graph import build_codebase_graph
from src.agents.issue.graph import build_issue_graph

OUT = Path("docs")
OUT.mkdir(exist_ok=True)

graphs = {
    "1_main": build_main_graph(),
    "2_codebase": build_codebase_graph(),
    "3_issue": build_issue_graph(),
}

for name, app in graphs.items():
    g = app.get_graph(xray=True)
    (OUT / f"{name}.mmd").write_text(g.draw_mermaid(), encoding="utf-8")
    try:
        (OUT / f"{name}.png").write_bytes(g.draw_mermaid_png())
        print(f"Wrote docs/{name}.png")
    except Exception as exc:
        print(f"PNG failed for {name}: {exc} (use the .mmd on mermaid.live)")