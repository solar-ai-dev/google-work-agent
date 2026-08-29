"""Recovery option projection uses the Domain-owned closed matrix."""

from contextlib import contextmanager
from importlib import import_module
from types import SimpleNamespace

import pytest

from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsHandler,
    ProjectRecoveryOptionsQueryV1,
)


def test_canonical_application_owner_is_importable() -> None:
    assert (
        import_module("google_work_agent.application.use_cases.recovery.project_recovery_options")
        is not None
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("UNKNOWN_RESULT", ("RECHECK",)),
        (
            "VERIFICATION_MISMATCH",
            ("RECHECK", "ACCEPT_PARTIAL", "CREATE_CORRECTIVE_PLAN", "FAIL"),
        ),
        ("CHECKPOINT_MISMATCH", ("RECHECK", "FAIL")),
        ("CONTRACT_VIOLATION", ("RECHECK", "FAIL")),
    ],
)
def test_projection_matches_domain_matrix_without_cancel_intent(
    reason: str, expected: tuple[str, ...]
) -> None:
    context = {
        "reason": reason,
        "action_id": "action-1" if reason in {"UNKNOWN_RESULT", "VERIFICATION_MISMATCH"} else None,
    }

    @contextmanager
    def factory():
        yield SimpleNamespace(
            recovery_contexts=SimpleNamespace(load_current_context=lambda _run_id: context),
            cancel_intents=SimpleNamespace(has_durable_intent=lambda _run_id: False),
            plans=SimpleNamespace(get_current=lambda _run_id: None),
            actions=SimpleNamespace(list_for_plan=lambda _plan_id: ()),
        )

    result = ProjectRecoveryOptionsHandler(factory)(ProjectRecoveryOptionsQueryV1("run-1"))

    assert result.allowed_resolution_kinds == expected
    assert result.target == (
        {"target_kind": "ACTION", "action_id": "action-1"}
        if reason in {"UNKNOWN_RESULT", "VERIFICATION_MISMATCH"}
        else {"target_kind": "RUN"}
    )


def test_executed_awaiting_verification_hides_terminal_resolutions() -> None:
    context = {"reason": "CHECKPOINT_MISMATCH", "action_id": None}
    plan = SimpleNamespace(id="plan-1")
    executed = SimpleNamespace(id="action-1", status="EXECUTED")

    @contextmanager
    def factory():
        yield SimpleNamespace(
            recovery_contexts=SimpleNamespace(load_current_context=lambda _run_id: context),
            cancel_intents=SimpleNamespace(has_durable_intent=lambda _run_id: True),
            plans=SimpleNamespace(get_current=lambda _run_id: plan),
            actions=SimpleNamespace(list_for_plan=lambda _plan_id: (executed,)),
        )

    result = ProjectRecoveryOptionsHandler(factory)(ProjectRecoveryOptionsQueryV1("run-1"))

    assert result.allowed_resolution_kinds == ("RECHECK",)
