"""Persist one immutable Verification and its Action lifecycle fact."""

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import update_action_record
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event,
    finish_json_receipt,
    require_action,
    require_attempt,
    require_plan,
)
from google_work_agent.application.use_cases.verification.verify_effect import VerificationResultV1
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import canonicalize_json_value
from google_work_agent.domain.command_receipt.model import CommandReceipt, CommandReceiptStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent
from google_work_agent.domain.verification.model import Verification, VerificationStatus
from google_work_agent.domain.verification.transitions.store_verification import (
    transition_store_verification,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

VERIFICATION_NORMALIZER_VERSION = "2026-08-06.p0"


@dataclass(frozen=True, slots=True)
class StoreVerificationCommand:
    command_id: str
    request_hash: str
    verification_id: str
    run_id: str
    action_id: str
    execution_attempt_id: str
    expected_action_version: int
    verification: VerificationResultV1


@dataclass(frozen=True, slots=True)
class StoreVerificationResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    verification_id: str | None
    requires_recovery: bool
    conflict_detail: str | None = None
    request_replayed: bool = False


class StoreVerificationHandler:
    """Store Action/Verification only; Recovery entry is a separate command."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: StoreVerificationCommand) -> StoreVerificationResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay(command, existing)
            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="StoreVerification",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.execution_attempt_id)
            plan = require_plan(unit_of_work, action.plan_id)
            if plan.run_id != command.run_id:
                raise ValueError("verification Run/Action binding mismatch")
            if attempt.id != command.execution_attempt_id:
                raise ValueError("verification Attempt binding mismatch")
            status = VerificationStatus(command.verification.status)
            transition = transition_store_verification(
                ActionStatusV1(action.status),
                current_version=action.version,
                expected_version=command.expected_action_version,
                verification_status=status,
            )
            if not transition.applied:
                result = StoreVerificationResult(
                    False,
                    transition.result_code.value,
                    action.id,
                    transition.current_status.value,
                    transition.current_version,
                    None,
                    False,
                    transition.conflict_detail,
                )
                self._finish(unit_of_work, command, result, now_ms)
                unit_of_work.commit()
                return result

            latest = unit_of_work.verifications.get_latest_for_attempt(attempt.id)
            record = Verification(
                id=command.verification_id,
                execution_attempt_id=attempt.id,
                verification_no=1 if latest is None else latest.verification_no + 1,
                status=status,
                normalizer_version=VERIFICATION_NORMALIZER_VERSION,
                expected_json=canonicalize_json_value(command.verification.expected_normalized),
                actual_json=(
                    None
                    if command.verification.actual_normalized is None
                    else canonicalize_json_value(command.verification.actual_normalized)
                ),
                diff_json=canonicalize_json_value(command.verification.reason_codes),
                verified_at_ms=now_ms,
            )
            unit_of_work.verifications.insert(record)
            if (
                update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=transition.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated StoreVerification CAS failed")
            event_type = (
                "VERIFICATION_VERIFIED"
                if status is VerificationStatus.VERIFIED
                else "VERIFICATION_MISMATCH"
            )
            unit_of_work.traces.append(
                TraceEvent(
                    run_id=command.run_id,
                    action_id=action.id,
                    event_type=event_type,
                    status=status.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "verification_id": record.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                audit_event(
                    run_id=command.run_id,
                    action_id=action.id,
                    event_type=event_type,
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"attempt_id": attempt.id, "verification_id": record.id},
                    created_at_ms=now_ms,
                )
            )
            result = StoreVerificationResult(
                True,
                ResultCode.TRANSITION_APPLIED.value,
                action.id,
                transition.current_status.value,
                transition.current_version,
                record.id,
                status is VerificationStatus.MISMATCH,
            )
            self._finish(unit_of_work, command, result, now_ms)
            unit_of_work.commit()
            return result

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        command: StoreVerificationCommand,
        result: StoreVerificationResult,
        now_ms: int,
    ) -> None:
        finish_json_receipt(
            unit_of_work,
            command.command_id,
            result,
            result.action_version,
            now_ms,
        )

    @staticmethod
    def _replay(
        command: StoreVerificationCommand, receipt: CommandReceipt
    ) -> StoreVerificationResult:
        if receipt.request_hash != command.request_hash:
            return StoreVerificationResult(
                False,
                ResultCode.DUPLICATE_COMMAND.value,
                command.action_id,
                "UNKNOWN",
                0,
                None,
                False,
                "command_id already exists with a different request_hash",
                True,
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        return StoreVerificationResult(**{**loads(receipt.response_json), "request_replayed": True})


__all__ = ["StoreVerificationCommand", "StoreVerificationHandler", "StoreVerificationResult"]
