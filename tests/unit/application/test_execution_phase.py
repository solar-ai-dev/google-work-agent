from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.application.execution_phase import (
    UnknownRecoveryPhaseRequest,
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
    WriteRunResponse,
)
from google_work_agent.domain import ActionStatus, CommandResult, ResultCode, RunStatus
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
    assert calls == ["preflight", "claim", "execute", "store", "begin_verification", "verify"]


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
    assert result.action_status == ActionStatus.UNKNOWN_RESULT.value
    assert calls == ["preflight", "claim", "execute", "mark_unknown"]


def test_not_sent_failure_does_not_begin_verification() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        execute_error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.TIMEOUT,
            message="write was not sent",
            delivered=False,
            mutated=False,
        ),
    )
    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )
    assert result.disposition is WriteExecutionDisposition.FAILED
    assert result.action_status == ActionStatus.FAILED.value
    assert calls == ["preflight", "claim", "execute", "mark_failed"]


def test_auth_failure_not_sent_marks_failed_before_reauth() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        execute_error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            message="auth failed before provider dispatch",
            delivered=False,
            mutated=False,
        ),
    )
    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )
    assert result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED
    assert result.action_status == ActionStatus.FAILED.value
    assert calls == ["preflight", "claim", "execute", "mark_failed", "require_reauth"]
    assert calls.count("execute") == 1


def test_auth_failure_ambiguous_marks_unknown_before_reauth_and_never_resends() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        execute_error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            message="provider may have received write",
            delivered=True,
            mutated=False,
        ),
    )
    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )
    assert result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED
    assert result.action_status == ActionStatus.UNKNOWN_RESULT.value
    assert calls == ["preflight", "claim", "execute", "mark_unknown", "require_reauth"]
    assert calls.count("execute") == 1


def test_claim_applied_false_reconciles_without_provider_write() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        claim_response=_response(
            status=ActionStatus.APPROVED.value,
            version=1,
            attempt_id=None,
            applied=False,
            result_code=ResultCode.STATE_CONFLICT.value,
        ),
    )
    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )
    assert result.disposition is WriteExecutionDisposition.DOMAIN_RECONCILE
    assert result.current_status == ActionStatus.APPROVED.value
    assert calls == ["preflight", "claim"]


def test_store_success_applied_false_reconciles_before_verification() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        store_response=_response(
            status=ActionStatus.EXECUTING.value,
            version=2,
            attempt_id="attempt-1",
            applied=False,
            result_code=ResultCode.VERSION_CONFLICT.value,
        ),
    )
    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )
    assert result.disposition is WriteExecutionDisposition.DOMAIN_RECONCILE
    assert calls == ["preflight", "claim", "execute", "store"]


def test_begin_verification_applied_false_reconciles_before_verification_read() -> None:
    calls: list[str] = []
    begin_result = CommandResult(
        applied=False,
        result_code=ResultCode.STATE_CONFLICT,
        current_status=RunStatus.REAUTH_REQUIRED,
        current_version=7,
        next_allowed_commands=(),
        conflict_detail="run moved",
    )
    coordinator = _coordinator(calls=calls, begin_verification_result=begin_result)
    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )
    assert result.disposition is WriteExecutionDisposition.DOMAIN_RECONCILE
    assert result.current_status == RunStatus.REAUTH_REQUIRED.value
    assert calls == ["preflight", "claim", "execute", "store", "begin_verification"]


def test_verification_credential_loss_routes_to_reauth_without_marking_write_failed() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        verify_error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            message="credential expired during verification",
            delivered=True,
            mutated=False,
        ),
    )
    result = coordinator.execute(
        WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
    )
    assert result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED
    assert calls == [
        "preflight",
        "claim",
        "execute",
        "store",
        "begin_verification",
        "verify",
        "require_reauth",
    ]


def test_verification_non_reauth_gateway_error_still_propagates() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        verify_error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.UPSTREAM_5XX,
            message="verification GET failed",
            delivered=True,
            mutated=False,
        ),
    )
    try:
        coordinator.execute(
            WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)
        )
        raised = False
    except GoogleWorkspaceGatewayError:
        raised = True
    assert raised is True
    assert calls == ["preflight", "claim", "execute", "store", "begin_verification", "verify"]


def test_recover_unknown_credential_loss_routes_to_reauth_without_replaying_write() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        recover_unknown_create_error=GoogleWorkspaceGatewayError(
            code=GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            message="credential expired during recovery search",
            delivered=True,
            mutated=False,
        ),
    )
    result = coordinator.recover_unknown(
        UnknownRecoveryPhaseRequest(
            run_id="run-1",
            action_id="action-1",
            effect_type="CREATE",
            action_version=2,
            attempt_id="attempt-1",
            attempt_version=0,
        )
    )
    assert result.applied is False
    assert result.safe_error_code == "AUTH_EXPIRED"
    assert result.action_status == ActionStatus.UNKNOWN_RESULT.value
    assert result.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert calls == ["recover_unknown_create", "require_reauth"]
    assert "execute" not in calls


def _coordinator(
    *,
    calls: list[str],
    execute_error: Exception | None = None,
    verify_error: Exception | None = None,
    recover_unknown_create_error: Exception | None = None,
    claim_response: WriteActionResponse | None = None,
    store_response: WriteActionResponse | None = None,
    begin_verification_result: object | None = None,
) -> WriteExecutionPhaseCoordinator:
    claim = claim_response or _response(
        status=ActionStatus.EXECUTING.value,
        version=2,
        attempt_id="attempt-1",
        claim_token="claim-token",
    )
    stored = store_response or _response(
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
    failed = _response(
        status=ActionStatus.FAILED.value,
        version=3,
        attempt_id="attempt-1",
    )
    reauth = WriteRunResponse(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED.value,
        run_id="run-1",
        run_status=RunStatus.REAUTH_REQUIRED.value,
        run_version=8,
        plan_id="plan-1",
        plan_status="ACTIVE",
        result_kind="REAUTH_REQUIRED",
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
        preflight_write=cast(PreflightWriteActionService, _RecordedCall(name="preflight", calls=calls)),
        claim_write=cast(
            ClaimWriteActionService, _RecordedCall(name="claim", calls=calls, result=claim)
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
        begin_verification=cast(
            Callable[[str], object],
            _RecordedCall(
                name="begin_verification",
                calls=calls,
                result=begin_verification_result,
            ),
        ),
        verify_write=cast(
            VerifyWriteActionService,
            _RecordedCall(name="verify", calls=calls, result=verified, error=verify_error),
        ),
        mark_write_failed=cast(
            MarkWriteActionFailedService,
            _RecordedCall(name="mark_failed", calls=calls, result=failed),
        ),
        mark_write_unknown=cast(
            MarkWriteActionUnknownResultService,
            _RecordedCall(name="mark_unknown", calls=calls, result=unknown),
        ),
        require_write_reauth=cast(
            RequireWriteReauthService,
            _RecordedCall(name="require_reauth", calls=calls, result=reauth),
        ),
        recover_unknown_create=cast(
            RecoverUnknownCreateActionService,
            _RecordedCall(
                name="recover_unknown_create", calls=calls, error=recover_unknown_create_error
            )
            if recover_unknown_create_error is not None
            else unused,
        ),
        recover_unknown_send=cast(RecoverUnknownSendActionService, unused),
        recover_unknown_delete=cast(RecoverUnknownDeleteActionService, unused),
        recover_unknown_update=cast(RecoverUnknownUpdateActionService, unused),
    )


def _response(
    *,
    status: str,
    version: int,
    attempt_id: str | None,
    claim_token: str | None = None,
    applied: bool = True,
    result_code: str = ResultCode.TRANSITION_APPLIED.value,
) -> WriteActionResponse:
    return WriteActionResponse(
        applied=applied,
        result_code=result_code,
        action_id="action-1",
        action_status=status,
        action_version=version,
        next_allowed_commands=(),
        attempt_id=attempt_id,
        claim_token=claim_token,
    )


def _unexpected_uow() -> UnitOfWork:
    raise AssertionError("unit of work was not expected")
