from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.application.execution_phase import (
    WriteExecutionDisposition,
    WriteExecutionPhaseCoordinator,
    WriteExecutionPhaseRequest,
)
from google_work_agent.application.write_actions import (
    ClaimWriteActionService,
    ExecutedWriteActionResult,
    ExecuteWriteActionService,
    MarkWriteActionFailedService,
    MarkWriteActionUnknownResultService,
    PreflightWriteActionService,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionService,
    RequireWriteReauthService,
    StoreWriteActionSuccessService,
    VerifyWriteActionService,
    WriteActionResponse,
)
from google_work_agent.domain import ActionStatus, ResultCode
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
    UnitOfWork,
)


class _RecordedCall:
    def __init__(
        self,
        *,
        name: str,
        calls: list[str],
        result: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self._name = name
        self._calls = calls
        self._result = result
        self._error = error

    def __call__(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self._calls.append(self._name)
        if self._error is not None:
            raise self._error
        return self._result


def test_successful_write_phase_preserves_call_trajectory() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls=calls)

    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )

    assert result.disposition is WriteExecutionDisposition.VERIFIED
    assert result.action_status == ActionStatus.VERIFIED.value
    assert calls == ["preflight", "claim", "execute", "store", "verify"]


def test_uncertain_delivery_marks_unknown_without_blind_resend() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        execute_error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.TIMEOUT,
            message="response uncertain",
            delivered=True,
            mutated=False,
        ),
    )

    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )

    assert result.disposition is WriteExecutionDisposition.UNKNOWN_RESULT
    assert calls == ["preflight", "claim", "execute", "mark_unknown"]


def _coordinator(
    *,
    calls: list[str],
    execute_error: Exception | None = None,
) -> WriteExecutionPhaseCoordinator:
    claim = _response(
        status=ActionStatus.EXECUTING.value,
        version=2,
        attempt_id="attempt-1",
        claim_token="claim-token",
    )
    stored = _response(
        status=ActionStatus.EXECUTED.value,
        version=3,
        attempt_id="attempt-1",
    )
    verified = _response(
        status=ActionStatus.VERIFIED.value,
        version=4,
        attempt_id="attempt-1",
    )
    unknown = _response(
        status=ActionStatus.UNKNOWN_RESULT.value,
        version=3,
        attempt_id="attempt-1",
    )
    snapshot = ResourceSnapshot(
        fixture_snapshot_id="snapshot-1",
        resource_type=ResourceType.TASK,
        resource_id="task-1",
        parent_id="list-1",
        related_resource_ids=("list-1",),
        version="1",
        recovery_fingerprint=None,
        payload={"title": "Task"},
    )
    unused = _RecordedCall(name="unexpected", calls=calls)
    return WriteExecutionPhaseCoordinator(
        unit_of_work_factory=cast(Callable[[], UnitOfWork], _unexpected_uow),
        id_factory=lambda: "generated-id",
        request_hash=lambda _payload: "request-hash",
        should_stop_for_cancel=lambda _run_id: False,
        preflight_write=cast(
            PreflightWriteActionService,
            _RecordedCall(name="preflight", calls=calls),
        ),
        claim_write=cast(
            ClaimWriteActionService,
            _RecordedCall(name="claim", calls=calls, result=claim),
        ),
        execute_write=cast(
            ExecuteWriteActionService,
            _RecordedCall(
                name="execute",
                calls=calls,
                result=ExecutedWriteActionResult(snapshot=snapshot, response_metadata_json="{}"),
                error=execute_error,
            ),
        ),
        store_write_success=cast(
            StoreWriteActionSuccessService,
            _RecordedCall(name="store", calls=calls, result=stored),
        ),
        verify_write=cast(
            VerifyWriteActionService,
            _RecordedCall(name="verify", calls=calls, result=verified),
        ),
        mark_write_failed=cast(MarkWriteActionFailedService, unused),
        mark_write_unknown=cast(
            MarkWriteActionUnknownResultService,
            _RecordedCall(name="mark_unknown", calls=calls, result=unknown),
        ),
        require_write_reauth=cast(RequireWriteReauthService, unused),
        recover_unknown_create=cast(RecoverUnknownCreateActionService, unused),
        recover_unknown_send=cast(RecoverUnknownSendActionService, unused),
        recover_unknown_delete=cast(RecoverUnknownDeleteActionService, unused),
        recover_unknown_update=cast(RecoverUnknownUpdateActionService, unused),
    )


def _response(
    *,
    status: str,
    version: int,
    attempt_id: str,
    claim_token: str | None = None,
) -> WriteActionResponse:
    return WriteActionResponse(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED.value,
        action_id="action-1",
        action_status=status,
        action_version=version,
        next_allowed_commands=(),
        attempt_id=attempt_id,
        claim_token=claim_token,
    )


def _unexpected_uow() -> UnitOfWork:
    raise AssertionError("unit of work was not expected")
