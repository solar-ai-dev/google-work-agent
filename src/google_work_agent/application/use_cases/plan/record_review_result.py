"""Persist one freshness-bound, deterministic Plan review result."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from json import dumps, loads
from typing import Literal

from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import PlanReviewStatus
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.persistence.plan_repository import load_plan_record
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

ReviewDispositionV1 = Literal[
    "PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM", "BLOCK"
]


@dataclass(frozen=True, slots=True)
class RecordReviewResultCommandV1:
    command_id: str
    plan_id: str
    expected_plan_version: int
    expected_review_version: int
    review_artifact_id: str
    review_version: int
    disposition: ReviewDispositionV1
    based_on_action_versions: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class RecordReviewResultResultV1:
    applied: bool
    result_code: str
    current_plan_version: int
    recorded_review_version: int | None
    conflict_detail: str | None = None


class RecordReviewResultHandler:
    """The sole Application writer for the durable current-review gate."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RecordReviewResultCommandV1) -> RecordReviewResultResultV1:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay(existing, command)

            now_ms = self._now_ms()
            plan = load_plan_record(unit_of_work.plans, command.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {command.plan_id}")
            if unit_of_work.runs.get(plan.run_id) is None:
                raise LookupError(f"plan owner Run not found: {plan.run_id}")
            conflict = _freshness_conflict(unit_of_work, plan.id, command)
            if conflict is not None:
                result = RecordReviewResultResultV1(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    current_plan_version=plan.revision_no,
                    recorded_review_version=None,
                    conflict_detail=conflict,
                )
                self._finish(unit_of_work, command, result, now_ms)
                return result

            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RecordReviewResult",
                request_hash=_request_hash(command),
                aggregate_type="Plan",
                aggregate_id=plan.id,
                created_at_ms=now_ms,
            )
            if command.disposition != "PASS":
                for approval in unit_of_work.approvals.list_active_for_plan(plan.id):
                    if not unit_of_work.approvals.update_if_status(
                        approval.id,
                        ApprovalStatusV1.ACTIVE,
                        {"status": ApprovalStatusV1.REVOKED},
                    ):
                        raise RuntimeError(
                            f"validated review Approval revoke CAS failed: {approval.id}"
                        )
                    unit_of_work.audits.append(
                        AuditEventRecord(
                            account_id=None,
                            run_id=plan.run_id,
                            action_id=approval.action_id,
                            actor_type="SYSTEM",
                            actor_id="plan_review",
                            actor_display="Plan review",
                            event_type="APPROVAL_REVOKED",
                            outcome=ResultCode.TRANSITION_APPLIED.value,
                            metadata_json=dumps(
                                {
                                    "approval_id": approval.id,
                                    "command_id": command.command_id,
                                    "reason": "NON_PASS_REVIEW",
                                },
                                sort_keys=True,
                            ),
                            created_at_ms=now_ms,
                        )
                    )
            review_status = _review_status(command.disposition)
            updated = unit_of_work.plans.record_review_result(
                plan.id,
                expected_review_version=command.expected_review_version,
                expected_review_statuses=frozenset({PlanReviewStatus.REQUIRED}),
                values={
                    "review_status": review_status,
                    "review_disposition": command.disposition,
                },
            )
            if updated is None:
                result = RecordReviewResultResultV1(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    current_plan_version=plan.revision_no,
                    recorded_review_version=None,
                    conflict_detail="review generation is no longer current",
                )
                self._finish(unit_of_work, command, result, now_ms)
                return result

            unit_of_work.audits.append(
                AuditEventRecord(
                    account_id=None,
                    run_id=plan.run_id,
                    action_id=None,
                    actor_type="SYSTEM",
                    actor_id="plan_review",
                    actor_display="Plan review",
                    event_type="REVIEW_RESULT_RECORDED",
                    outcome=command.disposition,
                    metadata_json=dumps(
                        {
                            "command_id": command.command_id,
                            "plan_id": plan.id,
                            "review_artifact_id": command.review_artifact_id,
                            "review_version": command.review_version,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            result = RecordReviewResultResultV1(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                current_plan_version=plan.revision_no,
                recorded_review_version=command.review_version,
            )
            self._finish(unit_of_work, command, result, now_ms)
            return result

    @staticmethod
    def _replay(
        receipt: object, command: RecordReviewResultCommandV1
    ) -> RecordReviewResultResultV1:
        request_hash = _request_hash(command)
        if receipt.request_hash != request_hash:  # type: ignore[attr-defined]
            return RecordReviewResultResultV1(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                current_plan_version=command.expected_plan_version,
                recorded_review_version=None,
                conflict_detail="command_id already exists with a different request",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:  # type: ignore[attr-defined]
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        return RecordReviewResultResultV1(**loads(receipt.response_json))  # type: ignore[attr-defined]

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        command: RecordReviewResultCommandV1,
        result: RecordReviewResultResultV1,
        now_ms: int,
    ) -> None:
        if unit_of_work.command_receipts.get_by_command_id(command.command_id) is None:
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RecordReviewResult",
                request_hash=_request_hash(command),
                aggregate_type="Plan",
                aggregate_id=command.plan_id,
                created_at_ms=now_ms,
            )
        unit_of_work.command_receipts.store_result(
            command_id=command.command_id,
            applied=result.applied,
            result_code=ResultCode(result.result_code),
            result_version=result.current_plan_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=now_ms,
        )
        unit_of_work.commit()


def _freshness_conflict(
    unit_of_work: UnitOfWork, plan_id: str, command: RecordReviewResultCommandV1
) -> str | None:
    plan = load_plan_record(unit_of_work.plans, plan_id)
    assert plan is not None
    if plan.revision_no != command.expected_plan_version:
        return "plan version is stale"
    if (
        plan.review_version != command.expected_review_version
        or plan.review_version != command.review_version
    ):
        return "review version is stale"
    if plan.review_status is not PlanReviewStatus.REQUIRED:
        return "plan is not awaiting a fresh review"
    current = {action.id: action.version for action in unit_of_work.actions.list_for_plan(plan_id)}
    if current != dict(command.based_on_action_versions):
        return "review action versions are stale"
    return None


def _review_status(disposition: ReviewDispositionV1) -> PlanReviewStatus:
    return PlanReviewStatus.PASSED if disposition == "PASS" else PlanReviewStatus.REQUIRED


def _request_hash(command: RecordReviewResultCommandV1) -> str:
    return calculate_canonical_json_hash(asdict(command))
