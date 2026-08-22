"""Resume one persisted run through the canonical Domain authority."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
from json import dumps
from typing import cast

from google_work_agent.application.run_command_receipts import finish_json_receipt, resolve_existing_receipt
from google_work_agent.application.run_contracts import ResumeRunCommand, ResumeRunResponse as ResumeRunResult
from google_work_agent.domain import ActionStatus, ResultCode, RunStatus
from google_work_agent.ports import AuditEventRecord, TraceEventRecord, UnitOfWork

ResumeAuthority = Mapping[str, object]


class ResumeRunHandler:
    """Own receipt, persisted resume transition, observability, commit, and handoff."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        enqueue_resume: Callable[..., None],
        resolve_resume_authority: Callable[..., ResumeAuthority | None],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._enqueue_resume = enqueue_resume
        self._resolve_resume_authority = resolve_resume_authority

    @classmethod
    def from_legacy_service_supplier(cls, service_supplier: Callable[[], object], coordinator: object) -> "ResumeRunHandler":
        service = service_supplier()
        query_service = coordinator._query_service  # type: ignore[attr-defined]
        workflow_runtime = coordinator._workflow_runtime  # type: ignore[attr-defined]

        def resolve_authority(*, run_id: str, resume_kind: str) -> ResumeAuthority | None:
            context = query_service.get_run_execution_context(run_id)
            if context is None:
                return None
            resolver = getattr(workflow_runtime, "resolve_resume_authority", None)
            if resolver is None:
                return None
            return cast(ResumeAuthority | None, resolver(run_id=run_id, workflow_key=context.workflow_key, resume_kind=resume_kind))

        return cls(
            unit_of_work_factory=service._unit_of_work_factory,  # type: ignore[attr-defined]
            now_ms=service._now_ms,  # type: ignore[attr-defined]
            enqueue_resume=coordinator.enqueue_resume,  # type: ignore[attr-defined]
            resolve_resume_authority=resolve_authority,
        )

    def __call__(self, command: ResumeRunCommand, *, request_id: str, resume_payload: dict[str, object] | None = None) -> ResumeRunResult:
        payload = {} if resume_payload is None else dict(resume_payload)
        authority = None
        if command.resume_kind in {"CONFIRMATION", "REAUTH_COMPLETED"}:
            authority = self._resolve_resume_authority(run_id=command.run_id, resume_kind=command.resume_kind)
        result = self._persist(command, authority=authority, resume_payload=payload)
        if result.applied and result.should_enqueue:
            self._enqueue_resume(
                run_id=command.run_id,
                request_id=request_id,
                command_id=command.command_id,
                resume_kind=command.resume_kind,
                resume_payload=payload,
            )
        return result

    def _persist(self, command: ResumeRunCommand, *, authority: ResumeAuthority | None, resume_payload: dict[str, object]) -> ResumeRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(ResumeRunResult, resolve_existing_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    response_type=ResumeRunResult,
                    run_id=command.run_id,
                    now_ms=self._now_ms(),
                ))
                return ResumeRunResult(**{**asdict(response), "should_enqueue": False, "request_replayed": True})

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResumeRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = unit_of_work.runs.get_by_id(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            plans = unit_of_work.plans.list_by_run(command.run_id)
            latest_plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
            actions = () if latest_plan is None else unit_of_work.actions.list_by_plan(latest_plan.id)
            unknown_result_exists = any(action.status == ActionStatus.UNKNOWN_RESULT.value for action in actions)

            response = self._validate(command, run, unknown_result_exists, authority, resume_payload)
            if response is None:
                decision = self._apply_canonical_transition(unit_of_work, command, run.version, authority)
                response = ResumeRunResult(
                    applied=decision.applied,
                    result_code=decision.result_code.value,
                    run_id=run.id,
                    run_status=decision.current_status.value,
                    run_version=decision.current_version,
                    should_enqueue=decision.applied,
                    request_replayed=False,
                    conflict_detail=decision.conflict_detail,
                )
            if response.applied:
                metadata = {"command_id": command.command_id, "resume_kind": command.resume_kind}
                unit_of_work.traces.add(TraceEventRecord(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_RESUMED",
                    status=response.run_status,
                    duration_ms=None,
                    payload_json=dumps(metadata, sort_keys=True),
                    created_at_ms=now_ms,
                ))
                unit_of_work.audits.add(AuditEventRecord(
                    account_id=None,
                    run_id=run.id,
                    action_id=None,
                    actor_type="USER",
                    actor_id="local_user",
                    actor_display=None,
                    event_type="RUN_RESUMED",
                    outcome=response.result_code,
                    metadata_json=dumps(metadata, sort_keys=True),
                    created_at_ms=now_ms,
                ))
            finish_json_receipt(unit_of_work, command.command_id, response, response.run_version, now_ms)
            unit_of_work.commit()
            return response

    @staticmethod
    def _validate(command: ResumeRunCommand, run: object, unknown_result_exists: bool, authority: ResumeAuthority | None, resume_payload: dict[str, object]) -> ResumeRunResult | None:
        status = run.status  # type: ignore[attr-defined]
        version = run.version  # type: ignore[attr-defined]
        if command.expected_run_version != version:
            return ResumeRunResult(False, ResultCode.VERSION_CONFLICT.value, command.run_id, status.value, version, False, False, "expected_run_version does not match current version")
        if unknown_result_exists and command.resume_kind != "RECOVERY_RECHECK":
            return ResumeRunResult(False, ResultCode.RECOVERY_REQUIRED.value, command.run_id, status.value, version, False, False, "unknown write results must be resolved before resume")
        allowed = {
            "CONFIRMATION": RunStatus.WAITING_CONFIRMATION,
            "REAUTH_COMPLETED": RunStatus.REAUTH_REQUIRED,
            "SAFE_CHECKPOINT_RESUME": RunStatus.BLOCKED,
            "RECOVERY_RECHECK": RunStatus.RECOVERY_REQUIRED,
        }
        if allowed.get(command.resume_kind) is not status:
            return ResumeRunResult(False, ResultCode.STATE_CONFLICT.value, command.run_id, status.value, version, False, False, "run status does not allow manual resume")
        if command.resume_kind in {"CONFIRMATION", "REAUTH_COMPLETED"}:
            if authority is None or not isinstance(authority.get("resume_status"), str):
                return ResumeRunResult(False, ResultCode.STATE_CONFLICT.value, command.run_id, status.value, version, False, False, "persisted resume authority is unavailable")
        if command.resume_kind == "CONFIRMATION":
            expected_interrupt = authority.get("interrupt_id") if authority is not None else None
            if not isinstance(expected_interrupt, str) or resume_payload.get("interrupt_id") != expected_interrupt:
                return ResumeRunResult(False, ResultCode.STATE_CONFLICT.value, command.run_id, status.value, version, False, False, "confirmation interrupt does not match persisted checkpoint authority")
        return None

    @staticmethod
    def _apply_canonical_transition(unit_of_work: UnitOfWork, command: ResumeRunCommand, current_version: int, authority: ResumeAuthority | None):
        if command.resume_kind == "CONFIRMATION":
            return unit_of_work.runs.resume_confirmation(command.run_id, expected_version=current_version, resume_status=RunStatus(cast(str, authority["resume_status"])))
        if command.resume_kind == "REAUTH_COMPLETED":
            return unit_of_work.runs.resume_after_reauth(command.run_id, expected_version=current_version, resume_status=RunStatus(cast(str, authority["resume_status"])))
        if command.resume_kind == "RECOVERY_RECHECK":
            return unit_of_work.runs.resolve_recovery(command.run_id, expected_version=current_version, recovery_next_status=RunStatus.VERIFYING)
        run = unit_of_work.runs.get_by_id(command.run_id)
        assert run is not None
        return _ordinary_resume_result(run)


def _ordinary_resume_result(run: object):
    from google_work_agent.domain import CommandResult
    return CommandResult(
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        current_status=run.status,  # type: ignore[attr-defined]
        current_version=run.version,  # type: ignore[attr-defined]
        next_allowed_commands=(),
        conflict_detail=None,
    )


__all__ = ["ResumeRunCommand", "ResumeRunHandler", "ResumeRunResult"]
