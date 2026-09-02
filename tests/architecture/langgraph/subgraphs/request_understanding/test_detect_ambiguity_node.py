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


def test_detect_ambiguity_node__uses_exact_operation__projection_and_router() -> None:
    node = OWNER / "nodes/detect_ambiguity_node.py"
    projection = OWNER / "projections/detect_ambiguity_projection.py"
    router = OWNER / "routing/route_after_detect_ambiguity.py"

    assert {"project_detect_ambiguity_input", "detect_ambiguity"} <= _calls(node)
    assert "request_from_run_input_state" in _calls(projection)
    assert "route_after_detect_ambiguity" in router.read_text(encoding="utf-8")


def test_detect_ambiguity_has__its_own_prompt__call_and_bounded_input() -> None:
    operation = SRC / "application/agents/request_understanding/detect_ambiguity.py"
    source = operation.read_text(encoding="utf-8")

    assert '"request_understanding.detect_ambiguity"' in source
    assert "infer" in _calls(operation)
    assert '"user_request"' in source
    assert '"goal_candidate"' in source
    assert '"confirmation_response"' in source
    for forbidden in ("conversation_history", "previous_run", "checkpoint", "resume_payload"):
        assert forbidden not in source
