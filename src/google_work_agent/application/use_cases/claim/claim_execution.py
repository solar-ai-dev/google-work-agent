"""Canonical durable application use case for claiming write execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import cast

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_calendar_conflict_authority,
    calendar_conflict_authority,
    calendar_conflict_change_requires_reapproval,
)
from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.feasibility import (
    approval_feasibility_authority,
    feasibility_authority,
    feasibility_change_requires_reapproval,
)
from google_work_agent.application.persistence_cas import (
    update_action_record,
    update_approval_status,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_duplicate_authority,
    duplicate_authority,
    duplicate_change_requires_reapproval,
)
from google_work_agent.application.write_action_arguments import dict_argument
from google_work_agent.application.write_execution_integrity import (
    CLAIM_TOKEN_VERSION,
    issue_claim_token,
)
from google_work_agent.application.write_persistence import (
    emit_command_rejected_hash_mismatch,
    require_action,
    require_plan,
    require_run,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1, EffectType, PolicyViolationError
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.claim.guards.claim_execution import (
    ClaimExecutionGuardInput,
    guard_claim_execution,
)
from google_work_agent.domain.claim.model import ClaimCommand
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    UnitOfWork,
)
from google_work_agent.ports.connector.claim_context_contract import (
    CLAIM_CONTEXT_DEFAULT_TTL_MS,
    validate_claim_ttl_ms,
)
from google_work_agent.ports.connector.migration_contracts.tool_registry import (
    build_p0_tool_registry,
)
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple


@dataclass(frozen=True, slots=True)
class ClaimExecutionCommand:
    """Server-owned command input for one durable WRITE claim."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    source_snapshot: dict[str, object]
    attempt_id: str
    nonce: str


@dataclass(frozen=True, slots=True)
class ClaimExecutionResult:
    """Durable result returned only after the claim transaction commits."""

    applied: bool
    result_code: ResultCode
    action_id: str
    current_status: ActionStatusV1
    current_version: int
    next_allowed_commands: tuple[ClaimCommand, ...]
    approval_id: str | None = None
    attempt_id: str | None = None
    claim_token: str | None = None
    conflict_detail: str | None = None


class ClaimExecutionHandler:
    """Atomically consume Approval, claim Action, insert Attempt, audit and receipt.

    This handler deliberately has no Connector/MCP dependency. External WRITE dispatch
    is a later execution concern and cannot occur before this transaction commits.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
        claim_ttl_ms: int = CLAIM_CONTEXT_DEFAULT_TTL_MS,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._claim_ttl_ms = validate_claim_ttl_ms(claim_ttl_ms)
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ClaimExecutionCommand) -> ClaimExecutionResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    command=command,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ClaimExecution",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )

            action = require_action(unit_of_work, command.action_id)
            plan = require_plan(unit_of_work, action.plan_id)
            run = require_run(unit_of_work, plan.run_id)
            approval = unit_of_work.approvals.get_active_for_action(action.id)
            if approval is None:
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    action_id=action.id,
                    status=ActionStatusV1(action.status),
                    version=action.version,
                    now_ms=now_ms,
                    detail="write action requires an ACTIVE approval",
                )

            entry = self._registry.require(action.tool_name)
            active_attempt_exists = (
                unit_of_work.execution_attempts.get_active_for_approval(approval.id) is not None
            )
            predecessor_verified = self._predecessors_verified(
                unit_of_work=unit_of_work,
                action_id=action.id,
            )
            plans = tuple(current_plan_tuple(unit_of_work.plans, run.id))
            current_plan = max(
                plans,
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )

            try:
                current_source_snapshot = self._current_source_snapshot(
                    action=action,
                    approval_source_snapshot_json=approval.source_snapshot_json,
                    command_source_snapshot=command.source_snapshot,
                )
                guard = ClaimExecutionGuardInput(
                    action_status=ActionStatusV1(action.status),
                    effect_type=EffectType(action.effect_type),
                    action_version=action.version,
                    approval_status=approval.status,
                    approval_action_version=approval.action_version,
                    approval_arguments_hash=approval.canonical_arguments_hash,
                    current_arguments_hash=action.arguments_hash,
                    approval_source_snapshot_hash=approval.source_snapshot_hash,
                    current_source_snapshot_hash=calculate_canonical_json_hash(
                        current_source_snapshot
                    ),
                    approval_policy_version=approval.policy_version,
                    current_policy_version=entry.registry_version,
                    approval_tool_schema_version=approval.tool_schema_version,
                    current_tool_schema_version=entry.input_schema_version,
                    expires_at_ms=approval.expires_at_ms,
                    now_ms=now_ms,
                    run_status=run.status,
                    plan_status=plan.status,
                    plan_is_current=current_plan is not None and current_plan.id == plan.id,
                    durable_cancel_intent=has_durable_cancel_intent(
                        unit_of_work.cancel_intents, run.id
                    ),
                    predecessor_verified=predecessor_verified,
                    active_attempt_exists=active_attempt_exists,
                )
                guard_claim_execution(guard)
            except PolicyViolationError as error:
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    action_id=action.id,
                    status=ActionStatusV1(action.status),
                    version=action.version,
                    now_ms=now_ms,
                    detail=str(error),
                )

            preview = transition_claim_execution(
                guard.action_status,
                guard.action_version,
                command.expected_version,
                effect_type=guard.effect_type,
            )
            if not preview.applied:
                result = ClaimExecutionResult(
                    applied=False,
                    result_code=preview.result_code,
                    action_id=action.id,
                    current_status=preview.current_status,
                    current_version=preview.current_version,
                    next_allowed_commands=preview.next_allowed_commands,
                    conflict_detail=preview.conflict_detail,
                )
                self._finish_receipt(
                    unit_of_work=unit_of_work,
                    command_id=command.command_id,
                    result=result,
                    result_version=action.version,
                    completed_at_ms=now_ms,
                )
                unit_of_work.commit()
                return result

            # Order is intentional: executable DB invariant 0005 forbids moving an
            # Action away from APPROVED while its Approval remains ACTIVE.
            if not update_approval_status(
                unit_of_work,
                approval.id,
                expected_status=approval.status,
                next_status=ApprovalStatusV1.CONSUMED,
                consumed_at_ms=now_ms,
            ):
                raise RuntimeError("validated ConsumeApproval CAS failed")
            if (
                update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=preview.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated ClaimExecution CAS failed")
            persisted = preview

            attempt = ExecutionAttemptRecord(
                id=command.attempt_id,
                approval_id=approval.id,
                attempt_no=len(
                    active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
                )
                + 1,
                status=ExecutionAttemptStatusV1.CLAIMED,
                version=0,
                result_resource_ref_id=None,
                response_metadata_json=None,
                error_code=None,
                error_detail_json=None,
                started_at_ms=now_ms,
                finished_at_ms=None,
            )
            unit_of_work.execution_attempts.insert_claimed(attempt)

            claim_token = issue_claim_token(
                {
                    "version": CLAIM_TOKEN_VERSION,
                    "action_id": action.id,
                    "approval_id": approval.id,
                    "attempt_id": attempt.id,
                    "tool_name": action.tool_name,
                    "arguments_hash": action.arguments_hash,
                    "service_instance_id": self._service_instance_id,
                    "nonce": command.nonce,
                    "issued_at_ms": now_ms,
                    "expires_at_ms": now_ms + self._claim_ttl_ms,
                },
                signing_secret=self._signing_secret,
            )

            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="EXECUTION_CLAIMED",
                    status=ActionStatusV1.EXECUTING.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"approval_id": approval.id, "attempt_id": attempt.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                self._audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="APPROVAL_CONSUMED",
                    metadata={"approval_id": approval.id},
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                self._audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="EXECUTION_CLAIMED",
                    metadata={"approval_id": approval.id, "attempt_id": attempt.id},
                    created_at_ms=now_ms,
                )
            )

            result = ClaimExecutionResult(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED,
                action_id=action.id,
                current_status=persisted.current_status,
                current_version=persisted.current_version,
                next_allowed_commands=persisted.next_allowed_commands,
                approval_id=approval.id,
                attempt_id=attempt.id,
                claim_token=claim_token,
            )
            self._finish_receipt(
                unit_of_work=unit_of_work,
                command_id=command.command_id,
                result=result,
                result_version=persisted.current_version,
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return result

    def _current_source_snapshot(
        self,
        *,
        action: ActionRecord,
        approval_source_snapshot_json: str,
        command_source_snapshot: dict[str, object],
    ) -> dict[str, object]:
        stored = dict_argument(loads(approval_source_snapshot_json))
        risk = action.risk
        tool_name = action.tool_name

        if tool_name == TASK_CREATE_TOOL:
            if duplicate_change_requires_reapproval(
                approved=approval_duplicate_authority(stored),
                current=duplicate_authority(risk),
            ):
                raise PolicyViolationError("task duplicate risk changed after approval")
            return {
                **command_source_snapshot,
                "task_duplicate": stored.get("task_duplicate"),
            }

        if tool_name in CALENDAR_CONFLICT_TOOLS:
            if feasibility_change_requires_reapproval(
                approved=approval_feasibility_authority(stored),
                current=feasibility_authority(risk),
            ):
                raise PolicyViolationError("feasibility risk changed after approval")
            if calendar_conflict_change_requires_reapproval(
                approved=approval_calendar_conflict_authority(stored),
                current=calendar_conflict_authority(risk),
            ):
                raise PolicyViolationError("calendar conflict risk changed after approval")
            return {
                **command_source_snapshot,
                "calendar_conflict": stored.get("calendar_conflict"),
                "feasibility": stored.get("feasibility"),
            }

        return command_source_snapshot

    @staticmethod
    def _predecessors_verified(*, unit_of_work: UnitOfWork, action_id: str) -> bool:
        return unit_of_work.actions.is_dependency_ready(action_id)

    @staticmethod
    def _audit_event(
        *,
        run_id: str,
        action_id: str,
        event_type: str,
        metadata: dict[str, object],
        created_at_ms: int,
    ) -> AuditEventRecord:
        return AuditEventRecord(
            account_id=None,
            run_id=run_id,
            action_id=action_id,
            actor_type="AGENT",
            actor_id="claim_execution",
            actor_display="ClaimExecutionHandler",
            event_type=event_type,
            outcome=ResultCode.TRANSITION_APPLIED.value,
            metadata_json=dumps(metadata, sort_keys=True),
            created_at_ms=created_at_ms,
        )

    def _reject(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: ClaimExecutionCommand,
        action_id: str,
        status: ActionStatusV1,
        version: int,
        now_ms: int,
        detail: str,
    ) -> ClaimExecutionResult:
        result = ClaimExecutionResult(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT,
            action_id=action_id,
            current_status=status,
            current_version=version,
            next_allowed_commands=(),
            conflict_detail=detail,
        )
        self._finish_receipt(
            unit_of_work=unit_of_work,
            command_id=command.command_id,
            result=result,
            result_version=version,
            completed_at_ms=now_ms,
        )
        unit_of_work.commit()
        return result

    def _resolve_existing_receipt(
        self,
        *,
        unit_of_work: UnitOfWork,
        receipt: CommandReceiptRecord,
        command: ClaimExecutionCommand,
    ) -> ClaimExecutionResult:
        if receipt.request_hash != command.request_hash:
            emit_command_rejected_hash_mismatch(
                unit_of_work=unit_of_work,
                receipt=receipt,
                run_id=None,
                action_id=command.action_id,
                now_ms=self._now_ms(),
            )
            action = require_action(unit_of_work, command.action_id)
            return ClaimExecutionResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND,
                action_id=action.id,
                current_status=ActionStatusV1(action.status),
                current_version=action.version,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            )

        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            action = require_action(unit_of_work, command.action_id)
            return ClaimExecutionResult(
                applied=False,
                result_code=ResultCode.RECOVERY_REQUIRED,
                action_id=action.id,
                current_status=ActionStatusV1(action.status),
                current_version=action.version,
                next_allowed_commands=(),
                conflict_detail=(
                    "receipt exists in RECEIVED state; durable claim recovery is inconclusive"
                ),
            )

        payload = loads(receipt.response_json)
        return ClaimExecutionResult(
            applied=bool(payload["applied"]),
            result_code=ResultCode(str(payload["result_code"])),
            action_id=str(payload["action_id"]),
            current_status=ActionStatusV1(str(payload["current_status"])),
            current_version=int(payload["current_version"]),
            next_allowed_commands=tuple(
                ClaimCommand(str(item)) for item in payload["next_allowed_commands"]
            ),
            approval_id=cast(str | None, payload.get("approval_id")),
            attempt_id=cast(str | None, payload.get("attempt_id")),
            claim_token=cast(str | None, payload.get("claim_token")),
            conflict_detail=cast(str | None, payload.get("conflict_detail")),
        )

    @staticmethod
    def _finish_receipt(
        *,
        unit_of_work: UnitOfWork,
        command_id: str,
        result: ClaimExecutionResult,
        result_version: int,
        completed_at_ms: int,
    ) -> None:
        unit_of_work.command_receipts.store_result(
            command_id=command_id,
            applied=result.applied,
            result_code=result.result_code,
            result_version=result_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=completed_at_ms,
        )
