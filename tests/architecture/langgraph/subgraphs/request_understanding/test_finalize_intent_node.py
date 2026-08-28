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
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Name, ast.Attribute))
    }


def test_finalize_node_owns_finalize_and_validate_in_one_runtime_node() -> None:
    node = OWNER / "nodes/finalize_intent_node.py"
    operation = SRC / "application/agents/request_understanding/finalize_intent.py"
    router = OWNER / "routing/route_after_finalize_intent.py"

    assert {"project_finalize_intent_input", "finalize_intent"} <= _calls(node)
    assert "validate_intent" in _calls(operation)
    assert "route_after_finalize_intent" in router.read_text(encoding="utf-8")
    assert not (OWNER / "nodes/validate_intent_node.py").exists()


def test_request_understanding_graph_and_state_are_exact() -> None:
    graph = (OWNER / "graph.py").read_text(encoding="utf-8")
    state = (OWNER / "state.py").read_text(encoding="utf-8")

    assert "RequestUnderstandingStateV2" in state
    assert "RequestUnderstandingStateV2" in graph
    assert 'graph.add_node("identify_goal"' in graph
    assert 'graph.add_node("detect_ambiguity"' in graph
    assert 'graph.add_node("finalize_intent"' in graph
    assert 'graph.add_node("validate_intent"' not in graph
