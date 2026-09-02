from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
OWNER = ROOT / "src/google_work_agent/adapters/langgraph/subgraphs/tool_routing"


def test_bind_candidates_has__exact_projection_router__and_no_precondition_node() -> None:
    node = (OWNER / "nodes/bind_registry_candidates_node.py").read_text(encoding="utf-8")
    assert "project_bind_registry_candidates_input" in node
    assert "bind_registry_candidates(" in node
    assert (OWNER / "projections/bind_registry_candidates_projection.py").is_file()
    assert (OWNER / "routing/route_after_bind_registry_candidates.py").is_file()
    assert not (OWNER / "nodes/resolve_policy_preconditions_node.py").exists()
