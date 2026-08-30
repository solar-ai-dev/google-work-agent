from __future__ import annotations

import re
from pathlib import Path
from typing import get_type_hints

from google_work_agent.adapters.langgraph.subgraphs.review.state import ReviewState
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewInspectorResultV1,
)

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src/google_work_agent"
LANGGRAPH = SRC / "adapters/langgraph"


def _formal_ids(path: Path, prefix: str) -> set[str]:
    pattern = re.compile(rf"^\| ({prefix}-[A-Z0-9-]+) \|", re.MULTILINE)
    return set(pattern.findall(path.read_text(encoding="utf-8")))


def test_ledger_and_map_cover_the_exact_current_formal_universe() -> None:
    ledger = ROOT / "implementation-inventory/ledger.md"
    implementation_map = ROOT / "implementation-inventory/canonical-current-implementation-map.md"

    expected_counts = {"CAP": 142, "STR": 473, "NPA": 85}
    for prefix, expected_count in expected_counts.items():
        ledger_ids = _formal_ids(ledger, prefix)
        map_ids = _formal_ids(implementation_map, prefix)
        assert len(ledger_ids) == expected_count
        assert map_ids == ledger_ids


def test_retrieval_result_is_the_only_main_retrieval_business_artifact() -> None:
    live_boundary_files = (
        LANGGRAPH / "main/state.py",
        LANGGRAPH / "main/response_synthesis.py",
        LANGGRAPH / "subgraph_state.py",
        SRC / "application/orchestration/contracts.py",
        SRC / "application/orchestration/supervisor.py",
        SRC / "application/use_cases/run/run_terminal.py",
    )
    for path in live_boundary_files:
        source = path.read_text(encoding="utf-8")
        assert "context_result" not in source, path.relative_to(SRC).as_posix()
    assert "retrieval_result" in (LANGGRAPH / "main/state.py").read_text(encoding="utf-8")


def test_review_graph_uses_one_typed_owner_local_state() -> None:
    review_graph = (LANGGRAPH / "subgraphs/review/graph.py").read_text(encoding="utf-8")
    shared_states = (LANGGRAPH / "subgraph_state.py").read_text(encoding="utf-8")
    hints = get_type_hints(ReviewState)

    assert "ReviewLocalState" not in review_graph
    assert "ReviewLocalState" not in shared_states
    assert "StateGraph(ReviewState" in review_graph
    assert hints["goal_evidence_result"] is ReviewInspectorResultV1
    assert hints["action_scope_route_result"] is ReviewInspectorResultV1
    assert hints["constraints_policy_result"] is ReviewInspectorResultV1
