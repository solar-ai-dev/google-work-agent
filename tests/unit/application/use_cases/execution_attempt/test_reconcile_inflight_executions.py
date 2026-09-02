from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import Mock

import pytest

from google_work_agent.application.use_cases.execution_attempt import (
    reconcile_inflight_executions,
)
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty
from google_work_agent.ports.persistence.execution_attempt_repository import (
    ExecutionReconciliationCandidateV1,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

ReconcileInflightExecutionsCommand = (
    reconcile_inflight_executions.ReconcileInflightExecutionsCommand
)
ReconcileInflightExecutionsHandler = (
    reconcile_inflight_executions.ReconcileInflightExecutionsHandler
)


class _UnitOfWork:
    def __init__(self, **repositories: object) -> None:
        self.__dict__.update(repositories)

    def __enter__(self) -> "_UnitOfWork":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _candidate(
    kind: Literal[
        "PRE_BEGIN_ORPHAN",
        "POST_BEGIN_ORPHAN",
        "UNKNOWN_RESULT_UNRESOLVED",
        "EXECUTED_AWAITING_VERIFICATION",
        "FAILED_AWAITING_CONTINUATION",
    ],
) -> ExecutionReconciliationCandidateV1:
    return ExecutionReconciliationCandidateV1(
        schema_version=1,
        kind=kind,
        execution_attempt_id="attempt-1",
        action_id="action-1",
        run_id="run-1",
    )


def test_batch_uses__bounded_repository_contract__and_reports_progress() -> None:
    candidates = (_candidate("UNKNOWN_RESULT_UNRESOLVED"),) * 2
    attempts = SimpleNamespace(list_reconciliation_candidates=Mock(return_value=candidates))
    handler = object.__new__(ReconcileInflightExecutionsHandler)
    handler._unit_of_work_factory = lambda: cast(
        UnitOfWork, _UnitOfWork(execution_attempts=attempts)
    )
    cast(Any, handler)._reconcile = Mock(side_effect=(1, 0))

    result = handler(ReconcileInflightExecutionsCommand(schema_version=1, limit=2))

    attempts.list_reconciliation_candidates.assert_called_once_with(2)
    assert (result.processed_count, result.progressed_count, result.has_more) == (2, 1, True)
    with pytest.raises(ValueError, match="between 1 and 256"):
        handler(ReconcileInflightExecutionsCommand(schema_version=1, limit=257))


def test_post_begin__orphan_marks_unknown__without_resending_write() -> None:
    action = SimpleNamespace(id="action-1", version=3)
    attempt = SimpleNamespace(id="attempt-1", version=4)
    mark_unknown = Mock(return_value=SimpleNamespace(applied=True))
    handler = object.__new__(ReconcileInflightExecutionsHandler)
    handler._unit_of_work_factory = lambda: cast(
        UnitOfWork,
        _UnitOfWork(
            actions=SimpleNamespace(get=Mock(return_value=action)),
            execution_attempts=SimpleNamespace(get=Mock(return_value=attempt)),
        ),
    )
    handler._mark_unknown_result = mark_unknown

    assert handler._reconcile(_candidate("POST_BEGIN_ORPHAN")) == 1

    command = mark_unknown.call_args.args[0]
    assert command.command_id == "system:execution-attempt-reconcile:attempt-1"
    assert command.delivery_certainty is DeliveryCertainty.MAY_HAVE_BEEN_SENT
    assert command.expected_action_version == 3
    assert command.expected_attempt_version == 4


def test_pre_begin__orphan_aborts_claim__without_resending_write() -> None:
    action = SimpleNamespace(id="action-1", version=3)
    attempt = SimpleNamespace(id="attempt-1", version=0)
    abort = Mock(return_value=SimpleNamespace(applied=True))
    handler = object.__new__(ReconcileInflightExecutionsHandler)
    handler._unit_of_work_factory = lambda: cast(
        UnitOfWork,
        _UnitOfWork(
            actions=SimpleNamespace(get=Mock(return_value=action)),
            execution_attempts=SimpleNamespace(get=Mock(return_value=attempt)),
        ),
    )
    handler._abort_claimed_execution = abort

    assert handler._reconcile(_candidate("PRE_BEGIN_ORPHAN")) == 1

    command = abort.call_args.args[0]
    assert command.command_id == "system:execution-attempt-reconcile:attempt-1:abort"
    assert command.expected_action_version == 3
    assert command.expected_attempt_version == 0
    assert command.error_code == "PROCESS_RESTART_BEFORE_BEGIN"


def test_failed_continuation_uses__current_plan_and__current_run_guard() -> None:
    handler = object.__new__(ReconcileInflightExecutionsHandler)
    run = SimpleNamespace(status=RunStatusV1.WAITING_APPROVAL)
    current_plan = SimpleNamespace(id="plan-current", revision_no=2, created_at_ms=2)
    actions = SimpleNamespace(
        list_for_plan=Mock(return_value=(SimpleNamespace(status="APPROVED"),))
    )
    handler._unit_of_work_factory = lambda: cast(
        UnitOfWork,
        _UnitOfWork(
            runs=SimpleNamespace(get=Mock(return_value=run)),
            plans=SimpleNamespace(get_current=Mock(return_value=current_plan)),
            actions=actions,
        ),
    )
    stage_continuation = Mock(return_value=True)
    cast(Any, handler)._stage_continuation = stage_continuation

    candidate = _candidate("FAILED_AWAITING_CONTINUATION")
    assert handler._reconcile(candidate) == 1
    stage_continuation.assert_called_once_with(candidate, "PREFLIGHT", ":post-failed")

    run.status = RunStatusV1.CANCELLED
    actions.list_for_plan.return_value = ()
    stage_continuation.reset_mock()
    assert handler._reconcile(candidate) == 0
    stage_continuation.assert_not_called()
