"""Enforce the API-visible runtime operation gate."""

from fastapi import Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.ports import RuntimeOperation


def enforce_runtime_operation(request: Request, *, operation: str) -> None:
    container = get_api_container(request)
    if container.core_initialization_in_progress:
        raise ApiRequestError(
            error_code="SAFE_MODE",
            user_message="Core initialization is still in progress.",
            status_code=409,
            request_id=_request_id(request),
            detail_code="SAFE_MODE_BLOCKED",
            current_state="CORE_INITIALIZING",
        )
    controller = container.safe_mode_controller
    if controller is None or controller.allows(RuntimeOperation(operation)):
        return
    state = controller.snapshot()
    raise ApiRequestError(
        error_code="SAFE_MODE",
        user_message="현재 작업은 Safe Mode에서 허용되지 않습니다.",
        status_code=409,
        request_id=_request_id(request),
        detail_code="SAFE_MODE_BLOCKED",
        current_state=",".join(state.reason_codes) if state.reason_codes else "SAFE_MODE",
    )


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str):
        return request_id
    request_id = get_api_container(request).id_generator.new_uuid()
    request.state.request_id = request_id
    return request_id
