"""Test migration adapter for pre-canonical recovery integration scenarios."""

from dataclasses import dataclass
from types import SimpleNamespace

from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommandV1,
    ResolveRecoveryHandler,
)
from google_work_agent.domain.recovery.model import RecoveryResolution

RecoveryResolutionKind = RecoveryResolution


@dataclass(frozen=True, slots=True)
class ResolveMismatchRecoveryCommand:
    command_id: str
    request_hash: str
    run_id: str
    action_id: str
    expected_run_version: int
    resolution_kind: RecoveryResolution
    corrective_plan_id: str | None = None


class ResolveMismatchRecoveryService:
    """Keep historical scenarios exercising the canonical recovery owner."""

    def __init__(self, *, unit_of_work_factory, now_ms) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveMismatchRecoveryCommand):
        with self._unit_of_work_factory() as unit_of_work:
            receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            context = unit_of_work.recovery_contexts.load_current_context(command.run_id)
            run = unit_of_work.runs.get(command.run_id)
            if (
                receipt is None
                and context is None
                and run is not None
                and run.status.value in {"COMPLETED", "CANCELLED", "FAILED", "BLOCKED"}
            ):
                return SimpleNamespace(
                    applied=False,
                    result_code="STATE_CONFLICT",
                    result_kind=None,
                    plan_id=None,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_status=None,
                )
            if receipt is None and context is None:
                unit_of_work.recovery_contexts.store_context(
                    {
                        "schema_version": 1,
                        "run_id": command.run_id,
                        "reason": "VERIFICATION_MISMATCH",
                        "scope": "ACTION",
                        "pre_recovery_status": "VERIFYING",
                        "recovery_fingerprint": f"test:{command.action_id}",
                        "action_id": command.action_id,
                        "execution_attempt_id": f"test-attempt:{command.action_id}",
                        "verification_id": f"test-verification:{command.action_id}",
                        "observed_external_state_fingerprint": "test-observed",
                        "verification_input_fingerprint": "test-input",
                        "version": 0,
                        "created_at_ms": self._now_ms(),
                        "updated_at_ms": self._now_ms(),
                    }
                )
                unit_of_work.commit()
        result = ResolveRecoveryHandler(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
            next_id=(
                (lambda: f"message:{command.command_id}")
                if command.corrective_plan_id is None
                else lambda: command.corrective_plan_id
            ),
        )(
            ResolveRecoveryCommandV1(
                run_id=command.run_id,
                expected_version=command.expected_run_version,
                command_id=command.command_id,
                request_hash=command.request_hash,
                recovery_context_version=0 if context is None else int(context["version"]),
                resolution=command.resolution_kind,
                target_kind="ACTION",
                target_action_id=command.action_id,
            )
        )
        return SimpleNamespace(
            applied=result.applied,
            result_code=result.result_code,
            result_kind=result.result_kind,
            plan_id=result.plan_id,
            run_status=result.current_status,
            run_version=result.current_version,
            plan_status="DRAFT" if result.plan_id is not None else None,
        )


__all__ = [
    "RecoveryResolutionKind",
    "ResolveMismatchRecoveryCommand",
    "ResolveMismatchRecoveryService",
]
