from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "src/google_work_agent"
OWNER = SRC / "adapters/langgraph/subgraphs/request_understanding"


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
    }


def test_identify_goal_node_uses_exact_operation_projection_and_router() -> None:
    node = OWNER / "nodes/identify_goal_node.py"
    projection = OWNER / "projections/identify_goal_projection.py"
    router = OWNER / "routing/route_after_identify_goal.py"

    assert {"project_identify_goal_input", "identify_goal"} <= _calls(node)
    assert "request_from_state" in _calls(projection)
    assert "route_after_identify_goal" in router.read_text(encoding="utf-8")


def test_identify_goal_prompt_boundary_is_current_run_only() -> None:
    operation = SRC / "application/agents/request_understanding/identify_goal.py"
    source = operation.read_text(encoding="utf-8")

    assert '"request_understanding.identify_goal"' in source
    assert '"user_request"' in source
    assert '"selected_resource_refs"' in source
    assert '"confirmation_response"' in source
    for forbidden in ("conversation_history", "previous_run", "checkpoint", "resume_payload"):
        assert forbidden not in source


def test_request_understanding_broad_production_authority_is_absent() -> None:
    assert not (SRC / "application/orchestration/request_understanding.py").exists()
    production = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.py"))
    assert "RequestUnderstandingAgent" not in production
    assert "application.orchestration.request_understanding" not in production
    assert "request_understanding.classify" not in production
