from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "src/google_work_agent"
OWNER = SRC / "adapters/langgraph/subgraphs/tool_routing"


def test_validate_route_closes_exact_graph_state_and_legacy_negative_proof() -> None:
    node = (OWNER / "nodes/validate_route_node.py").read_text(encoding="utf-8")
    graph = (OWNER / "graph.py").read_text(encoding="utf-8")
    state = (OWNER / "state.py").read_text(encoding="utf-8")
    production = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.py"))

    assert "project_validate_route_input" in node
    assert "validate_route(" in node
    assert "route_after_validate_route" in graph
    assert "ToolRouteStateV1" in state
    assert "ToolRouteCoordinator" not in production
    assert "ToolRouteAgent" not in production
    assert "application.orchestration.tool_routing" not in production
    assert "application.orchestration.tool_route_semantic" not in production


def test_tool_route_state_has_exact_canonical_local_fields() -> None:
    state = (OWNER / "state.py").read_text(encoding="utf-8")
    for field in (
        "request_intent",
        "registry_snapshot_ref",
        "io_resource_candidate",
        "registry_candidates",
        "bound_input_routes",
        "bound_output_routes",
        "final_route",
    ):
        assert f"    {field}:" in state
    assert "tr_" not in state
    assert "ToolRoutingLocalState" not in state
