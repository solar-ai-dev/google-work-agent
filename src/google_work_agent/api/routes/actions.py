"""Existing action command routes."""

from collections.abc import Iterable
from typing import cast

from fastapi import APIRouter, Request, Response

from google_work_agent.api.dependencies import (
    ActionRouteDependency,
    calculate_server_request_hash,
    enforce_access,
    enforce_runtime_operation,
    enforce_supported_api_contract_version,
)
from google_work_agent.api.errors import ApiError, http_status_for_result_code
from google_work_agent.api.route_dependencies import ActionRouteDependencies
from google_work_agent.api.schemas.actions import (
    ActionCommandResponse,
    ApproveActionRequestV2,
    ModifyActionRequestV2,
    PrepareRetryRequestV2,
    RejectActionRequestV2,
)
from google_work_agent.application.coordinator import QueueBusyError
from google_work_agent.application.projections import build_snapshot_required_event
from google_work_agent.application.start_run import (
    ModifyWriteActionCommand,
    RejectWriteActionCommand,
)
from google_work_agent.ports import EndpointPolicy, PlanReviewStatus

router = APIRouter(prefix="/api/v1/actions")


@router.post("/{action_id}/approve", response_model=ActionCommandResponse)
def approve(
    action_id: str,
    request: Request,
    payload: ApproveActionRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="APPROVALS")
    from google_work_agent.application.write_actions import ApproveWriteActionCommand

    settings_service = dependencies.get_settings_service()
    if settings_service is None:
        raise RuntimeError("get_settings_service is not configured")
    approval_ttl_ms = settings_service().approval_ttl_minutes * 60_000
    if approval_ttl_ms <= 0:
        raise RuntimeError("approval_ttl_minutes must be positive")

    approved_by_account_id, run_id = _account_and_run_id_for_action(dependencies, action_id)
    request_payload = payload.model_dump()
    request_payload.pop("ttl_ms", None)
    result = dependencies.approve_action_service()(
        ApproveWriteActionCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ApproveActionRequestV2",
                payload={"action_id": action_id, **request_payload},
            ),
            action_id=action_id,
            expected_version=payload.expected_version,
            approved_by_account_id=approved_by_account_id,
            approved_by_display=None,
            source_snapshot={},
            approval_id=dependencies.id_generator.next_id(),
            idempotency_key=calculate_server_request_hash(
                operation="ApproveActionIdempotencyKeyV1",
                payload={"action_id": action_id, "command_id": payload.command_id},
            ),
            ttl_ms=approval_ttl_ms,
            duplicate_acknowledged=payload.duplicate_acknowledged,
            calendar_conflict_acknowledged=payload.calendar_conflict_acknowledged,
        )
    )
    if result.applied:
        try:
            dependencies.local_run_coordinator.enqueue_resume(
                run_id=run_id,
                request_id=request.state.request_id,
                command_id=payload.command_id,
                resume_kind="APPROVAL",
                resume_payload={"approved": True},
            )
        except QueueBusyError as error:
            raise ApiError(
                error_code="SERVICE_BUSY",
                user_message="The approval was saved, but runtime execution is still queued.",
                status_code=503,
                request_id=request.state.request_id,
                retryable=True,
                detail_code=type(error).__name__,
                current_state=result.action_status,
            ) from error
    response.status_code = http_status_for_result_code(result.result_code)
    return ActionCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        action_id=result.action_id,
        action_status=result.action_status,
        action_version=result.action_version,
        next_allowed_commands=list(result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )


def _account_and_run_id_for_action(
    dependencies: ActionRouteDependencies, action_id: str
) -> tuple[str, str]:
    with dependencies.unit_of_work_factory() as unit_of_work:
        action = unit_of_work.actions.get_by_id(action_id)
        if action is None:
            raise LookupError(f"action not found: {action_id}")
        plan = unit_of_work.plans.get_by_id(action.plan_id)
        if plan is None:
            raise LookupError(f"plan not found: {action.plan_id}")
        run = unit_of_work.runs.get_by_id(plan.run_id)
        if run is None:
            raise LookupError(f"run not found: {plan.run_id}")
        conversation = unit_of_work.conversations.get_by_id(run.conversation_id)
        if conversation is None:
            raise LookupError(f"conversation not found: {run.conversation_id}")
        return conversation.account_id, run.id


@router.post("/{action_id}/modify", response_model=ActionCommandResponse)
def modify(
    action_id: str,
    request: Request,
    payload: ModifyActionRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="APPROVALS")
    result = dependencies.modify_action_service()(
        ModifyWriteActionCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ModifyActionRequestV2",
                payload={"action_id": action_id, **payload.model_dump()},
            ),
            action_id=action_id,
            expected_version=payload.expected_version,
            arguments_patch=dict(payload.arguments_patch),
        )
    )
    if bool(result["applied"]):
        _, run_id = _account_and_run_id_for_action(dependencies, action_id)
        with dependencies.unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get_by_id(action_id)
            if action is None:
                raise LookupError(f"action not found: {action_id}")
            plan = unit_of_work.plans.get_by_id(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
        if plan.review_status is PlanReviewStatus.REQUIRED:
            try:
                dependencies.local_run_coordinator.enqueue_resume(
                    run_id=run_id,
                    request_id=request.state.request_id,
                    command_id=payload.command_id,
                    resume_kind="MODIFY_REVIEW",
                    resume_payload={
                        "resume_kind": "MODIFY_REVIEW",
                        "plan_id": plan.id,
                        "review_version": plan.review_version,
                    },
                )
            except QueueBusyError as error:
                raise ApiError(
                    error_code="SERVICE_BUSY",
                    user_message="The action was modified, but plan review is still queued.",
                    status_code=503,
                    request_id=request.state.request_id,
                    retryable=True,
                    detail_code=type(error).__name__,
                    current_state=str(result["action_status"]),
                ) from error
    response.status_code = http_status_for_result_code(str(result["result_code"]))
    return ActionCommandResponse(
        applied=bool(result["applied"]),
        result_code=str(result["result_code"]),
        action_id=str(result["action_id"]),
        action_status=str(result["action_status"]),
        action_version=int(cast(int | str, result["action_version"])),
        next_allowed_commands=[
            str(item) for item in cast(Iterable[object], result["next_allowed_commands"])
        ],
        conflict_detail=None
        if result["conflict_detail"] is None
        else str(result["conflict_detail"]),
    )


@router.post("/{action_id}/reject", response_model=ActionCommandResponse)
def reject(
    action_id: str,
    request: Request,
    payload: RejectActionRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="APPROVALS")
    actor_account_id, run_id = _account_and_run_id_for_action(dependencies, action_id)
    result = dependencies.reject_action_service()(
        RejectWriteActionCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="RejectActionRequestV2",
                payload={"action_id": action_id, **payload.model_dump()},
            ),
            action_id=action_id,
            expected_version=payload.expected_version,
            actor_account_id=actor_account_id,
            reason_code=payload.reason_code,
        )
    )
    if bool(result["applied"]):
        dependencies.event_publisher().publish(
            build_snapshot_required_event(
                run_id=run_id,
                occurred_at_ms=dependencies.clock.now_ms(),
                reason="ACTION_REJECTED",
            )
        )
    response.status_code = http_status_for_result_code(str(result["result_code"]))
    return ActionCommandResponse(
        applied=bool(result["applied"]),
        result_code=str(result["result_code"]),
        action_id=str(result["action_id"]),
        action_status=str(result["action_status"]),
        action_version=int(cast(int | str, result["action_version"])),
        next_allowed_commands=[
            str(item) for item in cast(Iterable[object], result["next_allowed_commands"])
        ],
        conflict_detail=None
        if result["conflict_detail"] is None
        else str(result["conflict_detail"]),
    )


@router.post("/{action_id}/prepare-retry", response_model=ActionCommandResponse)
def prepare_retry(
    action_id: str,
    request: Request,
    payload: PrepareRetryRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="APPROVALS")
    from google_work_agent.application.write_actions import PrepareWriteRetryCommand

    result = dependencies.prepare_retry_service()(
        PrepareWriteRetryCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="PrepareRetryRequestV2",
                payload={"action_id": action_id, **payload.model_dump()},
            ),
            action_id=action_id,
            expected_action_version=payload.expected_action_version,
        )
    )
    response.status_code = http_status_for_result_code(result.result_code)
    return ActionCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        action_id=result.action_id,
        action_status=result.action_status,
        action_version=result.action_version,
        next_allowed_commands=list(result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )
