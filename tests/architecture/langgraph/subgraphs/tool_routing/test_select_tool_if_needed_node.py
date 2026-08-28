from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
OWNER = ROOT / "src/google_work_agent/adapters/langgraph/subgraphs/tool_routing"


def test_select_tool_uses_only_bound_candidates_and_exact_boundary_files() -> None:
    node = (OWNER / "nodes/select_tool_if_needed_node.py").read_text(encoding="utf-8")
    assert "project_select_tool_if_needed_input" in node
    assert "eligible_tool_ids=bound.eligible_tool_ids" in node
    assert "SignedToolRegistry" not in node
    assert (OWNER / "projections/select_tool_if_needed_projection.py").is_file()
    assert (OWNER / "routing/route_after_select_tool_if_needed.py").is_file()
