"""FN-031 deterministic title normalization and decision matrix."""

import pytest

from google_work_agent.domain import (
    DuplicateDecision,
    TaskDuplicateCandidate,
    evaluate_task_duplicate,
    normalize_task_title,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Send   summary  ", "send summary"),
        ("Cafe\u0301", "café"),
        ("Straße", "strasse"),
        ("Send: summary!", "send: summary!"),
        ("résumé", "résumé"),
        ("Send\n\t summary", "send summary"),
    ],
)
def test_normalize_task_title_contract(raw: str, expected: str) -> None:
    assert normalize_task_title(raw) == expected


def _candidate(
    resource_id: str,
    *,
    title: str = "Send summary",
    scheduled_date: str | None = None,
    status: str | None = "needsAction",
) -> TaskDuplicateCandidate:
    return TaskDuplicateCandidate(
        resource_id=resource_id,
        title=title,
        scheduled_date=scheduled_date,
        status=status,
    )


@pytest.mark.parametrize(
    ("scheduled_date", "candidates", "decision", "matched_ids"),
    [
        (None, (_candidate("task-1"),), DuplicateDecision.CLEAR_DUPLICATE, ("task-1",)),
        (
            "2026-08-12",
            (_candidate("task-1", scheduled_date="2026-08-12"),),
            DuplicateDecision.CLEAR_DUPLICATE,
            ("task-1",),
        ),
        (
            "2026-08-12",
            (_candidate("task-1", scheduled_date="2026-08-13"),),
            DuplicateDecision.SIMILAR_CANDIDATE,
            ("task-1",),
        ),
        (
            "2026-08-12",
            (_candidate("task-1"),),
            DuplicateDecision.SIMILAR_CANDIDATE,
            ("task-1",),
        ),
        (
            None,
            (_candidate("task-1", title="Another task"),),
            DuplicateDecision.NOT_DUPLICATE,
            (),
        ),
        (
            None,
            (_candidate("task-1", status="completed"),),
            DuplicateDecision.NOT_DUPLICATE,
            (),
        ),
        (
            "2026-08-12",
            (
                _candidate("similar", scheduled_date="2026-08-13"),
                _candidate("clear", scheduled_date="2026-08-12"),
            ),
            DuplicateDecision.CLEAR_DUPLICATE,
            ("clear",),
        ),
        (
            None,
            (_candidate("z"), _candidate("a"), _candidate("a")),
            DuplicateDecision.CLEAR_DUPLICATE,
            ("a", "z"),
        ),
    ],
)
def test_task_duplicate_decision_matrix(
    scheduled_date: str | None,
    candidates: tuple[TaskDuplicateCandidate, ...],
    decision: DuplicateDecision,
    matched_ids: tuple[str, ...],
) -> None:
    result = evaluate_task_duplicate(
        title="Send summary",
        scheduled_date=scheduled_date,
        candidates=candidates,
    )

    assert result.decision is decision
    assert result.matched_resource_ids == matched_ids
