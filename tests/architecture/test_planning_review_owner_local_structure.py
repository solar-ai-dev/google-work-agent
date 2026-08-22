from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_owner_local_langgraph_structure_exists() -> None:
    for owner in ("planning", "review"):
        base = ROOT / f"src/google_work_agent/adapters/langgraph/subgraphs/{owner}"
        assert (base / "graph.py").is_file()
        assert (base / "state.py").is_file()
        assert (base / "nodes").is_dir()
        assert (base / "projections").is_dir()
        assert (base / "routing").is_dir()


def test_thin_nodes_do_not_import_forbidden_execution_boundaries() -> None:
    forbidden = ("sqlite3", "googleapiclient", "MCPTransport", "ConnectorExecutionPort")
    for owner in ("planning", "review"):
        for path in (ROOT / f"src/google_work_agent/adapters/langgraph/subgraphs/{owner}/nodes").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert all(token not in text for token in forbidden)


def test_broad_planning_review_modules_are_retired() -> None:
    base = ROOT / "src/google_work_agent/adapters/langgraph/subgraphs"
    assert not (base / "planning.py").exists()
    assert not (base / "review.py").exists()
