from dataclasses import dataclass

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClock

from google_work_agent.adapters.readiness.composite import (
    StaticReadinessAggregator,
    StaticRuntimeStatusProvider,
)
from google_work_agent.api import ApiContainer, create_app
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimeSummary,
)


class _CoordinatorStub:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _AllowGuard:
    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        del request_context, endpoint_policy
        return AccessDecision(allowed=True)


class _DenyGuard:
    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        del request_context, endpoint_policy
        return AccessDecision(
            allowed=False,
            status_code=401,
            error_code="LOCAL_SESSION_INVALID",
            user_message="session required",
        )


@dataclass
class _QueryStub:
    def get_runtime_summary(self) -> RuntimeSummary:
        return RuntimeSummary(
            google="NOT_CONFIGURED",
            mcp="NOT_CONFIGURED",
            api_llm="NOT_CONFIGURED",
            ollama="NOT_AVAILABLE",
            deployment_profile="test",
            recovery_required_run_ids=(),
            open_run_ids=(),
        )


def _build_container(guard: _AllowGuard | _DenyGuard) -> tuple[ApiContainer, _CoordinatorStub]:
    coordinator = _CoordinatorStub()
    container = ApiContainer(
        unit_of_work_factory=lambda: None,
        query_service=_QueryStub(),
        create_conversation_service=lambda command: command,
        start_run_service=lambda command: command,
        approve_action_service=lambda command: command,
        modify_action_service=lambda command: command,
        reject_action_service=lambda command: command,
        prepare_retry_service=lambda command: command,
        cancel_run_service=lambda command: command,
        resume_run_service=lambda command: command,
        local_run_coordinator=coordinator,
        workflow_runtime=type("Runtime", (), {"close": lambda self: None})(),
        event_publisher=type(
            "Publisher",
            (),
            {
                "replay": lambda self, **kwargs: (),
                "subscribe": lambda self, run_id: type(
                    "Subscription",
                    (),
                    {"poll": lambda self, timeout_seconds: None},
                )(),
                "close_subscription": lambda self, subscription: None,
                "publish": lambda self, event: None,
            },
        )(),
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(
                state=ReadinessState.READY,
                checks=(
                    ReadinessCheckResult(name="sqlite_connection", state=ReadinessState.READY),
                ),
            )
        ),
        runtime_status_provider=StaticRuntimeStatusProvider(
            RuntimeSummary(
                google="NOT_CONFIGURED",
                mcp="NOT_CONFIGURED",
                api_llm="NOT_CONFIGURED",
                ollama="NOT_AVAILABLE",
                deployment_profile="test",
                recovery_required_run_ids=(),
                open_run_ids=(),
            )
        ),
        api_access_guard=guard,
        clock=FakeClock(100),
        id_generator=DeterministicUUID(prefix="req"),
        release_version="test",
        environment="test",
        service_instance_id="svc-test",
    )
    return container, coordinator


def test_app_lifespan_starts_and_stops_coordinator() -> None:
    container, coordinator = _build_container(_AllowGuard())

    with TestClient(create_app(container)) as client:
        response = client.get("/health/live")
        assert response.status_code == 200

    assert coordinator.started == 1
    assert coordinator.stopped == 1


def test_health_routes_bypass_guard_but_runtime_requires_guard() -> None:
    container, _ = _build_container(_DenyGuard())

    with TestClient(create_app(container)) as client:
        live = client.get("/health/live")
        runtime = client.get("/api/v1/runtime")

    assert live.status_code == 200
    assert runtime.status_code == 401
    assert runtime.json()["error_code"] == "LOCAL_SESSION_INVALID"
