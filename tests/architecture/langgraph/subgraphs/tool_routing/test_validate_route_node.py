from __future__ import annotations

from pathlib import Path

import pytest

from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing.route_after_finalize_route import (  # noqa: E501
    route_after_finalize_route,
)

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


def test_tool_route_router_rejects_unknown_disposition() -> None:
    with pytest.raises(ValueError, match="unexpected final route disposition"):
        route_after_finalize_route(
            {
                "tr_result": {
                    "schema_version": 1,
                    "disposition": "UNKNOWN",
                    "tool_route_plan": None,
                    "workflow_signal": None,
                    "reason_codes": [],
                }
            }
        )
