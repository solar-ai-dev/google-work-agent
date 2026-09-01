"""Recovery option projection uses the Domain-owned closed matrix."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast

import pytest

from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsHandler,
    ProjectRecoveryOptionsQueryV1,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("UNKNOWN_RESULT", ("RECHECK",)),
        (
            "VERIFICATION_MISMATCH",
            ("RECHECK", "ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN"),
        ),
        ("CHECKPOINT_MISMATCH", ("RECHECK",)),
        ("CONTRACT_VIOLATION", ("RECHECK",)),
    ],
)
def test_projection_matches_domain_matrix_without_cancel_intent(
    reason: str, expected: tuple[str, ...]
) -> None:
    context = {
        "run_id": "run-1",
        "reason": reason,
        "action_id": "action-1" if reason in {"UNKNOWN_RESULT", "VERIFICATION_MISMATCH"} else None,
    }

    @contextmanager
    def factory() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(
            recovery_contexts=SimpleNamespace(load_current_context=lambda _run_id: context),
            command_receipts=SimpleNamespace(has_durable_cancel_intent=lambda _run_id: False),
            plans=SimpleNamespace(get_current=lambda _run_id: None),
            actions=SimpleNamespace(get=lambda _action_id: None, list_for_plan=lambda _plan_id: ()),
        )

    result = ProjectRecoveryOptionsHandler(cast(Callable[[], UnitOfWork], factory))(
        ProjectRecoveryOptionsQueryV1("run-1")
    )

    assert result.allowed_resolution_kinds == expected
    assert result.target == (
        {"target_kind": "ACTION", "action_id": "action-1"}
        if reason in {"UNKNOWN_RESULT", "VERIFICATION_MISMATCH"}
        else {"target_kind": "RUN"}
    )


def test_executed_awaiting_verification_hides_terminal_resolutions() -> None:
    context = {"run_id": "run-1", "reason": "CHECKPOINT_MISMATCH", "action_id": None}
    plan = SimpleNamespace(id="plan-1")
    executed = SimpleNamespace(id="action-1", status="EXECUTED")

    @contextmanager
    def factory() -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(
            recovery_contexts=SimpleNamespace(load_current_context=lambda _run_id: context),
            command_receipts=SimpleNamespace(has_durable_cancel_intent=lambda _run_id: True),
            plans=SimpleNamespace(get_current=lambda _run_id: plan),
            actions=SimpleNamespace(
                get=lambda _action_id: None, list_for_plan=lambda _plan_id: (executed,)
            ),
        )

    result = ProjectRecoveryOptionsHandler(cast(Callable[[], UnitOfWork], factory))(
        ProjectRecoveryOptionsQueryV1("run-1")
    )

    assert result.allowed_resolution_kinds == ("RECHECK",)
