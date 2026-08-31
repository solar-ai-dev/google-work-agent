"""Execution-attempt orchestration for deterministic write phases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from json import loads
from typing import Literal, cast

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionCommand,
    RefreshExpiredActionHandler,
)
from google_work_agent.application.use_cases.action.write_preflight import (
    PreflightWriteActionService,
)
from google_work_agent.application.use_cases.approval.expire_approval import (
    ExpireApprovalCommand,
    ExpireApprovalHandler,
)
from google_work_agent.application.use_cases.claim.build_claim_context import (
    BuildClaimContextHandler,
    BuildClaimContextQueryV1,
    claim_context_payload,
)
from google_work_agent.application.use_cases.claim.claim_execution import (
    ClaimExecutionCommand,
    ClaimExecutionHandler,
    ClaimExecutionResult,
)
from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionCommandV1,
    AbortClaimedExecutionHandler,
)
from google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt import (
    BeginExecutionAttemptCommand,
    BeginExecutionAttemptHandler,
)
from google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result import (
    ClassifyDispatchResultHandler,
    ClassifyDispatchResultQueryV1,
)
from google_work_agent.application.use_cases.execution_attempt.connector_write_projection import (
    ConnectorWriteProjection,
)
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteResultV1,
)
from google_work_agent.application.use_cases.execution_attempt.mark_failed import (
    MarkFailedCommand,
    MarkFailedHandler,
    MarkFailedResult,
)
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultCommand,
    MarkUnknownResultHandler,
    MarkUnknownResultResult,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultCommand,
    RecoverExistingResultHandler,
    RecoverExistingResultResult,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedCommand,
    ResolveAsFailedHandler,
    ResolveAsFailedResult,
)
from google_work_agent.application.use_cases.execution_attempt.store_success import (
    StoreSuccessCommand,
    StoreSuccessHandler,
    StoreSuccessResult,
)
from google_work_agent.application.use_cases.execution_attempt.write_dispatch_models import (
    AuthorizedWriteDispatch,
    PreparedWriteDispatch,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    ExecutedWriteActionResult,
    WriteActionResponse,
    WriteRunResponse,
)
from google_work_agent.application.use_cases.plan.persistence_projection import load_plan_record
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
    LookupUnknownResultQueryV1,
    UnknownResultLookupResultV1,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
    RequireRecoveryResult,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommandV1,
    ResolveRecoveryHandler,
)
from google_work_agent.application.use_cases.resource_ref.resolve_resource_ref import (
    ResolveResourceRefHandler,
    ResolveResourceRefQuery,
)
from google_work_agent.application.use_cases.run.begin_verification import (
    BeginVerificationCommand,
    BeginVerificationHandler,
)
from google_work_agent.application.use_cases.run.require_reauth import (
    RequireReauthCommand,
    RequireReauthHandler,
)
from google_work_agent.application.use_cases.verification.store_verification import (
    StoreVerificationCommand,
    StoreVerificationHandler,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    SelectedResourceRefV1,
    VerifyEffectHandler,
    VerifyEffectQueryV1,
)
from google_work_agent.domain.action.model import ActionStatusV1, PolicyViolationError
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.recovery.model import RecoveryResolution
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class WriteExecutionDisposition(StrEnum):
    CLAIM_READY = "CLAIM_READY"
    PREFLIGHT_REAPPROVAL_REQUIRED = "PREFLIGHT_REAPPROVAL_REQUIRED"
    PREFLIGHT_BLOCKED = "PREFLIGHT_BLOCKED"
    DOMAIN_RECONCILE = "DOMAIN_RECONCILE"
    CLAIM_SKIPPED = "CLAIM_SKIPPED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    FAILED = "FAILED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True, slots=True)
class WriteExecutionPhaseRequest:
    run_id: str
    action_id: str
    action_version: int


@dataclass(frozen=True, slots=True)
class WriteExecutionPhaseResult:
    disposition: WriteExecutionDisposition
    action_status: str | None = None
    result_code: str | None = None
    safe_error_code: str | None = None
    current_status: str | None = None
    current_version: int | None = None
    next_allowed_commands: tuple[str, ...] = ()
    attempt_id: str | None = None
    approval_id: str | None = None
    claimed_action_version: int | None = None
    delivery_certainty: str | None = None
    verification_id: str | None = None


@dataclass(frozen=True, slots=True)
class UnknownRecoveryPhaseRequest:
    run_id: str
    action_id: str
    effect_type: str
    action_version: int
    attempt_id: str
    attempt_version: int


class WriteExecutionPhaseCoordinator:
    """Sequence write safety services and consume every mutation result."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        id_factory: Callable[[], str],
        request_hash: Callable[[dict[str, object]], str],
        should_stop_for_cancel: Callable[[str], bool],
        preflight_write: PreflightWriteActionService,
        expire_approval: ExpireApprovalHandler | None,
        refresh_expired_action: RefreshExpiredActionHandler | None,
        claim_execution: ClaimExecutionHandler,
        build_claim_context: BuildClaimContextHandler,
        begin_execution_attempt: BeginExecutionAttemptHandler,
        abort_claimed_execution: AbortClaimedExecutionHandler,
        connector_execution: ConnectorWriteProjection,
        classify_dispatch_result: ClassifyDispatchResultHandler,
        store_write_success: StoreSuccessHandler,
        begin_verification: BeginVerificationHandler,
        verify_effect: VerifyEffectHandler,
        store_verification: StoreVerificationHandler,
        require_recovery: RequireRecoveryHandler,
        resolve_recovery: ResolveRecoveryHandler,
        mark_write_failed: MarkFailedHandler,
        mark_write_unknown: MarkUnknownResultHandler,
        service_instance_id: str,
        mcp_process_instance_id: Callable[[], str],
        require_write_reauth: RequireReauthHandler,
        lookup_unknown_result: LookupUnknownResultHandler,
        recover_existing_result: RecoverExistingResultHandler,
        resolve_as_failed: ResolveAsFailedHandler,
        resolve_resource_ref: ResolveResourceRefHandler,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._id_factory = id_factory
        self._request_hash = request_hash
        self._should_stop_for_cancel = should_stop_for_cancel
        self._preflight_write = preflight_write
        self._expire_approval = expire_approval
        self._refresh_expired_action = refresh_expired_action
        self._claim_execution = claim_execution
        self._build_claim_context = build_claim_context
        self._begin_execution_attempt = begin_execution_attempt
        self._abort_claimed_execution = abort_claimed_execution
        self._connector_execution = connector_execution
        self._classify_dispatch_result = classify_dispatch_result
        self._store_write_success = store_write_success
        self._begin_verification = begin_verification
        self._verify_effect = verify_effect
        self._store_verification = store_verification
        self._require_recovery = require_recovery
        self._resolve_recovery = resolve_recovery
        self._mark_write_failed = mark_write_failed
        self._mark_write_unknown = mark_write_unknown
        self._service_instance_id = service_instance_id
        self._mcp_process_instance_id = mcp_process_instance_id
        self._require_write_reauth = require_write_reauth
        self._lookup_unknown_result = lookup_unknown_result
        self._recover_existing_result = recover_existing_result
        self._resolve_as_failed = resolve_as_failed
        self._resolve_resource_ref = resolve_resource_ref

    def execute(self, request: WriteExecutionPhaseRequest) -> WriteExecutionPhaseResult:
        """Preserve the Application API while keeping preflight and write boundaries explicit."""

        claim = self.preflight(request)
        if claim.disposition is not WriteExecutionDisposition.CLAIM_READY:
            return claim
        executed = self.execute_claimed(request, claim)
        if executed.disposition is not WriteExecutionDisposition.EXECUTED:
            return executed
        assert executed.action_status is not None
        assert executed.current_version is not None
        assert executed.attempt_id is not None
        begin = self._begin_verification(
            BeginVerificationCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "begin_verification", "run_id": request.run_id}
                ),
                run_id=request.run_id,
            )
        )
        if begin is not None and not begin.applied:
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
                result_code=begin.result_code.value,
                current_status=begin.current_status.value,
                current_version=begin.current_version,
                next_allowed_commands=tuple(item.value for item in begin.next_allowed_commands),
            )
        try:
            verified = self._verify_and_store(
                run_id=request.run_id,
                action_id=request.action_id,
                action_version=executed.current_version,
                attempt_id=executed.attempt_id,
            )
        except GoogleWorkspaceGatewayError as error:
            return self._handle_verification_error(request=request, error=error)
        return WriteExecutionPhaseResult(
            disposition=(
                WriteExecutionDisposition.VERIFIED
                if verified.action_status == ActionStatusV1.VERIFIED.value
                else WriteExecutionDisposition.DOMAIN_RECONCILE
            ),
            action_status=verified.action_status,
            result_code=verified.result_code,
            current_status=verified.action_status,
            current_version=verified.action_version,
            next_allowed_commands=verified.next_allowed_commands,
            attempt_id=verified.attempt_id,
        )

    def preflight(self, request: WriteExecutionPhaseRequest) -> WriteExecutionPhaseResult:
        """Validate freshness and commit Claim without performing connector I/O."""

        try:
            source_snapshot = self._preflight_write(action_id=request.action_id) or {}
        except (GoogleWorkspaceGatewayError, LookupError, PolicyViolationError) as error:
            if isinstance(error, GoogleWorkspaceGatewayError) and self._is_auth_error(error):
                reauth = self._require_reauth(request=request, error=error, kind="preflight_reauth")
                if not reauth.applied:
                    return self._reconcile_run_response(reauth)
                return WriteExecutionPhaseResult(
                    disposition=WriteExecutionDisposition.REAUTH_REQUIRED,
                    safe_error_code=error.code.value,
                    current_status=reauth.run_status,
                    current_version=reauth.run_version,
                )
            if self._action_status(request.action_id) == ActionStatusV1.MODIFIED.value:
                return WriteExecutionPhaseResult(
                    disposition=WriteExecutionDisposition.PREFLIGHT_REAPPROVAL_REQUIRED,
                )
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.PREFLIGHT_BLOCKED,
                safe_error_code=type(error).__name__,
            )

        if self._should_stop_for_cancel(request.run_id):
            return WriteExecutionPhaseResult(disposition=WriteExecutionDisposition.CANCEL_REQUESTED)

        claimed = self._claim_execution(
            ClaimExecutionCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "claim", "action_id": request.action_id}),
                action_id=request.action_id,
                expected_version=request.action_version,
                source_snapshot=source_snapshot,
                attempt_id=self._id_factory(),
            )
        )
        if not claimed.applied:
            if (
                claimed.conflict_detail
                in {
                    "approval expired",
                    "approval action version is stale",
                    "approval arguments binding is stale",
                    "approval source snapshot is stale",
                    "approval policy version is stale",
                    "approval tool schema version is stale",
                }
                and claimed.approval_id is not None
                and self._expire_approval is not None
            ):
                with self._unit_of_work_factory() as unit_of_work:
                    approval = unit_of_work.approvals.get(claimed.approval_id)
                    current_action = unit_of_work.actions.get(claimed.action_id)
                if approval is None or current_action is None:
                    raise LookupError("stale approval authority disappeared")
                entry = load_signed_tool_registry().get_required(
                    current_action.connector_id, current_action.tool_name
                )
                current_source_snapshot = (
                    source_snapshot
                    if claimed.conflict_detail == "approval source snapshot is stale"
                    else cast(dict[str, object], loads(approval.source_snapshot_json))
                )
                current_source_snapshot_hash = calculate_canonical_json_hash(
                    current_source_snapshot
                )
                expire_request = {
                    "approval_id": claimed.approval_id,
                    "expected_action_version": claimed.current_version,
                    "current_source_snapshot": current_source_snapshot,
                }
                expired = self._expire_approval(
                    ExpireApprovalCommand(
                        command_id=f"system:expire-approval:{claimed.approval_id}",
                        request_hash=calculate_canonical_json_hash(expire_request),
                        approval_id=claimed.approval_id,
                        expected_action_version=claimed.current_version,
                        current_source_snapshot=current_source_snapshot,
                    )
                )
                if expired.applied and self._refresh_expired_action is not None:
                    refresh_request = {
                        "action_id": claimed.action_id,
                        "expected_version": expired.action_version,
                        "fresh_source_snapshot": current_source_snapshot,
                        "fresh_source_snapshot_hash": current_source_snapshot_hash,
                        "fresh_policy_version": entry.registry_version,
                        "fresh_tool_schema_version": entry.input_schema_version,
                        "fresh_risk": current_action.risk,
                    }
                    refreshed = self._refresh_expired_action(
                        RefreshExpiredActionCommand(
                            command_id=f"system:refresh-expired-action:{claimed.action_id}",
                            request_hash=calculate_canonical_json_hash(refresh_request),
                            action_id=claimed.action_id,
                            expected_version=expired.action_version,
                            fresh_source_snapshot=current_source_snapshot,
                            fresh_source_snapshot_hash=current_source_snapshot_hash,
                            fresh_policy_version=entry.registry_version,
                            fresh_tool_schema_version=entry.input_schema_version,
                            fresh_risk=current_action.risk,
                        )
                    )
                    return WriteExecutionPhaseResult(
                        disposition=WriteExecutionDisposition.PREFLIGHT_REAPPROVAL_REQUIRED,
                        action_status=refreshed.action_status,
                        result_code=refreshed.result_code,
                        current_status=refreshed.action_status,
                        current_version=refreshed.action_version,
                    )
                return WriteExecutionPhaseResult(
                    disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
                    action_status=expired.action_status,
                    result_code=expired.result_code,
                    current_status=expired.action_status,
                    current_version=expired.action_version,
                )
            return self._reconcile_claim_response(claimed)
        if claimed.attempt_id is None or claimed.approval_id is None:
            return self._claim_authority_missing(claimed)

        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.CLAIM_READY,
            action_status=claimed.current_status.value,
            result_code=claimed.result_code.value,
            current_status=claimed.current_status.value,
            current_version=claimed.current_version,
            next_allowed_commands=tuple(command.value for command in claimed.next_allowed_commands),
            attempt_id=claimed.attempt_id,
            approval_id=claimed.approval_id,
            claimed_action_version=claimed.current_version,
        )

    def execute_claimed(
        self,
        request: WriteExecutionPhaseRequest,
        claim: WriteExecutionPhaseResult,
    ) -> WriteExecutionPhaseResult:
        """Execute only a claim that PREFLIGHT committed and projected."""

        if (
            claim.disposition is not WriteExecutionDisposition.CLAIM_READY
            or claim.attempt_id is None
            or claim.approval_id is None
            or claim.claimed_action_version is None
        ):
            raise ValueError("execute_claimed requires a complete CLAIM_READY projection")

        attempt_id = claim.attempt_id
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(request.action_id)
            approval = unit_of_work.approvals.get(claim.approval_id)
        if action is None or approval is None:
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
                result_code=ResultCode.STATE_CONFLICT.value,
                current_version=claim.claimed_action_version,
            )
        try:
            prepared = self._connector_execution.prepare_write(
                tool_name=action.tool_name,
                arguments=cast(dict[str, object], loads(action.arguments_json)),
                recovery_fingerprint=approval.recovery_fingerprint,
            )
            claim_context = self._build_claim_context(
                BuildClaimContextQueryV1(
                    schema_version=1,
                    action_id=action.id,
                    approval_id=approval.id,
                    execution_attempt_id=attempt_id,
                    tool_name=action.tool_name,
                    approval_arguments_hash=action.arguments_hash,
                    final_tool_arguments=prepared.arguments,
                    service_instance_id=self._service_instance_id,
                    mcp_process_instance_id=self._mcp_process_instance_id(),
                )
            )
            claim_payload = claim_context_payload(claim_context)
        except (
            GoogleWorkspaceGatewayError,
            LookupError,
            PermissionError,
            RuntimeError,
            ValueError,
        ) as error:
            return self._abort_before_dispatch(
                request=request,
                claim=claim,
                error=error,
            )
        if self._should_stop_for_cancel(request.run_id):
            abort_payload = {
                "action_id": request.action_id,
                "attempt_id": attempt_id,
                "expected_action_version": claim.claimed_action_version,
                "expected_attempt_version": 0,
                "error_code": "CANCEL_REQUESTED",
                "error_detail": "write was not sent because cancellation was requested",
            }
            aborted = self._abort_claimed_execution(
                AbortClaimedExecutionCommandV1(
                    command_id=self._id_factory(),
                    request_hash=calculate_canonical_json_hash(abort_payload),
                    action_id=request.action_id,
                    attempt_id=attempt_id,
                    expected_action_version=claim.claimed_action_version,
                    expected_attempt_version=0,
                    error_code="CANCEL_REQUESTED",
                    error_detail="write was not sent because cancellation was requested",
                )
            )
            return WriteExecutionPhaseResult(
                disposition=(
                    WriteExecutionDisposition.CANCEL_REQUESTED
                    if aborted.applied
                    else WriteExecutionDisposition.DOMAIN_RECONCILE
                ),
                action_status=aborted.action_status.value,
                result_code=aborted.result_code.value,
                current_status=aborted.action_status.value,
                current_version=aborted.action_version,
            )

        try:
            begun = self._begin_execution_attempt(
                BeginExecutionAttemptCommand(
                    command_id=f"begin-execution-attempt:{attempt_id}",
                    request_hash=calculate_canonical_json_hash(claim_payload),
                    action_id=request.action_id,
                    claim_payload=claim_payload,
                )
            )
        except (LookupError, PermissionError, RuntimeError, ValueError) as error:
            return self._abort_before_dispatch(
                request=request,
                claim=claim,
                error=error,
            )
        dispatch = AuthorizedWriteDispatch(
            prepared=PreparedWriteDispatch(action.tool_name, prepared.arguments),
            claim_context=claim_context,
        )
        try:
            dispatch_result = self._connector_execution.dispatch_write(dispatch)
            connector_result = dispatch_result
            decision = self._classify_dispatch_result(
                ClassifyDispatchResultQueryV1(
                    schema_version=1,
                    dispatch_result=DispatchConnectorWriteResultV1(dispatch_result),
                )
            )
        except PermissionError as error:
            # No connector call was made (eligibility rejected before dispatch),
            # so no classify_dispatch_result decision exists here; NOT_SENT is
            # the only legal certainty for a call that never happened.
            connector_error = GoogleWorkspaceGatewayError(
                code=GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
                message=str(error),
                delivered=False,
                mutated=False,
            )
            return self._handle_execution_error(
                request=request,
                attempt_id=attempt_id,
                claimed_action_version=claim.claimed_action_version,
                error=connector_error,
                mark_as_failed=True,
            )
        if decision.disposition != "STORE_SUCCESS":
            # `classify_dispatch_result` is the sole write-dispatch persistence
            # decision authority; reuse its decision instead of re-deriving a
            # competing MARK_FAILED/MARK_UNKNOWN_RESULT choice here.
            connector_error = self._dispatch_error(connector_result)
            return self._handle_execution_error(
                request=request,
                attempt_id=attempt_id,
                claimed_action_version=claim.claimed_action_version,
                error=connector_error,
                mark_as_failed=decision.disposition == "MARK_FAILED",
            )
        executed = ExecutedWriteActionResult(
            snapshot=self._connector_execution.materialize_success(dispatch, connector_result),
            response_metadata_json="{}",
        )

        stored = self._store_write_success(
            StoreSuccessCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "store_success", "action_id": request.action_id}
                ),
                action_id=request.action_id,
                attempt_id=attempt_id,
                expected_action_version=claim.claimed_action_version,
                expected_attempt_version=begun.attempt.version,
                snapshot=executed.snapshot,
            )
        )
        if not stored.applied:
            return self._reconcile_action_response(stored)
        if not isinstance(stored.attempt_id, str) or not stored.attempt_id:
            return self._reconcile_action_response(
                WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=stored.action_id,
                    action_status=stored.action_status,
                    action_version=stored.action_version,
                    next_allowed_commands=stored.next_allowed_commands,
                    conflict_detail="stored success is missing attempt identity",
                )
            )

        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.EXECUTED,
            action_status=stored.action_status,
            result_code=stored.result_code,
            current_status=stored.action_status,
            current_version=stored.action_version,
            next_allowed_commands=stored.next_allowed_commands,
            attempt_id=stored.attempt_id,
        )

    def _abort_before_dispatch(
        self,
        *,
        request: WriteExecutionPhaseRequest,
        claim: WriteExecutionPhaseResult,
        error: Exception,
    ) -> WriteExecutionPhaseResult:
        """Settle a durable CLAIMED attempt when no dispatch authority was committed."""

        if claim.attempt_id is None or claim.claimed_action_version is None:
            raise ValueError("pre-dispatch abort requires the claimed Attempt projection")
        error_code = (
            error.code.value
            if isinstance(error, GoogleWorkspaceGatewayError)
            else "PRE_DISPATCH_REJECTED"
        )
        error_detail = str(error) or type(error).__name__
        payload = {
            "action_id": request.action_id,
            "attempt_id": claim.attempt_id,
            "expected_action_version": claim.claimed_action_version,
            "expected_attempt_version": 0,
            "error_code": error_code,
            "error_detail": error_detail,
        }
        aborted = self._abort_claimed_execution(
            AbortClaimedExecutionCommandV1(
                command_id=f"abort-before-dispatch:{claim.attempt_id}",
                request_hash=calculate_canonical_json_hash(payload),
                action_id=request.action_id,
                attempt_id=claim.attempt_id,
                expected_action_version=claim.claimed_action_version,
                expected_attempt_version=0,
                error_code=error_code,
                error_detail=error_detail,
            )
        )
        if not aborted.applied:
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
                action_status=aborted.action_status.value,
                result_code=aborted.result_code.value,
                current_status=aborted.action_status.value,
                current_version=aborted.action_version,
                attempt_id=claim.attempt_id,
            )
        return WriteExecutionPhaseResult(
            disposition=(
                WriteExecutionDisposition.CANCEL_REQUESTED
                if aborted.action_status is ActionStatusV1.CANCELLED
                else WriteExecutionDisposition.FAILED
            ),
            action_status=aborted.action_status.value,
            result_code=aborted.result_code.value,
            safe_error_code=error_code,
            current_status=aborted.action_status.value,
            current_version=aborted.action_version,
            attempt_id=claim.attempt_id,
        )

    def recover_unknown(
        self,
        request: UnknownRecoveryPhaseRequest,
        *,
        allow_reauth: bool = True,
    ) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(request.action_id)
            attempt = unit_of_work.execution_attempts.get(request.attempt_id)
            if action is None or attempt is None:
                raise LookupError("unknown-result Action/Attempt binding is missing")
            approval = unit_of_work.approvals.get(attempt.approval_id)
            resource_ref = (
                None
                if action.target_resource_ref_id is None
                else unit_of_work.resource_refs.get(action.target_resource_ref_id)
            )
        if approval is None:
            raise LookupError("unknown-result Approval binding is missing")
        action_arguments = cast(dict[str, object], loads(action.arguments_json))
        target = (
            self._create_recovery_search_scope(action.tool_name, action_arguments)
            if resource_ref is None
            else SelectedResourceRefV1(
                schema_version=1,
                resource_ref_id=resource_ref.id,
                connector_id=resource_ref.connector_id,
                resource_type=resource_ref.resource_type,
                resource_id=resource_ref.resource_id,
                parent_resource_id=resource_ref.parent_resource_id,
            )
        )
        try:
            lookup = self._lookup_unknown_result(
                LookupUnknownResultQueryV1(
                    run_id=request.run_id,
                    action_id=request.action_id,
                    execution_attempt_id=request.attempt_id,
                    effect=cast(Literal["CREATE", "UPDATE", "DELETE", "SEND"], request.effect_type),
                    recovery_fingerprint=approval.recovery_fingerprint,
                    target_resource_ref=target,
                )
            )
        except GoogleWorkspaceGatewayError as error:
            if not self._is_auth_error(error):
                raise
            self._ensure_unknown_recovery(request, approval.recovery_fingerprint)
            if allow_reauth:
                self._require_reauth(request=request, error=error, kind="recover_unknown_reauth")
            return WriteActionResponse(
                applied=False,
                result_code=ResultCode.RECOVERY_REQUIRED.value,
                action_id=request.action_id,
                action_status=ActionStatusV1.UNKNOWN_RESULT.value,
                action_version=request.action_version,
                next_allowed_commands=(),
                attempt_id=request.attempt_id,
                safe_error_code=error.code.value,
            )
        if lookup.disposition == "MUTATION_FOUND":
            if len(lookup.candidate_resource_refs) != 1:
                raise RuntimeError("MUTATION_FOUND requires exactly one candidate")
            snapshot = self._connector_execution.materialize_recovery_candidate(
                tool_name=action.tool_name,
                arguments=action_arguments,
                resource_id=lookup.candidate_resource_refs[0],
            )
            command_id = self._id_factory()
            recovered = self._recover_existing_result(
                RecoverExistingResultCommand(
                    command_id=command_id,
                    request_hash=calculate_canonical_json_hash(
                        {
                            "command_id": command_id,
                            "action_id": request.action_id,
                            "attempt_id": request.attempt_id,
                            "candidate": lookup.candidate_resource_refs[0],
                        }
                    ),
                    action_id=request.action_id,
                    attempt_id=request.attempt_id,
                    expected_action_version=request.action_version,
                    expected_attempt_version=request.attempt_version,
                    snapshot=snapshot,
                )
            )
            if not recovered.applied:
                return self._as_write_response(recovered)
            resolved, continuation_staged = self._resolve_unknown_recovery(
                request=request,
                recovered_status=ActionStatusV1.EXECUTED,
                lookup=lookup,
            )
            del resolved, continuation_staged
            return self._as_write_response(recovered)
        if lookup.disposition == "MUTATION_NOT_FOUND":
            command_id = self._id_factory()
            failed = self._resolve_as_failed(
                ResolveAsFailedCommand(
                    command_id=command_id,
                    request_hash=calculate_canonical_json_hash(
                        {
                            "command_id": command_id,
                            "action_id": request.action_id,
                            "attempt_id": request.attempt_id,
                            "reason_codes": lookup.reason_codes,
                        }
                    ),
                    action_id=request.action_id,
                    attempt_id=request.attempt_id,
                    expected_action_version=request.action_version,
                    expected_attempt_version=request.attempt_version,
                    error_code="RECOVERY_CONFIRMED_NOT_EXECUTED",
                    error_detail=",".join(lookup.reason_codes),
                )
            )
            if failed.applied:
                self._resolve_unknown_recovery(
                    request=request,
                    recovered_status=ActionStatusV1.FAILED,
                    lookup=lookup,
                )
            return self._as_write_response(failed)
        recovery = self._ensure_unknown_recovery(request, approval.recovery_fingerprint)
        if recovery is not None and not recovery.applied:
            return WriteActionResponse(
                applied=False,
                result_code=recovery.result_code,
                action_id=request.action_id,
                action_status=ActionStatusV1.UNKNOWN_RESULT.value,
                action_version=request.action_version,
                next_allowed_commands=(),
                attempt_id=request.attempt_id,
                conflict_detail=recovery.conflict_detail,
            )
        return WriteActionResponse(
            applied=False,
            result_code=ResultCode.RECOVERY_REQUIRED.value,
            action_id=request.action_id,
            action_status=ActionStatusV1.UNKNOWN_RESULT.value,
            action_version=request.action_version,
            next_allowed_commands=(),
            attempt_id=request.attempt_id,
            conflict_detail=",".join(lookup.reason_codes),
        )

    @staticmethod
    def _create_recovery_search_scope(
        tool_name: str, arguments: dict[str, object]
    ) -> SelectedResourceRefV1 | None:
        if tool_name == "tasks_create_task":
            parent_id = arguments.get("task_list_id")
            resource_type = "task"
        elif tool_name == "calendar_create_event":
            parent_id = arguments.get("calendar_id")
            resource_type = "calendar_event"
        else:
            return None
        if not isinstance(parent_id, str) or not parent_id:
            raise ValueError("create recovery requires a container identity")
        return SelectedResourceRefV1(
            schema_version=1,
            resource_ref_id="recovery-search-scope",
            connector_id="google_workspace",
            resource_type=resource_type,
            resource_id="recovery-search-scope",
            parent_resource_id=parent_id,
        )

    def _resolve_unknown_recovery(
        self,
        *,
        request: UnknownRecoveryPhaseRequest,
        recovered_status: ActionStatusV1,
        lookup: UnknownResultLookupResultV1,
    ) -> tuple[bool, bool]:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(request.run_id)
            context = unit_of_work.recovery_contexts.load_current_context(request.run_id)
        if run is None:
            raise LookupError("unknown-result Run binding is missing")
        if context is None:
            if recovered_status is ActionStatusV1.FAILED:
                return True, False
            begin = self._begin_verification(
                BeginVerificationCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "begin_recovered_verification", "run_id": request.run_id}
                    ),
                    run_id=request.run_id,
                )
            )
            return begin is None or bool(begin.applied), False
        evidence_fingerprint = calculate_canonical_json_hash(
            {
                "disposition": lookup.disposition,
                "candidate_resource_refs": lookup.candidate_resource_refs,
                "evidence_refs": lookup.evidence_refs,
                "reason_codes": lookup.reason_codes,
            }
        )
        command_id = self._id_factory()
        result = self._resolve_recovery(
            ResolveRecoveryCommandV1(
                run_id=request.run_id,
                expected_version=run.version,
                command_id=command_id,
                request_hash=calculate_canonical_json_hash(
                    {
                        "command_id": command_id,
                        "resolution": RecoveryResolution.RECHECK.value,
                        "evidence_fingerprint": evidence_fingerprint,
                    }
                ),
                recovery_context_version=int(context["version"]),
                resolution=RecoveryResolution.RECHECK,
                target_kind=context["scope"],
                target_action_id=(
                    None if context.get("action_id") is None else str(context["action_id"])
                ),
            )
        )
        return bool(result.applied), bool(result.handoff_id)

    def _ensure_unknown_recovery(
        self, request: UnknownRecoveryPhaseRequest, recovery_fingerprint: str
    ) -> RequireRecoveryResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(request.run_id)
        if run is None:
            raise LookupError(f"run not found: {request.run_id}")
        if run.status is RunStatusV1.RECOVERY_REQUIRED:
            return None
        command_id = self._id_factory()
        return self._require_recovery(
            RequireRecoveryCommand(
                run_id=request.run_id,
                expected_version=run.version,
                command_id=command_id,
                request_hash=calculate_canonical_json_hash(
                    {
                        "command_id": command_id,
                        "reason": "UNKNOWN_RESULT",
                        "recovery_fingerprint": recovery_fingerprint,
                    }
                ),
                reason="UNKNOWN_RESULT",
                scope="ACTION",
                recovery_fingerprint=recovery_fingerprint,
                action_id=request.action_id,
                execution_attempt_id=request.attempt_id,
            )
        )

    @staticmethod
    def _as_write_response(
        result: RecoverExistingResultResult | ResolveAsFailedResult,
    ) -> WriteActionResponse:
        return WriteActionResponse(
            applied=result.applied,
            result_code=result.result_code,
            action_id=result.action_id,
            action_status=result.action_status,
            action_version=result.action_version,
            next_allowed_commands=result.next_allowed_commands,
            attempt_id=result.attempt_id,
            safe_error_code=result.safe_error_code,
            conflict_detail=result.conflict_detail,
        )

    def verify_executed(
        self,
        *,
        action_id: str,
        action_version: int,
        attempt_id: str,
        request_kind: str,
    ) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
            plan = None if action is None else load_plan_record(unit_of_work.plans, action.plan_id)
        if plan is None:
            raise LookupError(f"plan not found for action: {action_id}")
        del request_kind
        return self._verify_and_store(
            run_id=plan.run_id,
            action_id=action_id,
            action_version=action_version,
            attempt_id=attempt_id,
        )

    def handle_verification_error(
        self,
        *,
        request: WriteExecutionPhaseRequest,
        error: GoogleWorkspaceGatewayError,
    ) -> WriteExecutionPhaseResult:
        """Apply only the canonical auth pause for a technical verification failure."""

        return self._handle_verification_error(request=request, error=error)

    def _verify_and_store(
        self,
        *,
        run_id: str,
        action_id: str,
        action_version: int,
        attempt_id: str,
    ) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
            attempt = unit_of_work.execution_attempts.get(attempt_id)
            if action is None or attempt is None:
                raise LookupError("verification Action/Attempt binding is missing")
            approval = unit_of_work.approvals.get(attempt.approval_id)
            resource_ref_id = attempt.result_resource_ref_id or action.target_resource_ref_id
        resource_ref = (
            None
            if resource_ref_id is None
            else self._resolve_resource_ref(ResolveResourceRefQuery(resource_ref_id)).resource_ref
        )
        expected = cast(dict[str, object], loads(action.expected_json))
        if action.effect_type == "SEND" and approval is not None:
            expected = {**expected, "recovery_fingerprint": approval.recovery_fingerprint}
        target = (
            None
            if resource_ref is None
            else SelectedResourceRefV1(
                schema_version=1,
                resource_ref_id=resource_ref.id,
                connector_id=resource_ref.connector_id,
                resource_type=resource_ref.resource_type,
                resource_id=resource_ref.resource_id,
                parent_resource_id=resource_ref.parent_resource_id,
            )
        )
        observation = self._verify_effect(
            VerifyEffectQueryV1(
                run_id=run_id,
                action_id=action_id,
                execution_attempt_id=attempt_id,
                effect=cast(Literal["CREATE", "UPDATE", "DELETE", "SEND"], action.effect_type),
                expected_effect=expected,
                target_resource_ref=target,
            )
        )
        verification_id = self._id_factory()
        store_payload = {
            "verification_id": verification_id,
            "run_id": run_id,
            "action_id": action_id,
            "execution_attempt_id": attempt_id,
            "expected_action_version": action_version,
            "verification_status": observation.status,
        }
        stored = self._store_verification(
            StoreVerificationCommand(
                command_id=self._id_factory(),
                request_hash=calculate_canonical_json_hash(store_payload),
                verification_id=verification_id,
                run_id=run_id,
                action_id=action_id,
                execution_attempt_id=attempt_id,
                expected_action_version=action_version,
                verification=observation,
            )
        )
        if stored.applied and stored.requires_recovery:
            with self._unit_of_work_factory() as unit_of_work:
                run = unit_of_work.runs.get(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            recovery_fingerprint = calculate_canonical_json_hash(
                {
                    "expected": observation.expected_normalized,
                    "actual": observation.actual_normalized,
                    "reason_codes": observation.reason_codes,
                }
            )
            recovery_command_id = self._id_factory()
            recovery = self._require_recovery(
                RequireRecoveryCommand(
                    run_id=run_id,
                    expected_version=run.version,
                    command_id=recovery_command_id,
                    request_hash=calculate_canonical_json_hash(
                        {
                            "command_id": recovery_command_id,
                            "reason": "VERIFICATION_MISMATCH",
                            "recovery_fingerprint": recovery_fingerprint,
                        }
                    ),
                    reason="VERIFICATION_MISMATCH",
                    scope="ACTION",
                    recovery_fingerprint=recovery_fingerprint,
                    action_id=action_id,
                    execution_attempt_id=attempt_id,
                    verification_id=stored.verification_id,
                    observed_external_state_fingerprint=calculate_canonical_json_hash(
                        observation.actual_normalized
                    ),
                    verification_input_fingerprint=calculate_canonical_json_hash(
                        observation.expected_normalized
                    ),
                )
            )
            if not recovery.applied:
                return WriteActionResponse(
                    applied=False,
                    result_code=recovery.result_code,
                    action_id=stored.action_id,
                    action_status=stored.action_status,
                    action_version=stored.action_version,
                    next_allowed_commands=(),
                    attempt_id=attempt_id,
                    verification_id=stored.verification_id,
                    conflict_detail=recovery.conflict_detail,
                )
        return WriteActionResponse(
            applied=stored.applied,
            result_code=stored.result_code,
            action_id=stored.action_id,
            action_status=stored.action_status,
            action_version=stored.action_version,
            next_allowed_commands=(),
            attempt_id=attempt_id,
            verification_id=stored.verification_id,
            conflict_detail=stored.conflict_detail,
        )

    def _handle_execution_error(
        self,
        *,
        request: WriteExecutionPhaseRequest,
        attempt_id: str,
        claimed_action_version: int,
        error: GoogleWorkspaceGatewayError,
        mark_as_failed: bool,
    ) -> WriteExecutionPhaseResult:
        is_auth_error = self._is_auth_error(error)
        if mark_as_failed:
            failed = self._mark_write_failed(
                MarkFailedCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "failed", "action_id": request.action_id}
                    ),
                    action_id=request.action_id,
                    attempt_id=attempt_id,
                    expected_action_version=claimed_action_version,
                    expected_attempt_version=1,
                    delivery_certainty=DeliveryCertainty.NOT_SENT,
                    error_code=error.code.value,
                    error_detail=str(error),
                )
            )
            if not failed.applied:
                return self._reconcile_action_response(failed)
            if is_auth_error:
                reauth = self._require_reauth(request=request, error=error, kind="reauth_not_sent")
                if not reauth.applied:
                    return self._reconcile_run_response(reauth)
                return WriteExecutionPhaseResult(
                    disposition=WriteExecutionDisposition.REAUTH_REQUIRED,
                    action_status=failed.action_status,
                    result_code=failed.result_code,
                    safe_error_code=error.code.value,
                    current_status=failed.action_status,
                    current_version=failed.action_version,
                    next_allowed_commands=failed.next_allowed_commands,
                    attempt_id=attempt_id,
                    delivery_certainty=DeliveryCertainty.NOT_SENT.value,
                )
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.FAILED,
                action_status=failed.action_status,
                result_code=failed.result_code,
                safe_error_code=error.code.value,
                current_status=failed.action_status,
                current_version=failed.action_version,
                next_allowed_commands=failed.next_allowed_commands,
                attempt_id=attempt_id,
                delivery_certainty=DeliveryCertainty.NOT_SENT.value,
            )

        unknown = self._mark_write_unknown(
            MarkUnknownResultCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "unknown", "action_id": request.action_id}
                ),
                action_id=request.action_id,
                attempt_id=attempt_id,
                expected_action_version=claimed_action_version,
                expected_attempt_version=1,
                delivery_certainty=error.delivery_certainty,
                error_code=error.code.value,
                error_detail=str(error),
                mcp_request_id=error.mcp_request_id,
            )
        )
        if not unknown.applied:
            return self._reconcile_action_response(unknown)
        if is_auth_error:
            with self._unit_of_work_factory() as unit_of_work:
                attempt = unit_of_work.execution_attempts.get(attempt_id)
                action = unit_of_work.actions.get(request.action_id)
            if attempt is None or action is None:
                raise LookupError("unknown-result Action/Attempt binding is missing")
            recovered = self.recover_unknown(
                UnknownRecoveryPhaseRequest(
                    run_id=request.run_id,
                    action_id=request.action_id,
                    effect_type=action.effect_type,
                    action_version=unknown.action_version,
                    attempt_id=attempt_id,
                    attempt_version=attempt.version,
                )
            )
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.REAUTH_REQUIRED,
                action_status=recovered.action_status,
                result_code=recovered.result_code,
                safe_error_code=error.code.value,
                current_status=recovered.action_status,
                current_version=recovered.action_version,
                next_allowed_commands=recovered.next_allowed_commands,
                attempt_id=attempt_id,
                delivery_certainty=error.delivery_certainty.value,
            )
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.UNKNOWN_RESULT,
            action_status=unknown.action_status,
            result_code=unknown.result_code,
            safe_error_code=error.code.value,
            current_status=unknown.action_status,
            current_version=unknown.action_version,
            next_allowed_commands=unknown.next_allowed_commands,
            attempt_id=attempt_id,
            delivery_certainty=error.delivery_certainty.value,
        )

    def _handle_verification_error(
        self,
        *,
        request: WriteExecutionPhaseRequest,
        error: GoogleWorkspaceGatewayError,
    ) -> WriteExecutionPhaseResult:
        if self._is_auth_error(error):
            reauth = self._require_reauth(request=request, error=error, kind="verify_reauth")
            if not reauth.applied:
                return self._reconcile_run_response(reauth)
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.REAUTH_REQUIRED,
                safe_error_code=error.code.value,
                current_status=reauth.run_status,
                current_version=reauth.run_version,
            )
        raise error

    def _require_reauth(
        self,
        *,
        request: WriteExecutionPhaseRequest | UnknownRecoveryPhaseRequest,
        error: GoogleWorkspaceGatewayError,
        kind: str,
    ) -> WriteRunResponse:
        return self._require_write_reauth(
            RequireReauthCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": kind, "action_id": request.action_id}),
                run_id=request.run_id,
                expected_run_version=self._current_run_version(request.run_id),
                action_id=request.action_id,
                safe_error_code=error.code.value,
                mcp_request_id=error.mcp_request_id,
            )
        )

    def _current_run_version(self, run_id: str) -> int:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
        if run is None:
            raise LookupError(f"run not found: {run_id}")
        return run.version

    @staticmethod
    def _is_auth_error(error: GoogleWorkspaceGatewayError) -> bool:
        return error.code in {
            GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            GoogleWorkspaceErrorCode.PERMISSION_DENIED,
        }

    @staticmethod
    def _dispatch_error(result: ConnectorWriteResultV1) -> GoogleWorkspaceGatewayError:
        certainty = DeliveryCertainty(result.delivery_certainty or "MAY_HAVE_BEEN_SENT")
        code = {
            "AUTH_REQUIRED": GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            "PERMISSION_DENIED": GoogleWorkspaceErrorCode.PERMISSION_DENIED,
            "INVALID_ARGUMENT": GoogleWorkspaceErrorCode.INVALID_ARGUMENT,
            "NOT_FOUND": GoogleWorkspaceErrorCode.NOT_FOUND,
            "TIMEOUT": GoogleWorkspaceErrorCode.TIMEOUT,
        }.get(result.error_code or "", GoogleWorkspaceErrorCode.CONNECTION_CLOSED)
        return GoogleWorkspaceGatewayError(
            code=code,
            message=result.error_code or "CONNECTOR_WRITE_FAILED",
            delivered=certainty is not DeliveryCertainty.NOT_SENT,
            mutated=certainty is DeliveryCertainty.SENT_RESPONSE_LOST,
            mcp_request_id=result.provider_request_id,
        )

    @staticmethod
    def _reconcile_claim_response(response: ClaimExecutionResult) -> WriteExecutionPhaseResult:
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
            action_status=response.current_status.value,
            result_code=response.result_code.value,
            current_status=response.current_status.value,
            current_version=response.current_version,
            next_allowed_commands=tuple(item.value for item in response.next_allowed_commands),
        )

    @staticmethod
    def _claim_authority_missing(response: ClaimExecutionResult) -> WriteExecutionPhaseResult:
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
            action_status=response.current_status.value,
            result_code=ResultCode.STATE_CONFLICT.value,
            current_status=response.current_status.value,
            current_version=response.current_version,
        )

    @staticmethod
    def _reconcile_action_response(
        response: WriteActionResponse
        | StoreSuccessResult
        | MarkFailedResult
        | MarkUnknownResultResult,
    ) -> WriteExecutionPhaseResult:
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
            action_status=response.action_status,
            result_code=response.result_code,
            current_status=response.action_status,
            current_version=response.action_version,
            next_allowed_commands=response.next_allowed_commands,
            safe_error_code=getattr(response, "safe_error_code", None),
        )

    @staticmethod
    def _reconcile_run_response(response: WriteRunResponse) -> WriteExecutionPhaseResult:
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
            result_code=response.result_code,
            current_status=response.run_status,
            current_version=response.run_version,
            next_allowed_commands=(),
        )

    def _action_status(self, action_id: str) -> str | None:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
            return None if action is None else action.status
