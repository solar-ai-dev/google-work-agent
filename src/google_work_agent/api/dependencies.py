"""FastAPI dependency helpers."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from google_work_agent.api.container import ApiContainer
from google_work_agent.api.errors import ApiError
from google_work_agent.api.route_dependencies import (
    ActionRouteDependencies,
    AttachmentRouteDependencies,
    ConversationRouteDependencies,
    EventRouteDependencies,
    GoogleRouteDependencies,
    HealthRouteDependencies,
    IdentityRouteDependencies,
    LLMRouteDependencies,
    ResourceRouteDependencies,
    RunRouteDependencies,
    RuntimeRouteDependencies,
    SafeModeRouteState,
    SessionRouteDependencies,
    SettingsRouteDependencies,
)
from google_work_agent.api.security.cookies import LOCAL_SESSION_COOKIE_NAME
from google_work_agent.application.readiness import compose_readiness
from google_work_agent.domain import calculate_canonical_json_hash
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
    ReadinessCheckResult,
    ReadinessState,
    RuntimeOperation,
)


def get_container(request: Request) -> ApiContainer:
    """Return the application container stored on `app.state`."""

    return cast("ApiContainer", request.app.state.container)


def get_health_route_dependencies(request: Request) -> HealthRouteDependencies:
    container = get_container(request)
    frontend = container.frontend_site
    safe_mode = container.safe_mode_controller
    return HealthRouteDependencies(
        service_instance_id=container.service_instance_id,
        release_version=container.release_version,
        api_contract_version=container.api_contract_version,
        clock=container.clock,
        readiness_aggregator=lambda: container.readiness_aggregator,
        launcher_probe_verifier=container.launcher_probe_verifier,
        frontend_readiness_check=(None if frontend is None else frontend.readiness_check),
        safe_mode_readiness_check=(None if safe_mode is None else safe_mode.readiness_check),
        additional_readiness_checks=container.additional_readiness_checks,
    )


def get_session_route_dependencies(request: Request) -> SessionRouteDependencies:
    container = get_container(request)
    return SessionRouteDependencies(
        service_instance_id=container.service_instance_id,
        api_contract_version=container.api_contract_version,
        clock=container.clock,
        bootstrap_grant_store=container.bootstrap_grant_store,
        local_session_manager=container.local_session_manager,
    )


def get_google_route_dependencies(request: Request) -> GoogleRouteDependencies:
    container = get_container(request)
    return GoogleRouteDependencies(
        api_contract_version=container.api_contract_version,
        start_google_oauth_service=lambda: container.start_google_oauth_service,
        get_google_connection_service=lambda: container.get_google_connection_service,
        disconnect_google_service=lambda: container.disconnect_google_service,
    )


def get_runtime_route_dependencies(request: Request) -> RuntimeRouteDependencies:
    container = get_container(request)

    def safe_mode_state() -> SafeModeRouteState | None:
        controller = container.safe_mode_controller
        if controller is None:
            return None
        state = controller.snapshot()
        return SafeModeRouteState(
            enabled=state.enabled,
            reason_codes=tuple(state.reason_codes),
            allowed_operations=tuple(item.value for item in state.allowed_operations),
        )

    return RuntimeRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        safe_mode_state=safe_mode_state,
    )


def get_identity_route_dependencies(request: Request) -> IdentityRouteDependencies:
    container = get_container(request)
    return IdentityRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
    )


def get_conversation_route_dependencies(request: Request) -> ConversationRouteDependencies:
    container = get_container(request)
    return ConversationRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        create_conversation_service=lambda: container.create_conversation_service,
    )


def get_run_route_dependencies(request: Request) -> RunRouteDependencies:
    from google_work_agent.application.write_actions import ResolveMismatchRecoveryService

    container = get_container(request)

    def resolve_recovery_service() -> ResolveMismatchRecoveryService:
        return container.resolve_recovery_service or ResolveMismatchRecoveryService(
            unit_of_work_factory=container.unit_of_work_factory,
            now_ms=container.clock.now_ms,
        )

    return RunRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        start_run_service=lambda: container.start_run_service,
        cancel_run_service=lambda: container.cancel_run_service,
        resume_run_service=lambda: container.resume_run_service,
        resolve_recovery_service=resolve_recovery_service,
        local_run_coordinator=container.local_run_coordinator,
        id_generator=container.id_generator,
    )


def get_action_route_dependencies(request: Request) -> ActionRouteDependencies:
    container = get_container(request)
    return ActionRouteDependencies(
        api_contract_version=container.api_contract_version,
        approve_action_service=lambda: container.approve_action_service,
        modify_action_service=lambda: container.modify_action_service,
        reject_action_service=lambda: container.reject_action_service,
        prepare_retry_service=lambda: container.prepare_retry_service,
        unit_of_work_factory=lambda: container.unit_of_work_factory(),
        local_run_coordinator=container.local_run_coordinator,
        event_publisher=lambda: container.event_publisher,
        clock=container.clock,
        id_generator=container.id_generator,
    )


def get_event_route_dependencies(request: Request) -> EventRouteDependencies:
    container = get_container(request)
    return EventRouteDependencies(
        api_contract_version=container.api_contract_version,
        query_service=lambda: container.query_service,
        event_publisher=lambda: container.event_publisher,
        clock=container.clock,
    )


def get_resource_route_dependencies(request: Request) -> ResourceRouteDependencies:
    container = get_container(request)
    return ResourceRouteDependencies(
        api_contract_version=container.api_contract_version,
        resource_query_service=lambda: container.resource_query_service,
    )


def get_settings_route_dependencies(request: Request) -> SettingsRouteDependencies:
    container = get_container(request)
    return SettingsRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_settings_service=lambda: container.get_settings_service,
        patch_settings_service=lambda: container.patch_settings_service,
        list_backups_service=lambda: container.list_backups_service,
        create_backup_service=lambda: container.create_backup_service,
        create_restore_plan_service=lambda: container.create_restore_plan_service,
        request_shutdown_service=lambda: container.request_shutdown_service,
    )


def get_llm_route_dependencies(request: Request) -> LLMRouteDependencies:
    container = get_container(request)
    return LLMRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_llm_connection_service=lambda: container.get_llm_connection_service,
        store_llm_api_key_service=lambda: container.store_llm_api_key_service,
        delete_llm_api_key_service=lambda: container.delete_llm_api_key_service,
        test_llm_connection_service=lambda: container.test_llm_connection_service,
    )


def get_attachment_route_dependencies(request: Request) -> AttachmentRouteDependencies:
    container = get_container(request)
    return AttachmentRouteDependencies(
        api_contract_version=lambda: container.api_contract_version,
        get_gmail_attachment_service=lambda: container.get_gmail_attachment_service,
        stage_attachment_service=lambda: container.stage_attachment_service,
    )


HealthRouteDependency = Annotated[HealthRouteDependencies, Depends(get_health_route_dependencies)]
SessionRouteDependency = Annotated[
    SessionRouteDependencies, Depends(get_session_route_dependencies)
]
GoogleRouteDependency = Annotated[GoogleRouteDependencies, Depends(get_google_route_dependencies)]
RuntimeRouteDependency = Annotated[
    RuntimeRouteDependencies, Depends(get_runtime_route_dependencies)
]
IdentityRouteDependency = Annotated[
    IdentityRouteDependencies, Depends(get_identity_route_dependencies)
]
ConversationRouteDependency = Annotated[
    ConversationRouteDependencies, Depends(get_conversation_route_dependencies)
]
RunRouteDependency = Annotated[RunRouteDependencies, Depends(get_run_route_dependencies)]
ActionRouteDependency = Annotated[ActionRouteDependencies, Depends(get_action_route_dependencies)]
EventRouteDependency = Annotated[EventRouteDependencies, Depends(get_event_route_dependencies)]
ResourceRouteDependency = Annotated[
    ResourceRouteDependencies, Depends(get_resource_route_dependencies)
]
SettingsRouteDependency = Annotated[
    SettingsRouteDependencies, Depends(get_settings_route_dependencies)
]
LLMRouteDependency = Annotated[LLMRouteDependencies, Depends(get_llm_route_dependencies)]
AttachmentRouteDependency = Annotated[
    AttachmentRouteDependencies, Depends(get_attachment_route_dependencies)
]


def get_request_id(request: Request) -> str:
    """Return the per-request identifier."""

    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str):
        return existing
    container = get_container(request)
    request_id = container.id_generator.next_id()
    request.state.request_id = request_id
    return request_id


def calculate_server_request_hash(*, operation: str, payload: dict[str, object]) -> str:
    """Hash the versioned request contract on the server, never a browser-provided hash."""

    return calculate_canonical_json_hash({"operation": operation, "payload": payload})


def composed_readiness_state(
    checks: tuple[ReadinessCheckResult, ...],
) -> ReadinessState:
    return compose_readiness(checks).state


def enforce_api_contract_version(
    *,
    container: ApiContainer,
    request_id: str,
    request_version: str | None,
) -> None:
    """Reject unsupported contract versions before application execution."""

    enforce_supported_api_contract_version(
        supported_version=container.api_contract_version,
        request_id=request_id,
        request_version=request_version,
    )


def enforce_supported_api_contract_version(
    *,
    supported_version: str,
    request_id: str,
    request_version: str | None,
) -> None:
    """Reject a request version that differs from the supplied API contract."""

    if request_version is None:
        return
    if request_version != supported_version:
        raise ApiError(
            error_code="VERSION_CONFLICT",
            user_message="지원하지 않는 API 계약 버전입니다.",
            status_code=409,
            request_id=request_id,
            detail_code="API_CONTRACT_VERSION_MISMATCH",
        )


def enforce_access(
    request: Request,
    *,
    policy: EndpointPolicy,
) -> None:
    """Authorize one request through the configured access guard."""

    container = get_container(request)
    request_id = get_request_id(request)
    client_address_resolver = container.client_address_resolver
    client_host = (
        client_address_resolver(request)
        if client_address_resolver is not None
        else None
        if request.client is None
        else request.client.host
    )
    decision = container.api_access_guard.authorize(
        ApiRequestContext(
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            client_host=client_host,
            host=request.headers.get("host"),
            origin=request.headers.get("origin"),
            content_type=request.headers.get("content-type"),
            content_length=_parse_content_length(request.headers.get("content-length")),
            session_token=request.cookies.get(LOCAL_SESSION_COOKIE_NAME),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
            sec_fetch_mode=request.headers.get("sec-fetch-mode"),
            sec_fetch_dest=request.headers.get("sec-fetch-dest"),
        ),
        endpoint_policy=policy,
    )
    _raise_if_denied(decision, request_id)


def enforce_runtime_operation(request: Request, *, operation: str) -> None:
    container = get_container(request)
    if container.core_initialization_in_progress:
        raise ApiError(
            error_code="SAFE_MODE",
            user_message="Core initialization is still in progress.",
            status_code=409,
            request_id=get_request_id(request),
            detail_code="SAFE_MODE_BLOCKED",
            current_state="CORE_INITIALIZING",
        )
    controller = container.safe_mode_controller
    if controller is None or controller.allows(RuntimeOperation(operation)):
        return
    state = controller.snapshot()
    raise ApiError(
        error_code="SAFE_MODE",
        user_message="현재 작업은 Safe Mode에서 허용되지 않습니다.",
        status_code=409,
        request_id=get_request_id(request),
        detail_code="SAFE_MODE_BLOCKED",
        current_state=",".join(state.reason_codes) if state.reason_codes else "SAFE_MODE",
    )


def _parse_content_length(content_length: str | None) -> int | None:
    if content_length is None or not content_length.isdigit():
        return None
    return int(content_length)


def _raise_if_denied(decision: AccessDecision, request_id: str) -> None:
    if decision.allowed:
        return
    raise ApiError(
        error_code=decision.error_code or "LOCAL_SESSION_INVALID",
        user_message=decision.user_message or "요청이 허용되지 않았습니다.",
        status_code=decision.status_code,
        request_id=request_id,
        retryable=decision.retryable,
        detail_code=decision.detail_code,
    )
