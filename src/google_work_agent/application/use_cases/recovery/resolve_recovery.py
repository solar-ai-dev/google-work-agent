"""Application use case for explicit Run recovery resolution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.persistence_cas import update_plan_record
from google_work_agent.application.write_persistence import (
    cancel_pending_actions,
    revoke_active_approvals,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.recovery.model import RecoveryResolution
from google_work_agent.domain.recovery.transitions.resolve_recovery import (
    transition_resolve_recovery,
)
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.model import RunStatusV1, next_allowed_run_commands
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ResolveRecoveryCommandV1:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str
    resolution: RecoveryResolution
    cancel_intent_active: bool = False
    terminal_snapshot: bool = False
    irrecoverable_confirmed: bool = False
    recheck_input_changed: bool = False
    recovered_action_status: ActionStatusV1 | None = None
    validated_resume_status: RunStatusV1 | None = None
    unresolved_external_effect_count: int = 0


@dataclass(frozen=True, slots=True)
class ResolveRecoveryResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None
    result_kind: str | None = None
    plan_id: str | None = None


class ResolveRecoveryHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        next_id: Callable[[], str] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._next_id = next_id

    def __call__(self, command: ResolveRecoveryCommandV1) -> ResolveRecoveryResult:
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay_or_reject_duplicate(unit_of_work, command, existing)

            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            context = unit_of_work.recovery_contexts.load_current_context(command.run_id)
            if context is None:
                raise RuntimeError("ResolveRecovery requires a durable RecoveryContextV1")

            decision = transition_resolve_recovery(
                run.status,
                resolution=command.resolution,
                reason=context["reason"],
                pre_recovery_status=RunStatusV1(context["pre_recovery_status"]),
                recheck_input_changed=command.recheck_input_changed,
                recovered_action_status=self._recovered_action_status(
                    unit_of_work, command, context
                ),
                validated_resume_status=command.validated_resume_status,
                cancel_intent_active=command.cancel_intent_active,
                unresolved_external_effect_count=command.unresolved_external_effect_count,
                irrecoverable_confirmed=command.irrecoverable_confirmed,
            )
            if not decision.applied:
                result = ResolveRecoveryResult(
                    applied=False,
                    result_code=decision.result_code.value,
                    current_status=run.status.value,
                    current_version=run.version,
                    next_allowed_commands=(),
                    conflict_detail=decision.conflict_detail,
                )
                self._store_result(unit_of_work, command, result, now_ms)
                unit_of_work.commit()
                return result

            target = decision.current_status
            plan, result_kind = self._apply_resolution_effects(
                unit_of_work,
                command=command,
                context=context,
                now_ms=now_ms,
            )
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ResolveRecovery",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            if run.version != command.expected_version:
                persisted = CommandResult(
                    False,
                    ResultCode.VERSION_CONFLICT,
                    run.status,
                    run.version,
                    next_allowed_run_commands(run.status),
                    "expected_version does not match current_version",
                )
            else:
                values: dict[str, object] = {
                    "status": target.value,
                    "version": run.version + 1,
                }
                if target in {RunStatusV1.COMPLETED, RunStatusV1.CANCELLED, RunStatusV1.FAILED}:
                    values["finished_at_ms"] = now_ms
                    values["terminal_result_kind"] = result_kind
                applied = unit_of_work.runs.update_if_version_and_status(
                    run.id, run.version, frozenset({run.status}), values
                )
                persisted = CommandResult(
                    applied,
                    ResultCode.TRANSITION_APPLIED if applied else ResultCode.VERSION_CONFLICT,
                    target if applied else run.status,
                    run.version + 1 if applied else run.version,
                    next_allowed_run_commands(target if applied else run.status),
                    None if applied else "validated Run CAS failed",
                )
            result = ResolveRecoveryResult(
                applied=persisted.applied,
                result_code=persisted.result_code.value,
                current_status=persisted.current_status.value,
                current_version=persisted.current_version,
                next_allowed_commands=tuple(item.value for item in persisted.next_allowed_commands),
                conflict_detail=persisted.conflict_detail,
                result_kind=result_kind,
                plan_id=None if plan is None else plan.id,
            )
            if result.applied:
                unit_of_work.recovery_contexts.clear_context(
                    command.run_id, int(context["version"])
                )
                metadata = dumps(
                    {
                        "command_id": command.command_id,
                        "reason": context["reason"],
                        "resolution": command.resolution.value,
                    },
                    sort_keys=True,
                )
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=command.run_id,
                        action_id=None
                        if context.get("action_id") is None
                        else str(context["action_id"]),
                        event_type="RECOVERY_RESOLVED",
                        status=result.current_status,
                        duration_ms=None,
                        payload_json=metadata,
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    AuditEventRecord(
                        account_id=None,
                        run_id=command.run_id,
                        action_id=None
                        if context.get("action_id") is None
                        else str(context["action_id"]),
                        actor_type="SYSTEM",
                        actor_id="run_lifecycle",
                        actor_display="Run lifecycle",
                        event_type="RECOVERY_RESOLVED",
                        outcome=result.result_code,
                        metadata_json=metadata,
                        created_at_ms=now_ms,
                    )
                )
            unit_of_work.command_receipts.store_result(
                command_id=command.command_id,
                applied=result.applied,
                result_code=persisted.result_code,
                result_version=result.current_version,
                response_json=dumps(asdict(result), sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
            return result

    @staticmethod
    def recheck_in_unit_of_work(
        unit_of_work: UnitOfWork,
        *,
        run_id: str,
        expected_version: int,
    ) -> object:
        """Canonical RECHECK transition seam for an enclosing resume UoW.

        It deliberately requires the durable RecoveryContext rather than
        allowing ResumeRun to invent a recovery target.
        """
        run = unit_of_work.runs.get(run_id)
        context = unit_of_work.recovery_contexts.load_current_context(run_id)
        if run is None or context is None:
            raise RuntimeError("RECOVERY_RECHECK requires a durable RecoveryContextV1")
        decision = transition_resolve_recovery(
            run.status,
            resolution=RecoveryResolution.RECHECK,
            reason=context["reason"],
            pre_recovery_status=RunStatusV1(context["pre_recovery_status"]),
            recheck_input_changed=True,
            recovered_action_status=ResolveRecoveryHandler._recovered_action_status(
                unit_of_work,
                ResolveRecoveryCommandV1(
                    run_id=run_id,
                    expected_version=expected_version,
                    command_id="system:resume-recheck",
                    request_hash="",
                    resolution=RecoveryResolution.RECHECK,
                ),
                context,
            ),
            validated_resume_status=(
                RunStatusV1(context["pre_recovery_status"])
                if context["reason"] in {"CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"}
                else None
            ),
        )
        if not decision.applied:
            return decision
        applied = (
            run.version == expected_version
            and unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {"status": decision.current_status.value, "version": run.version + 1},
            )
        )
        persisted = CommandResult(
            applied,
            ResultCode.TRANSITION_APPLIED if applied else ResultCode.VERSION_CONFLICT,
            decision.current_status if applied else run.status,
            run.version + 1 if applied else run.version,
            next_allowed_run_commands(decision.current_status if applied else run.status),
            None if applied else "validated Run CAS failed",
        )
        if persisted.applied:
            unit_of_work.recovery_contexts.clear_context(run_id, int(context["version"]))
        return persisted

    @staticmethod
    def _recovered_action_status(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommandV1,
        context: dict[str, object],
    ) -> ActionStatusV1 | None:
        if command.recovered_action_status is not None:
            return command.recovered_action_status
        action_id = context.get("action_id")
        if action_id is None:
            return None
        action = unit_of_work.actions.get(str(action_id))
        return None if action is None else ActionStatusV1(action.status)

    def _apply_resolution_effects(
        self,
        unit_of_work: UnitOfWork,
        *,
        command: ResolveRecoveryCommandV1,
        context: dict[str, object],
        now_ms: int,
    ) -> tuple[PlanRecord | None, str | None]:
        """Preserve mismatch recovery effects at the canonical writer boundary."""
        plans = current_plan_tuple(unit_of_work.plans, command.run_id)
        plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
        if command.resolution is RecoveryResolution.CANCEL:
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            external_mutation_observed = any(
                action.status
                in {
                    ActionStatusV1.EXECUTED.value,
                    ActionStatusV1.VERIFIED.value,
                    ActionStatusV1.MISMATCH.value,
                }
                for action in actions
            )
            return plan, "PARTIAL" if external_mutation_observed else "CANCELLED"
        if command.resolution not in {
            RecoveryResolution.ACCEPT_PARTIAL,
            RecoveryResolution.CREATE_CORRECTIVE_PLAN,
        }:
            return plan, "FAILED" if command.resolution is RecoveryResolution.FAIL else None
        if plan is None:
            raise LookupError(f"plan not found for recovery run: {command.run_id}")
        action_id = context.get("action_id")
        action = None if action_id is None else unit_of_work.actions.get(str(action_id))
        if (
            action is None
            or action.plan_id != plan.id
            or action.status != ActionStatusV1.MISMATCH.value
        ):
            raise RuntimeError("mismatch recovery requires the current MISMATCH action")
        if has_durable_cancel_intent(unit_of_work.cancel_intents, command.run_id):
            raise RuntimeError("mismatch recovery is forbidden while cancel intent is active")
        if command.resolution is RecoveryResolution.ACCEPT_PARTIAL:
            cancel_pending_actions(
                unit_of_work=unit_of_work,
                run_id=command.run_id,
                plan_id=plan.id,
                updated_at_ms=now_ms,
            )
            if (
                update_plan_record(
                    unit_of_work,
                    plan.id,
                    expected_status=plan.status,
                    next_status=PlanStatusV1.COMPLETED,
                )
                is None
            ):
                raise RuntimeError(f"validated Plan completion CAS failed: {plan.id}")
            return plan, "PARTIAL"

        for candidate in unit_of_work.actions.list_for_plan(plan.id):
            revoke_active_approvals(unit_of_work, candidate.id)
        if (
            update_plan_record(
                unit_of_work,
                plan.id,
                expected_status=plan.status,
                next_status=PlanStatusV1.SUPERSEDED,
            )
            is None
        ):
            raise RuntimeError(f"validated Plan supersession CAS failed: {plan.id}")
        if self._next_id is None:
            raise RuntimeError("CREATE_CORRECTIVE_PLAN requires an id generator")
        corrective = PlanRecord(
            id=self._next_id(),
            run_id=command.run_id,
            revision_no=max(item.revision_no for item in plans) + 1,
            status=PlanStatusV1.DRAFT,
            summary_text=f"Corrective plan for mismatch action {action.id}",
            created_at_ms=now_ms,
        )
        unit_of_work.plans.insert_revision(corrective)
        return corrective, "CORRECTIVE_PLAN_REQUIRED"

    @staticmethod
    def _replay_or_reject_duplicate(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommandV1,
        receipt: object,
    ) -> ResolveRecoveryResult:
        if receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            return ResolveRecoveryResult(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                current_status=run.status.value if run else "UNKNOWN",
                current_version=run.version if run else 0,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        payload = loads(receipt.response_json)
        payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ()))
        return ResolveRecoveryResult(**payload)

    @staticmethod
    def _store_result(
        unit_of_work: UnitOfWork,
        command: ResolveRecoveryCommandV1,
        result: ResolveRecoveryResult,
        now_ms: int,
    ) -> None:
        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command.command_id,
            command_type="ResolveRecovery",
            request_hash=command.request_hash,
            aggregate_type="Run",
            aggregate_id=command.run_id,
            created_at_ms=now_ms,
        )
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=False,
            result_code=ResultCode(result.result_code),
            result_version=result.current_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=now_ms,
        )
