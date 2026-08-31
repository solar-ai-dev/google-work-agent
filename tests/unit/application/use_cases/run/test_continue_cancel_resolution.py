"""Exact ownership smoke gate for the canonical Application module."""

from importlib import import_module
from types import SimpleNamespace
from typing import Self

from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionCommandV1,
    ContinueCancelResolutionHandler,
)
from google_work_agent.domain.run.model import RunStatusV1


def test_canonical_application_owner_is_importable() -> None:
    assert (
        import_module("google_work_agent.application.use_cases.run.continue_cancel_resolution")
        is not None
    )


def test_expired_action_is_settled_before_finalize_cancel() -> None:
    calls: list[tuple[str, int]] = []

    class _Uow:
        command_receipts = SimpleNamespace(has_durable_cancel_intent=lambda _run_id: True)
        runs = SimpleNamespace(
            get=lambda _run_id: SimpleNamespace(
                id="run-1", status=RunStatusV1.CANCEL_REQUESTED, version=2
            )
        )
        plans = SimpleNamespace(
            get_current=lambda _run_id: SimpleNamespace(id="plan-1", revision_no=1)
        )
        actions = SimpleNamespace(
            list_for_plan=lambda _plan_id: (
                SimpleNamespace(id="action-1", status="EXPIRED", version=4),
            )
        )

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def settle_pending_action(action_id: str, version: int) -> bool:
        calls.append((action_id, version))
        return True

    handler = ContinueCancelResolutionHandler(
        unit_of_work_factory=_Uow,  # type: ignore[arg-type]
        settle_pending_action=settle_pending_action,
        reconcile_inflight_action=lambda _action_id: False,
        verify_executed_action=lambda _action_id: False,
        resolve_unknown_action=lambda _action_id: False,
        finalize_cancel=lambda _run_id, _version: (_ for _ in ()).throw(
            AssertionError("FinalizeCancel must wait for EXPIRED settlement")
        ),
    )

    result = handler(ContinueCancelResolutionCommandV1(1, "run-1"))

    assert result.outcome == "PROGRESSED"
    assert calls == [("action-1", 4)]
