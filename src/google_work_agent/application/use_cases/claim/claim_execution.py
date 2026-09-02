"""Canonical durable application use case for claiming write execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
    CalendarWorkHours,
)
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_calendar_conflict_authority,
    calendar_conflict_authority,
    calendar_conflict_change_requires_reapproval,
)
from google_work_agent.application.use_cases.action.feasibility import (
    approval_feasibility_authority,
    feasibility_authority,
    feasibility_change_requires_reapproval,
)
from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_approval_status,
)
from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionCommand,
    RefreshExpiredActionHandler,
)
from google_work_agent.application.use_cases.action.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_duplicate_authority,
    duplicate_authority,
    duplicate_change_requires_reapproval,
)
from google_work_agent.application.use_cases.action.write_action_arguments import dict_argument
from google_work_agent.application.use_cases.action.write_persistence import (
    emit_command_rejected_hash_mismatch,
    has_unresolved_unknown_result,
    require_action,
    require_plan,
    require_run,
)
from google_work_agent.application.use_cases.approval.expire_approval import (
    ExpireApprovalCommand,
    ExpireApprovalHandler,
)
from google_work_agent.application.use_cases.claim._write_preflight import (
    PreflightWriteGateway,
    _WritePreflight,
)
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.run.block_run import BlockRunHandler
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
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
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ClaimExecutionCommand:
    """Server-owned command input for one durable WRITE claim."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    source_snapshot: dict[str, object]
    attempt_id: str


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
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimPreflightRefreshResult:
    requires_reapproval: bool
    action_status: str
    result_code: str
    action_version: int


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
        preflight_gateway: PreflightWriteGateway | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
        expire_approval: ExpireApprovalHandler | None = None,
        refresh_expired_action: RefreshExpiredActionHandler | None = None,
        block_run: BlockRunHandler | None = None,
        tool_registry: SignedToolRegistry,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = tool_registry
        self._expire_approval = expire_approval
        self._refresh_expired_action = refresh_expired_action
        self._preflight = (
            None
            if preflight_gateway is None
            else _WritePreflight(
                unit_of_work_factory=unit_of_work_factory,
                gateway=preflight_gateway,
                now_ms=now_ms,
                work_hours_provider=work_hours_provider,
                expire_approval=expire_approval,
                refresh_expired_action=refresh_expired_action,
                block_run=block_run,
                tool_registry=tool_registry,
            )
        )

    def preflight(self, *, action_id: str) -> dict[str, object]:
        """Run the claim-owned provider-read safety phase."""

        if self._preflight is None:
            raise RuntimeError("claim preflight is not configured")
        return self._preflight(action_id=action_id)

    def action_status(self, action_id: str) -> str | None:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
        return None if action is None else action.status

    def refresh_stale_preflight(
        self,
        *,
        claim: ClaimExecutionResult,
        source_snapshot: dict[str, object],
    ) -> ClaimPreflightRefreshResult | None:
        stale_reasons = {
            "approval expired",
            "approval action version is stale",
            "approval arguments binding is stale",
            "approval source snapshot is stale",
            "approval policy version is stale",
            "approval tool schema version is stale",
        }
        if (
            claim.conflict_detail not in stale_reasons
            or claim.approval_id is None
            or self._expire_approval is None
        ):
            return None
        with self._unit_of_work_factory() as unit_of_work:
            approval = unit_of_work.approvals.get(claim.approval_id)
            current_action = unit_of_work.actions.get(claim.action_id)
        if approval is None or current_action is None:
            raise LookupError("stale approval authority disappeared")
        entry = self._registry.get_required(current_action.connector_id, current_action.tool_name)
        current_source_snapshot = (
            source_snapshot
            if claim.conflict_detail == "approval source snapshot is stale"
            else cast(dict[str, object], loads(approval.source_snapshot_json))
        )
        current_source_snapshot_hash = calculate_canonical_json_hash(current_source_snapshot)
        expire_request = {
            "approval_id": claim.approval_id,
            "expected_action_version": claim.current_version,
            "current_source_snapshot": current_source_snapshot,
        }
        expired = self._expire_approval(
            ExpireApprovalCommand(
                command_id=f"system:expire-approval:{claim.approval_id}",
                request_hash=calculate_canonical_json_hash(expire_request),
                approval_id=claim.approval_id,
                expected_action_version=claim.current_version,
                current_source_snapshot=current_source_snapshot,
            )
        )
        if not expired.applied or self._refresh_expired_action is None:
            return ClaimPreflightRefreshResult(
                False,
                expired.action_status,
                expired.result_code,
                expired.action_version,
            )
        refresh_request = {
            "action_id": claim.action_id,
            "expected_version": expired.action_version,
            "fresh_source_snapshot": current_source_snapshot,
            "fresh_source_snapshot_hash": current_source_snapshot_hash,
            "fresh_policy_version": entry.registry_version,
            "fresh_tool_schema_version": entry.input_schema_version,
            "fresh_risk": current_action.risk,
        }
        refreshed = self._refresh_expired_action(
            RefreshExpiredActionCommand(
                command_id=f"system:refresh-expired-action:{claim.action_id}",
                request_hash=calculate_canonical_json_hash(refresh_request),
                action_id=claim.action_id,
                expected_version=expired.action_version,
                fresh_source_snapshot=current_source_snapshot,
                fresh_source_snapshot_hash=current_source_snapshot_hash,
                fresh_policy_version=entry.registry_version,
                fresh_tool_schema_version=entry.input_schema_version,
                fresh_risk=current_action.risk,
            )
        )
        return ClaimPreflightRefreshResult(
            True,
            refreshed.action_status,
            refreshed.result_code,
            refreshed.action_version,
        )

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

            entry = self._registry.get_required(action.connector_id, action.tool_name)
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

            if has_unresolved_unknown_result(unit_of_work, plan.id):
                return self._reject(
                    unit_of_work=unit_of_work,
                    command=command,
                    action_id=action.id,
                    status=ActionStatusV1(action.status),
                    version=action.version,
                    now_ms=now_ms,
                    detail="unresolved UNKNOWN_RESULT blocks a new execution claim",
                    approval_id=approval.id,
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
                        unit_of_work.command_receipts, run.id
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
                    approval_id=approval.id,
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
                attempt_no=len(active_attempt_tuple(unit_of_work.execution_attempts, approval.id))
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
        approval_id: str | None = None,
    ) -> ClaimExecutionResult:
        result = ClaimExecutionResult(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT,
            action_id=action_id,
            current_status=status,
            current_version=version,
            next_allowed_commands=(),
            approval_id=approval_id,
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
