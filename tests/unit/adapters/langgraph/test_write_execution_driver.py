"""Behavior tests for the LangGraph write execution structural driver."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from google_work_agent.adapters.langgraph.write_execution_driver import (
    UnknownRecoveryPhaseRequest,
    WriteExecutionDisposition,
    WriteExecutionPhaseRequest,
    WriteExecutionStructuralDriver,
)
from google_work_agent.application.use_cases.claim.build_claim_context import ClaimContextV2
from google_work_agent.application.use_cases.claim.claim_execution import ClaimExecutionResult
from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionResultV1,
)
from google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result import (
    ClassifyDispatchResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.connector_write_projection import (
    ConnectorWriteProjection,
)
from google_work_agent.application.use_cases.execution_attempt.write_dispatch_models import (
    PreparedWriteDispatch,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
    WriteRunResponse,
)
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultQueryV1,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    VerificationResultV1,
    VerifyEffectQueryV1,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
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
        self.invocations: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.invocations.append((args, kwargs))
        self._calls.append(self._name)
        if self._error is not None:
            raise self._error
        return self._result

    def refresh_stale_preflight(self, **_kwargs: object) -> None:
        return None

    def action_status(self, _action_id: str) -> str:
        return ActionStatusV1.EXECUTING.value

    def load_claimed_execution_input(self, **_kwargs: object) -> object:
        return SimpleNamespace(
            tool_name="tasks_create_task",
            arguments={"task_list_id": "list-1", "title": "Task"},
            recovery_fingerprint="recovery-fingerprint",
        )

    def project_persisted_query(self, **kwargs: object) -> object:
        if self._name == "lookup_unknown":
            return SimpleNamespace(
                query=LookupUnknownResultQueryV1(
                    run_id=str(kwargs["run_id"]),
                    action_id=str(kwargs["action_id"]),
                    execution_attempt_id=str(kwargs["execution_attempt_id"]),
                    effect=cast(Any, kwargs["effect"]),
                    recovery_fingerprint="recovery-fingerprint",
                    target_resource_ref=None,
                ),
                tool_name="tasks_create_task",
                arguments={"task_list_id": "list-1", "title": "Task"},
            )
        return VerifyEffectQueryV1(
            run_id=str(kwargs["run_id"]),
            action_id=str(kwargs["action_id"]),
            execution_attempt_id=str(kwargs["execution_attempt_id"]),
            effect="CREATE",
            expected_effect={"title": "Task"},
            target_resource_ref=None,
        )

    def run_id_for_action(self, _action_id: str) -> str:
        return "run-1"

    def current_run(self, _run_id: str) -> tuple[str, int]:
        return RunStatusV1.RECOVERY_REQUIRED.value, 4

    def has_current_context(self, _run_id: str) -> bool:
        return False

    def recovery_projection(self, **_kwargs: object) -> tuple[str, int]:
        return "CREATE", 1


class _Repository:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def get(self, identity: str) -> object | None:
        return self._values.get(identity)


class _UnitOfWork:
    def __init__(self) -> None:
        action = SimpleNamespace(
            id="action-1",
            plan_id="plan-1",
            status=ActionStatusV1.EXECUTING.value,
            version=2,
            tool_name="tasks_create_task",
            arguments_json='{"task_list_id":"list-1","title":"Task"}',
            arguments_hash="arguments-hash",
            expected_json='{"title":"Task"}',
            effect_type="CREATE",
            target_resource_ref_id=None,
        )
        approval = SimpleNamespace(
            id="approval-1",
            action_id="action-1",
            recovery_fingerprint="recovery-fingerprint",
        )
        attempt = SimpleNamespace(
            id="attempt-1",
            approval_id="approval-1",
            result_resource_ref_id=None,
            version=1,
        )
        self.actions = _Repository({"action-1": action})
        self.approvals = _Repository({"approval-1": approval})
        self.execution_attempts = _Repository({"attempt-1": attempt})
        self.resource_refs = _Repository({})
        self.runs = _Repository(
            {"run-1": SimpleNamespace(id="run-1", status=RunStatusV1.RECOVERY_REQUIRED, version=4)}
        )

    def __enter__(self) -> _UnitOfWork:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _ConnectorExecution:
    def __init__(
        self,
        *,
        calls: list[str],
        snapshot: ResourceSnapshot,
        execute_error: GoogleWorkspaceGatewayError | None,
    ) -> None:
        self._calls = calls
        self._snapshot = snapshot
        self._execute_error = execute_error

    def prepare_write(self, **kwargs: object) -> PreparedWriteDispatch:
        self._calls.append("prepare")
        return PreparedWriteDispatch(
            tool_name=str(kwargs["tool_name"]),
            arguments=cast(dict[str, object], kwargs["arguments"]),
        )

    def dispatch_write(self, _dispatch: object) -> ConnectorWriteResultV1:
        self._calls.append("dispatch")
        if self._execute_error is None:
            return ConnectorWriteResultV1(1, True, None, "provider-1", {}, None)
        error = self._execute_error
        error_code = (
            "AUTH_REQUIRED"
            if error.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
            else error.code.value
        )
        return ConnectorWriteResultV1(
            1,
            False,
            error.delivery_certainty.value,
            error.mcp_request_id,
            None,
            error_code,
        )

    def materialize_success(
        self, _dispatch: object, _result: ConnectorWriteResultV1
    ) -> ResourceSnapshot:
        self._calls.append("materialize")
        return self._snapshot

    def materialize_recovery_candidate(self, **_kwargs: object) -> ResourceSnapshot:
        self._calls.append("materialize_recovery")
        return self._snapshot


class _Classify:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self._handler = ClassifyDispatchResultHandler()

    def __call__(self, query: object) -> object:
        self._calls.append("classify")
        return self._handler(cast(Any, query))


def test_successful_write_phase_preserves_call_trajectory() -> None:
    calls: list[str] = []
    result = _coordinator(calls=calls).execute(_request())

    assert result.disposition is WriteExecutionDisposition.VERIFIED
    assert result.action_status == ActionStatusV1.VERIFIED.value
    assert calls == [
        "preflight",
        "claim",
        "prepare",
        "build_claim_context",
        "begin",
        "dispatch",
        "classify",
        "materialize",
        "store",
        "begin_verification",
        "verify_effect",
        "store_verification",
    ]


def test_preflight_commits_claim_without_preparing_or_dispatching_write() -> None:
    calls: list[str] = []
    coordinator = _coordinator(calls=calls)

    claim = coordinator.preflight(_request())

    assert claim.disposition is WriteExecutionDisposition.CLAIM_READY
    assert claim.attempt_id == "attempt-1"
    assert claim.approval_id == "approval-1"
    assert calls == ["preflight", "claim"]

    result = coordinator.execute_claimed(_request(), claim)
    assert result.disposition is WriteExecutionDisposition.EXECUTED
    assert calls[2:4] == ["prepare", "build_claim_context"]
    assert calls.count("dispatch") == 1
    assert "begin_verification" not in calls
    assert "verify_effect" not in calls


def test_fresh_preflight_source_snapshot_is_forwarded_to_claim() -> None:
    calls: list[str] = []
    source_snapshot = {
        "resource_type": "task",
        "resource_id": "task-1",
        "parent_id": "list-1",
        "version": "4",
    }
    claim_call = _RecordedCall(name="claim", calls=calls, result=_claim_result())

    result = _coordinator(
        calls=calls,
        preflight_result=source_snapshot,
        claim_call=claim_call,
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.VERIFIED
    assert claim_call.invocations[0][0][0].source_snapshot == source_snapshot


def test_uncertain_delivery_marks_unknown_without_blind_resend() -> None:
    calls: list[str] = []
    result = _coordinator(
        calls=calls,
        execute_error=_gateway_error(GoogleWorkspaceErrorCode.TIMEOUT, delivered=True),
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.UNKNOWN_RESULT
    assert result.action_status == ActionStatusV1.UNKNOWN_RESULT.value
    assert calls[-1] == "mark_unknown"
    assert calls.count("dispatch") == 1
    assert "store" not in calls


def test_classify_dispatch_result_decision_is_authoritative_over_local_rederivation() -> None:
    """Issue #131 / 020-02-W: classify_dispatch_result is the sole write-
    dispatch persistence-decision authority. The coordinator must not
    independently re-derive MARK_FAILED vs MARK_UNKNOWN_RESULT from the raw
    connector result; it must obey the already-computed decision, even when
    that decision disagrees with what a naive delivery-certainty re-check on
    the raw result would otherwise conclude.
    """
    calls: list[str] = []

    def classify_forces_failed(_query: object) -> object:
        calls.append("classify")
        # The connector result here is MAY_HAVE_BEEN_SENT (a real dispatch was
        # attempted), which a re-derivation from the raw result alone would
        # route to mark_unknown. classify_dispatch_result's decision must win.
        return SimpleNamespace(disposition="MARK_FAILED")

    result = _coordinator(
        calls=calls,
        execute_error=_gateway_error(GoogleWorkspaceErrorCode.TIMEOUT, delivered=True),
        classify_dispatch_result=classify_forces_failed,
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.FAILED
    assert calls[-1] == "mark_failed"
    assert "mark_unknown" not in calls


def test_not_sent_failure_does_not_begin_verification() -> None:
    calls: list[str] = []
    result = _coordinator(
        calls=calls,
        execute_error=_gateway_error(GoogleWorkspaceErrorCode.TIMEOUT, delivered=False),
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.FAILED
    assert result.action_status == ActionStatusV1.FAILED.value
    assert calls[-1] == "mark_failed"
    assert "begin_verification" not in calls


def test_begin_rejection_aborts_claimed_attempt_before_connector_dispatch() -> None:
    calls: list[str] = []
    result = _coordinator(
        calls=calls,
        begin_error=PermissionError("claim parent authority is no longer current"),
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.FAILED
    assert result.action_status == ActionStatusV1.FAILED.value
    assert calls == [
        "preflight",
        "claim",
        "prepare",
        "build_claim_context",
        "begin",
        "abort",
    ]
    assert "dispatch" not in calls


def test_auth_failure_not_sent_marks_failed_before_reauth() -> None:
    calls: list[str] = []
    result = _coordinator(
        calls=calls,
        execute_error=_gateway_error(GoogleWorkspaceErrorCode.AUTH_EXPIRED, delivered=False),
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED
    assert result.action_status == ActionStatusV1.FAILED.value
    assert calls[-2:] == ["mark_failed", "require_reauth"]
    assert calls.count("dispatch") == 1


def test_auth_failure_ambiguous_marks_unknown_before_reauth_and_never_resends() -> None:
    calls: list[str] = []
    result = _coordinator(
        calls=calls,
        execute_error=_gateway_error(GoogleWorkspaceErrorCode.AUTH_EXPIRED, delivered=True),
        lookup_error=_gateway_error(GoogleWorkspaceErrorCode.AUTH_EXPIRED, delivered=False),
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED
    assert result.action_status == ActionStatusV1.UNKNOWN_RESULT.value
    assert calls[-3:] == ["mark_unknown", "lookup_unknown", "require_reauth"]
    assert calls.count("dispatch") == 1


def test_claim_applied_false_reconciles_without_provider_write() -> None:
    calls: list[str] = []
    claim = _claim_result(
        applied=False,
        status=ActionStatusV1.APPROVED,
        version=1,
        attempt_id=None,
        approval_id=None,
        result_code=ResultCode.STATE_CONFLICT,
    )

    result = _coordinator(calls=calls, claim_response=claim).execute(_request())

    assert result.disposition is WriteExecutionDisposition.DOMAIN_RECONCILE
    assert result.current_status == ActionStatusV1.APPROVED.value
    assert calls == ["preflight", "claim"]


def test_store_success_applied_false_reconciles_before_verification() -> None:
    calls: list[str] = []
    result = _coordinator(
        calls=calls,
        store_response=_action_response(
            ActionStatusV1.EXECUTING.value,
            2,
            applied=False,
            result_code=ResultCode.VERSION_CONFLICT.value,
        ),
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.DOMAIN_RECONCILE
    assert calls[-1] == "store"
    assert "begin_verification" not in calls


def test_begin_verification_applied_false_reconciles_before_verification_read() -> None:
    calls: list[str] = []
    begin = SimpleNamespace(
        applied=False,
        result_code=ResultCode.STATE_CONFLICT,
        current_status=RunStatusV1.REAUTH_REQUIRED,
        current_version=7,
        next_allowed_commands=(),
    )

    result = _coordinator(calls=calls, begin_verification_result=begin).execute(_request())

    assert result.disposition is WriteExecutionDisposition.DOMAIN_RECONCILE
    assert result.current_status == RunStatusV1.REAUTH_REQUIRED.value
    assert calls[-1] == "begin_verification"
    assert "verify_effect" not in calls


def test_verification_credential_loss_routes_to_reauth_without_marking_write_failed() -> None:
    calls: list[str] = []
    result = _coordinator(
        calls=calls,
        verify_error=_gateway_error(GoogleWorkspaceErrorCode.AUTH_EXPIRED, delivered=True),
    ).execute(_request())

    assert result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED
    assert calls[-2:] == ["verify_effect", "require_reauth"]
    assert "mark_failed" not in calls


def test_verification_non_reauth_gateway_error_still_propagates() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        verify_error=_gateway_error(GoogleWorkspaceErrorCode.UPSTREAM_5XX, delivered=True),
    )

    try:
        coordinator.execute(_request())
        raised = False
    except GoogleWorkspaceGatewayError:
        raised = True

    assert raised is True
    assert calls[-1] == "verify_effect"


def test_recover_unknown_credential_loss_routes_to_reauth_without_replaying_write() -> None:
    calls: list[str] = []
    coordinator = _coordinator(
        calls=calls,
        lookup_error=_gateway_error(GoogleWorkspaceErrorCode.AUTH_EXPIRED, delivered=True),
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
    assert result.action_status == ActionStatusV1.UNKNOWN_RESULT.value
    assert result.result_code == ResultCode.RECOVERY_REQUIRED.value
    assert calls == ["lookup_unknown", "require_reauth"]
    assert "dispatch" not in calls


def _coordinator(
    *,
    calls: list[str],
    execute_error: GoogleWorkspaceGatewayError | None = None,
    verify_error: Exception | None = None,
    lookup_error: Exception | None = None,
    claim_response: ClaimExecutionResult | None = None,
    store_response: WriteActionResponse | None = None,
    begin_verification_result: object | None = None,
    preflight_result: object | None = None,
    claim_call: _RecordedCall | None = None,
    classify_dispatch_result: object | None = None,
    begin_error: Exception | None = None,
) -> WriteExecutionStructuralDriver:
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
    stored = store_response or _action_response(ActionStatusV1.EXECUTED.value, 3)
    verified = SimpleNamespace(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED.value,
        action_id="action-1",
        action_status=ActionStatusV1.VERIFIED.value,
        action_version=4,
        verification_id="verification-1",
        requires_recovery=False,
        conflict_detail=None,
    )
    reauth = WriteRunResponse(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED.value,
        run_id="run-1",
        run_status=RunStatusV1.REAUTH_REQUIRED.value,
        run_version=8,
        plan_id="plan-1",
        plan_status="ACTIVE",
        result_kind="REAUTH_REQUIRED",
    )
    return WriteExecutionStructuralDriver(
        id_factory=lambda: "generated-id",
        request_hash=lambda _payload: "request-hash",
        should_stop_for_cancel=lambda _run_id: False,
        preflight_write=cast(
            Any, _RecordedCall(name="preflight", calls=calls, result=preflight_result)
        ),
        claim_execution=cast(
            Any,
            claim_call
            or _RecordedCall(name="claim", calls=calls, result=claim_response or _claim_result()),
        ),
        build_claim_context=cast(
            Any,
            _RecordedCall(name="build_claim_context", calls=calls, result=_claim_context()),
        ),
        begin_execution_attempt=cast(
            Any,
            _RecordedCall(
                name="begin",
                calls=calls,
                result=SimpleNamespace(attempt=SimpleNamespace(version=1)),
                error=begin_error,
            ),
        ),
        abort_claimed_execution=cast(
            Any,
            _RecordedCall(
                name="abort",
                calls=calls,
                result=AbortClaimedExecutionResultV1(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED,
                    action_status=ActionStatusV1.FAILED,
                    action_version=3,
                    attempt_status=ExecutionAttemptStatusV1.FAILED,
                    attempt_version=1,
                ),
            ),
        ),
        connector_execution=cast(
            ConnectorWriteProjection,
            _ConnectorExecution(calls=calls, snapshot=snapshot, execute_error=execute_error),
        ),
        classify_dispatch_result=cast(Any, classify_dispatch_result or _Classify(calls)),
        store_write_success=cast(Any, _RecordedCall(name="store", calls=calls, result=stored)),
        begin_verification=cast(
            Any,
            _RecordedCall(name="begin_verification", calls=calls, result=begin_verification_result),
        ),
        verify_effect=cast(
            Any,
            _RecordedCall(
                name="verify_effect",
                calls=calls,
                result=VerificationResultV1(
                    "VERIFIED", "GET_COMPARE", {"title": "Task"}, {"title": "Task"}, [], []
                ),
                error=verify_error,
            ),
        ),
        store_verification=cast(
            Any,
            _RecordedCall(name="store_verification", calls=calls, result=verified),
        ),
        require_recovery=cast(Any, _RecordedCall(name="require_recovery", calls=calls)),
        resolve_recovery=cast(Any, _RecordedCall(name="resolve_recovery", calls=calls)),
        mark_write_failed=cast(
            Any,
            _RecordedCall(
                name="mark_failed",
                calls=calls,
                result=_action_response(ActionStatusV1.FAILED.value, 3),
            ),
        ),
        mark_write_unknown=cast(
            Any,
            _RecordedCall(
                name="mark_unknown",
                calls=calls,
                result=_action_response(ActionStatusV1.UNKNOWN_RESULT.value, 3),
            ),
        ),
        service_instance_id="service-1",
        mcp_process_instance_id=lambda: "mcp-1",
        require_write_reauth=cast(
            Any, _RecordedCall(name="require_reauth", calls=calls, result=reauth)
        ),
        lookup_unknown_result=cast(
            Any,
            _RecordedCall(name="lookup_unknown", calls=calls, error=lookup_error),
        ),
        recover_existing_result=cast(Any, _RecordedCall(name="recover_existing", calls=calls)),
        resolve_as_failed=cast(Any, _RecordedCall(name="resolve_as_failed", calls=calls)),
    )


def _request() -> WriteExecutionPhaseRequest:
    return WriteExecutionPhaseRequest(run_id="run-1", action_id="action-1", action_version=1)


def _claim_result(
    *,
    applied: bool = True,
    status: ActionStatusV1 = ActionStatusV1.EXECUTING,
    version: int = 2,
    attempt_id: str | None = "attempt-1",
    approval_id: str | None = "approval-1",
    result_code: ResultCode = ResultCode.TRANSITION_APPLIED,
) -> ClaimExecutionResult:
    return ClaimExecutionResult(
        applied=applied,
        result_code=result_code,
        action_id="action-1",
        current_status=status,
        current_version=version,
        next_allowed_commands=(),
        approval_id=approval_id,
        attempt_id=attempt_id,
    )


def _claim_context() -> ClaimContextV2:
    return ClaimContextV2(
        claim_version=2,
        service_instance_id="service-1",
        mcp_process_instance_id="mcp-1",
        action_id="action-1",
        approval_id="approval-1",
        execution_attempt_id="attempt-1",
        tool_name="tasks_create_task",
        approval_arguments_hash="arguments-hash",
        execution_arguments_hash="execution-hash",
        issued_at_ms=1,
        expires_at_ms=2,
        nonce="nonce-1",
        signature="signature-1",
    )


def _action_response(
    status: str,
    version: int,
    *,
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
        attempt_id="attempt-1",
    )


def _gateway_error(
    code: GoogleWorkspaceErrorCode, *, delivered: bool
) -> GoogleWorkspaceGatewayError:
    return GoogleWorkspaceGatewayError(
        code=code,
        message="connector failed",
        delivered=delivered,
        mutated=False,
    )
