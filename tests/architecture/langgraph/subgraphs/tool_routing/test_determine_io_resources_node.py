from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
OWNER = ROOT / "src/google_work_agent/adapters/langgraph/subgraphs/tool_routing"


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
    }


def test_determine_resources_uses_exact_operation_projection_and_router() -> None:
    assert {"project_determine_io_resources_input", "determine_io_resources"} <= _calls(
        OWNER / "nodes/determine_io_resources_node.py"
    )
    assert (OWNER / "projections/determine_io_resources_projection.py").is_file()
    assert (OWNER / "routing/route_after_determine_io_resources.py").is_file()
