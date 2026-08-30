from pathlib import Path

import pytest

from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing.route_after_finalize_retrieval import (  # noqa: E501
    route_after_finalize_retrieval,
)


def test_finalize_retrieval_has_exact_node_projection_and_terminal_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    node = (owner / "nodes/finalize_retrieval_node.py").read_text()
    assert "project_finalize_retrieval_input" in node
    assert (owner / "projections/finalize_retrieval_projection.py").exists()
    assert 'return "end"' in (owner / "routing/route_after_finalize_retrieval.py").read_text()


def test_finalize_router_owns_confirmation_reentry_and_terminal_edges() -> None:
    assert (
        route_after_finalize_retrieval({"__context_retrieval_retry_confirmation__": True})
        == "finalize"
    )
    assert route_after_finalize_retrieval({"final_result": {"schema_version": 1}}) == "end"
    assert route_after_finalize_retrieval({"final_result": None}) == "end"
    with pytest.raises(ValueError, match="final_result"):
        route_after_finalize_retrieval({"final_result": "invalid"})
