"""Application orchestration for deterministic write execution phases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.application.write_actions import (
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    ExecuteWriteActionService,
    MarkWriteActionFailedCommand,
    MarkWriteActionFailedService,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    PreflightWriteActionService,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionCommand,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionCommand,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionCommand,
    RecoverUnknownUpdateActionService,
    RequireWriteReauthCommand,
    RequireWriteReauthService,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    WriteActionResponse,
)
from google_work_agent.domain.action.model import ActionStatus, PolicyViolationError
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import RunCommand, RunStatus
from google_work_agent.domain.run.transitions.begin_verification import (
    transition_begin_verification,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    UnitOfWork,
)


class WriteExecutionDisposition(StrEnum):
    PREFLIGHT_REAPPROVAL_REQUIRED = "PREFLIGHT_REAPPROVAL_REQUIRED"
    PREFLIGHT_BLOCKED = "PREFLIGHT_BLOCKED"
    DOMAIN_RECONCILE = "DOMAIN_RECONCILE"
    CLAIM_SKIPPED = "CLAIM_SKIPPED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    FAILED = "FAILED"
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


@dataclass(frozen=True, slots=True)
class UnknownRecoveryPhaseRequest:
    run_id: str
    action_id: str
    effect_type: str
    action_version: int
    attempt_id: str
    attempt_version: int


class BeginWriteVerificationService:
    """Apply BeginVerification and expose its CommandResult to the coordinator."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, run_id: str) -> CommandResult[RunStatus, RunCommand]:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            if run.status is RunStatus.VERIFYING:
                return CommandResult(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED,
                    current_status=run.status,
                    current_version=run.version,
                    next_allowed_commands=(),
                    conflict_detail=None,
                )
            next_status = transition_begin_verification(run.status)
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {"status": next_status.value, "version": run.version + 1},
            ):
                raise RuntimeError("validated BeginVerification CAS failed")
            unit_of_work.commit()
            return CommandResult(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED,
                current_status=next_status,
                current_version=run.version + 1,
                next_allowed_commands=(),
                conflict_detail=None,
            )


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
        claim_write: ClaimWriteActionService,
        execute_write: ExecuteWriteActionService,
        store_write_success: StoreWriteActionSuccessService,
        begin_verification: Callable[[str], CommandResult[RunStatus, RunCommand] | None],
        verify_write: VerifyWriteActionService,
        mark_write_failed: MarkWriteActionFailedService,
        mark_write_unknown: MarkWriteActionUnknownResultService,
        require_write_reauth: RequireWriteReauthService,
        recover_unknown_create: RecoverUnknownCreateActionService,
        recover_unknown_send: RecoverUnknownSendActionService,
        recover_unknown_delete: RecoverUnknownDeleteActionService,
        recover_unknown_update: RecoverUnknownUpdateActionService,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._id_factory = id_factory
        self._request_hash = request_hash
        self._should_stop_for_cancel = should_stop_for_cancel
        self._preflight_write = preflight_write
        self._claim_write = claim_write
        self._execute_write = execute_write
        self._store_write_success = store_write_success
        self._begin_verification = begin_verification
        self._verify_write = verify_write
        self._mark_write_failed = mark_write_failed
        self._mark_write_unknown = mark_write_unknown
        self._require_write_reauth = require_write_reauth
        self._recover_unknown_create = recover_unknown_create
        self._recover_unknown_send = recover_unknown_send
        self._recover_unknown_delete = recover_unknown_delete
        self._recover_unknown_update = recover_unknown_update

    def execute(self, request: WriteExecutionPhaseRequest) -> WriteExecutionPhaseResult:
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
            if self._action_status(request.action_id) == ActionStatus.MODIFIED.value:
                return WriteExecutionPhaseResult(
                    disposition=WriteExecutionDisposition.PREFLIGHT_REAPPROVAL_REQUIRED,
                )
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.PREFLIGHT_BLOCKED,
                safe_error_code=type(error).__name__,
            )

        if self._should_stop_for_cancel(request.run_id):
            return WriteExecutionPhaseResult(disposition=WriteExecutionDisposition.CANCEL_REQUESTED)

        claimed = self._claim_write(
            ClaimWriteActionCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "claim", "action_id": request.action_id}),
                action_id=request.action_id,
                expected_version=request.action_version,
                source_snapshot=source_snapshot,
                attempt_id=self._id_factory(),
                nonce=self._id_factory(),
            )
        )
        if not claimed.applied:
            return self._reconcile_action_response(claimed)
        if claimed.claim_token is None or claimed.attempt_id is None:
            return self._reconcile_action_response(
                WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=claimed.action_id,
                    action_status=claimed.action_status,
                    action_version=claimed.action_version,
                    next_allowed_commands=claimed.next_allowed_commands,
                    conflict_detail="applied claim is missing execution authority",
                )
            )

        attempt_id = claimed.attempt_id
        if self._should_stop_for_cancel(request.run_id):
            failed = self._mark_write_failed(
                MarkWriteActionFailedCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "cancel_before_write", "action_id": request.action_id}
                    ),
                    action_id=request.action_id,
                    attempt_id=attempt_id,
                    expected_action_version=claimed.action_version,
                    expected_attempt_version=0,
                    error_code="CANCEL_REQUESTED",
                    error_detail="write was not sent because cancellation was requested",
                )
            )
            if not failed.applied:
                return self._reconcile_action_response(failed)
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.CANCEL_REQUESTED,
                action_status=failed.action_status,
                result_code=failed.result_code,
                current_status=failed.action_status,
                current_version=failed.action_version,
                next_allowed_commands=failed.next_allowed_commands,
            )

        try:
            executed = self._execute_write(
                action_id=request.action_id,
                claim_token=claimed.claim_token,
            )
        except GoogleWorkspaceGatewayError as error:
            return self._handle_execution_error(
                request=request,
                attempt_id=attempt_id,
                claimed_action_version=claimed.action_version,
                error=error,
            )

        stored = self._store_write_success(
            StoreWriteActionSuccessCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "store_success", "action_id": request.action_id}
                ),
                action_id=request.action_id,
                attempt_id=attempt_id,
                expected_action_version=claimed.action_version,
                expected_attempt_version=1,
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

        begin = self._begin_verification(request.run_id)
        if begin is not None and not begin.applied:
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
                result_code=begin.result_code.value,
                current_status=begin.current_status.value,
                current_version=begin.current_version,
                next_allowed_commands=tuple(item.value for item in begin.next_allowed_commands),
            )
        try:
            verified = self._verify_write(
                VerifyWriteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "verify", "action_id": request.action_id}
                    ),
                    action_id=request.action_id,
                    attempt_id=stored.attempt_id,
                    expected_action_version=stored.action_version,
                    verification_id=self._id_factory(),
                )
            )
        except GoogleWorkspaceGatewayError as error:
            return self._handle_verification_error(request=request, error=error)
        if not verified.applied:
            return self._reconcile_action_response(verified)
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.VERIFIED,
            action_status=verified.action_status,
            result_code=verified.result_code,
            current_status=verified.action_status,
            current_version=verified.action_version,
            next_allowed_commands=verified.next_allowed_commands,
        )

    def recover_unknown(self, request: UnknownRecoveryPhaseRequest) -> WriteActionResponse:
        command_id = self._id_factory()
        request_hash = self._request_hash(
            {"kind": f"recover_{request.effect_type.lower()}", "action_id": request.action_id}
        )
        try:
            if request.effect_type == "CREATE":
                response = self._recover_unknown_create(
                    RecoverUnknownCreateActionCommand(
                        command_id=command_id,
                        request_hash=request_hash,
                        action_id=request.action_id,
                        attempt_id=request.attempt_id,
                        expected_action_version=request.action_version,
                        expected_attempt_version=request.attempt_version,
                    )
                )
            elif request.effect_type == "SEND":
                response = self._recover_unknown_send(
                    RecoverUnknownSendActionCommand(
                        command_id=command_id,
                        request_hash=request_hash,
                        action_id=request.action_id,
                        attempt_id=request.attempt_id,
                        expected_action_version=request.action_version,
                        expected_attempt_version=request.attempt_version,
                    )
                )
            elif request.effect_type == "DELETE":
                response = self._recover_unknown_delete(
                    RecoverUnknownDeleteActionCommand(
                        command_id=command_id,
                        request_hash=request_hash,
                        action_id=request.action_id,
                        attempt_id=request.attempt_id,
                        expected_action_version=request.action_version,
                        expected_attempt_version=request.attempt_version,
                    )
                )
            else:
                response = self._recover_unknown_update(
                    RecoverUnknownUpdateActionCommand(
                        command_id=command_id,
                        request_hash=request_hash,
                        action_id=request.action_id,
                        attempt_id=request.attempt_id,
                        expected_action_version=request.action_version,
                        expected_attempt_version=request.attempt_version,
                    )
                )
        except GoogleWorkspaceGatewayError as error:
            if self._is_auth_error(error):
                reauth = self._require_reauth(request=request, error=error, kind="recover_reauth")
                return WriteActionResponse(
                    applied=False,
                    result_code=(
                        ResultCode.RECOVERY_REQUIRED.value if reauth.applied else reauth.result_code
                    ),
                    action_id=request.action_id,
                    action_status=ActionStatus.UNKNOWN_RESULT.value,
                    action_version=request.action_version,
                    next_allowed_commands=(),
                    attempt_id=request.attempt_id,
                    safe_error_code=error.code.value,
                    conflict_detail=None if reauth.applied else reauth.conflict_detail,
                )
            raise
        if response.applied and response.action_status == ActionStatus.EXECUTED.value:
            return self.verify_executed(
                action_id=request.action_id,
                action_version=response.action_version,
                attempt_id=request.attempt_id,
                request_kind="verify_recovered",
            )
        return response

    def verify_executed(
        self,
        *,
        action_id: str,
        action_version: int,
        attempt_id: str,
        request_kind: str,
    ) -> WriteActionResponse:
        return self._verify_write(
            VerifyWriteActionCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": request_kind, "action_id": action_id}),
                action_id=action_id,
                attempt_id=attempt_id,
                expected_action_version=action_version,
                verification_id=self._id_factory(),
            )
        )

    def _handle_execution_error(
        self,
        *,
        request: WriteExecutionPhaseRequest,
        attempt_id: str,
        claimed_action_version: int,
        error: GoogleWorkspaceGatewayError,
    ) -> WriteExecutionPhaseResult:
        is_auth_error = self._is_auth_error(error)
        if error.delivery_certainty is DeliveryCertainty.NOT_SENT:
            failed = self._mark_write_failed(
                MarkWriteActionFailedCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "failed", "action_id": request.action_id}
                    ),
                    action_id=request.action_id,
                    attempt_id=attempt_id,
                    expected_action_version=claimed_action_version,
                    expected_attempt_version=1,
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
                )
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.FAILED,
                action_status=failed.action_status,
                result_code=failed.result_code,
                safe_error_code=error.code.value,
                current_status=failed.action_status,
                current_version=failed.action_version,
                next_allowed_commands=failed.next_allowed_commands,
            )

        unknown = self._mark_write_unknown(
            MarkWriteActionUnknownResultCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "unknown", "action_id": request.action_id}
                ),
                action_id=request.action_id,
                attempt_id=attempt_id,
                expected_action_version=claimed_action_version,
                expected_attempt_version=1,
                error_code=error.code.value,
                error_detail=str(error),
                mcp_request_id=error.mcp_request_id,
            )
        )
        if not unknown.applied:
            return self._reconcile_action_response(unknown)
        if is_auth_error:
            reauth = self._require_reauth(request=request, error=error, kind="reauth_unknown")
            if not reauth.applied:
                return self._reconcile_run_response(reauth)
            return WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.REAUTH_REQUIRED,
                action_status=unknown.action_status,
                result_code=unknown.result_code,
                safe_error_code=error.code.value,
                current_status=unknown.action_status,
                current_version=unknown.action_version,
                next_allowed_commands=unknown.next_allowed_commands,
            )
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.UNKNOWN_RESULT,
            action_status=unknown.action_status,
            result_code=unknown.result_code,
            safe_error_code=error.code.value,
            current_status=unknown.action_status,
            current_version=unknown.action_version,
            next_allowed_commands=unknown.next_allowed_commands,
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
    ):
        return self._require_write_reauth(
            RequireWriteReauthCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": kind, "action_id": request.action_id}),
                run_id=request.run_id,
                action_id=request.action_id,
                safe_error_code=error.code.value,
                mcp_request_id=error.mcp_request_id,
            )
        )

    @staticmethod
    def _is_auth_error(error: GoogleWorkspaceGatewayError) -> bool:
        return error.code in {
            GoogleWorkspaceErrorCode.AUTH_EXPIRED,
            GoogleWorkspaceErrorCode.PERMISSION_DENIED,
        }

    @staticmethod
    def _reconcile_action_response(response: WriteActionResponse) -> WriteExecutionPhaseResult:
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
            action_status=response.action_status,
            result_code=response.result_code,
            current_status=response.action_status,
            current_version=response.action_version,
            next_allowed_commands=response.next_allowed_commands,
            safe_error_code=response.safe_error_code,
        )

    @staticmethod
    def _reconcile_run_response(response) -> WriteExecutionPhaseResult:
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.DOMAIN_RECONCILE,
            result_code=response.result_code,
            current_status=response.run_status,
            current_version=response.run_version,
            next_allowed_commands=(),
        )

    def _action_status(self, action_id: str) -> str | None:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get_by_id(action_id)
            return None if action is None else action.status
