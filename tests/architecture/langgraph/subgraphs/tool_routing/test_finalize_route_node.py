from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "src/google_work_agent"
OWNER = SRC / "adapters/langgraph/subgraphs/tool_routing"


def test_finalize_route_uses_exact_projection_and_policy_operation() -> None:
    node = (OWNER / "nodes/finalize_route_node.py").read_text(encoding="utf-8")
    bind_node = (OWNER / "nodes/bind_registry_candidates_node.py").read_text(
        encoding="utf-8"
    )
    operation = (SRC / "application/agents/tool_routing/finalize_route.py").read_text(
        encoding="utf-8"
    )
    assert "project_finalize_route_input" in node
    assert "finalize_route(" in node
    assert "resolve_policy_preconditions(" in bind_node
    assert "resolve_policy_preconditions(" not in operation
    assert (OWNER / "routing/route_after_finalize_route.py").is_file()
