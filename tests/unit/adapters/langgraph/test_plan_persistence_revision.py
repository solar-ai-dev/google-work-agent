from types import SimpleNamespace

from google_work_agent.adapters.langgraph.main.plan_persistence import (
    next_plan_revision_no,
)


def test_next_plan_revision_counts_superseded_history() -> None:
    assert next_plan_revision_no(()) == 1
    assert next_plan_revision_no(
        (
            SimpleNamespace(revision_no=1, status="SUPERSEDED"),
            SimpleNamespace(revision_no=3, status="SUPERSEDED"),
        )
    ) == 4
