from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClock

from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
    StaticRuntimeStatusProvider,
)
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer
from google_work_agent.application.queries import ActionSnapshot, RunSnapshot
from google_work_agent.application.start_run import ResumeRunResponse
from google_work_agent.application.use_cases.recovery.resolve_mismatch_recovery import (
    ResolveMismatchRecoveryResult,
)
from google_work_agent.application.use_cases.run.request_cancel import RequestCancelResult
from google_work_agent.application.write_actions import WriteRunResponse
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
    LauncherProbeDecision,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimeSummary,
)


class _CoordinatorStub:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.resume_calls: list[dict[str, object]] = []

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def enqueue_resume(self, **kwargs: object) -> None:
        self.resume_calls.append(dict(kwargs))

    def request_cancel(self, **kwargs: object) -> None:
        del kwargs


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
    database_path = Path("unused-test-query.db")
    connection_factory = staticmethod(lambda _path: None)

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
        create_conversation_handler=lambda command: command,
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
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
    )
    return container, coordinator


def test_app_lifespan_starts_and_stops_coordinator() -> None:
    container, coordinator = _build_container(_AllowGuard())

    with TestClient(create_app(container)) as client:
        response = client.get("/health/live")
        assert response.status_code == 200

    assert coordinator.started == 1
    assert coordinator.stopped == 1


def test_app_lifespan_runs_all_resource_cleanup_callbacks() -> None:
    container, _ = _build_container(_AllowGuard())
    cleaned: list[str] = []

    def close_first() -> None:
        cleaned.append("first")

    def close_second() -> None:
        cleaned.append("second")

    container = replace(container, shutdown_callbacks=(close_first, close_second))

    with TestClient(create_app(container)):
        pass

    assert cleaned == ["first", "second"]


def test_health_routes_and_runtime_respect_guard() -> None:
    container, _ = _build_container(_DenyGuard())

    with TestClient(create_app(container)) as client:
        live = client.get("/health/live")
        runtime = client.get("/api/v1/runtime")

    assert live.status_code == 401
    assert runtime.status_code == 401
    assert runtime.json()["error_code"] == "LOCAL_SESSION_INVALID"


def test_typed_confirmation_and_recovery_routes_derive_server_authority() -> None:
    container, coordinator = _build_container(_AllowGuard())
    captured: dict[str, object] = {}

    def resume_service(command: object) -> ResumeRunResponse:
        captured["resume"] = command
        return ResumeRunResponse(
            applied=True,
            result_code="TRANSITION_APPLIED",
            run_id="run-1",
            run_status="WAITING_CONFIRMATION",
            run_version=2,
            should_enqueue=True,
            request_replayed=False,
        )

    def recovery_service(command: object) -> WriteRunResponse:
        captured["recovery"] = command
        return WriteRunResponse(
            applied=True,
            result_code="TRANSITION_APPLIED",
            run_id="run-1",
            run_status="COMPLETED",
            run_version=3,
            plan_id="plan-1",
            plan_status="COMPLETED",
            result_kind="PARTIAL",
        )

    container = replace(
        container,
        resume_run_service=resume_service,
        resolve_recovery_service=recovery_service,
    )

    def resume_handler(
        command: object,
        *,
        request_id: str,
        resume_payload: dict[str, object] | None = None,
    ) -> ResumeRunResponse:
        result = resume_service(command)
        coordinator.enqueue_resume(
            run_id="run-1",
            request_id=request_id,
            command_id="confirm-1",
            resume_kind="CONFIRMATION",
            resume_payload=resume_payload or {},
        )
        return result

    def recovery_handler(
        command: object, *, request_id: str
    ) -> ResolveMismatchRecoveryResult:
        del request_id
        legacy = recovery_service(command)
        return ResolveMismatchRecoveryResult(
            applied=legacy.applied,
            result_code=legacy.result_code,
            run_id=legacy.run_id,
            current_status=legacy.run_status,
            current_version=legacy.run_version,
            conflict_detail=legacy.conflict_detail,
            result_kind=legacy.result_kind,
            plan_id=legacy.plan_id,
        )

    with (
        patch(
            "google_work_agent.api.routes.runs.ResumeRunHandler",
            return_value=resume_handler,
        ),
        patch(
            "google_work_agent.api.routes.runs.ResolveMismatchRecoveryHandler",
            return_value=recovery_handler,
        ),
        TestClient(create_app(container)) as client,
    ):
        confirmed = client.post(
            "/api/v1/runs/run-1/confirm",
            json={
                "command_id": "confirm-1",
                "expected_version": 2,
                "interrupt_id": "interrupt-1",
                "response_kind": "FREE_TEXT",
                "selected_option_ids": [],
                "free_text": "Use the default list.",
                "api_contract_version": "1",
            },
        )
        resolved = client.post(
            "/api/v1/runs/run-1/resolve-recovery",
            json={
                "command_id": "recovery-1",
                "expected_version": 2,
                "action_id": "action-1",
                "resolution_kind": "ACCEPT_PARTIAL",
                "api_contract_version": "1",
            },
        )

    assert confirmed.status_code == 200
    assert resolved.status_code == 200
    assert captured["resume"].request_hash != "confirm-1"  # type: ignore[attr-defined]
    assert captured["recovery"].request_hash != "recovery-1"  # type: ignore[attr-defined]
    assert coordinator.resume_calls[0]["resume_payload"] == {
        "schema_version": 1,
        "interrupt_id": "interrupt-1",
        "response_kind": "FREE_TEXT",
        "selected_option_ids": [],
        "free_text": "Use the default list.",
    }


def test_cancel_route_returns_partial_result_projection() -> None:
    container, _ = _build_container(_AllowGuard())

    def cancel_service(_command: object) -> WriteRunResponse:
        return WriteRunResponse(
            applied=True,
            result_code="TRANSITION_APPLIED",
            run_id="run-1",
            run_status="CANCELLED",
            run_version=4,
            plan_id="plan-1",
            plan_status="CANCELLED",
            result_kind="PARTIAL",
        )

    container = replace(container, cancel_run_service=cancel_service)

    def cancel_handler(command: object, request_id: str) -> RequestCancelResult:
        del request_id
        legacy = cancel_service(command)
        return RequestCancelResult(
            applied=legacy.applied,
            result_code=legacy.result_code,
            current_status=legacy.run_status,
            current_version=legacy.run_version,
            next_allowed_commands=(),
            conflict_detail=legacy.conflict_detail,
            result_kind=legacy.result_kind,
        )

    with (
        patch(
            "google_work_agent.api.routes.runs.RequestCancelHandler",
            return_value=cancel_handler,
        ),
        TestClient(create_app(container)) as client,
    ):
        response = client.post(
            "/api/v1/runs/run-1/cancel",
            json={
                "command_id": "cancel-1",
                "expected_run_version": 3,
                "api_contract_version": "1",
            },
        )

    assert response.status_code == 200
    assert response.json()["result_kind"] == "PARTIAL"


def test_run_snapshot_rest_projection_includes_structured_action_risk() -> None:
    container, _ = _build_container(_AllowGuard())
    risk: dict[str, object] = {"validator": {"outcome": "WARNING"}}
    snapshot = RunSnapshot(
        run_id="run-1",
        conversation_id="conversation-1",
        status="WAITING_APPROVAL",
        version=1,
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        actual_runtime="API_LLM",
        started_at_ms=1,
        finished_at_ms=None,
        active_plan={"plan_id": "plan-1"},
        actions=(
            ActionSnapshot(
                action_id="action-1",
                tool_name="tasks_create_task",
                status="PROPOSED",
                version=0,
                effect_type="CREATE",
                approval_required=True,
                verification_policy="GET_COMPARE",
                risk=risk,
                next_allowed_commands=("APPROVE",),
            ),
        ),
        approvals=(),
        execution_status={"action_count": 1, "terminal_action_count": 0},
        verification_summary={"verified_count": 0, "mismatch_count": 0},
        recovery_summary={"unknown_result_action_count": 0},
        result_kind=None,
        next_allowed_commands=("REQUEST_CANCEL",),
        snapshot_version=1,
    )

    class _RunQueryStub(_QueryStub):
        def get_run_snapshot(self, run_id: str) -> RunSnapshot | None:
            return snapshot if run_id == "run-1" else None

    container = replace(container, query_service=_RunQueryStub())
    with (
        patch(
            "google_work_agent.api.routes.runs.GetRunSnapshotHandler",
            return_value=lambda query: snapshot if query.run_id == "run-1" else None,
        ),
        TestClient(create_app(container)) as client,
    ):
        response = client.get("/api/v1/runs/run-1")

    assert response.status_code == 200
    assert response.json()["snapshot"]["actions"][0]["risk"] == risk


def test_runtime_mutation_routes_reject_browser_authority_and_arbitrary_resume() -> None:
    container, _ = _build_container(_AllowGuard())
    with TestClient(create_app(container)) as client:
        approval = client.post(
            "/api/v1/actions/action-1/approve",
            json={
                "command_id": "approve-1",
                "expected_version": 1,
                "approved_by_account_id": "browser-account",
                "api_contract_version": "1",
            },
        )
        resume = client.post(
            "/api/v1/runs/run-1/resume",
            json={
                "command_id": "resume-1",
                "expected_version": 1,
                "resume_kind": "RECOVERY_RECHECK",
                "resume_payload": {"arbitrary": True},
                "api_contract_version": "1",
            },
        )
        invalid_recovery = client.post(
            "/api/v1/runs/run-1/resolve-recovery",
            json={
                "command_id": "recovery-1",
                "expected_version": 1,
                "action_id": "action-1",
                "resolution_kind": "RETRY_WRITE",
                "api_contract_version": "1",
            },
        )

    assert approval.status_code == 422
    assert resume.status_code == 422
    assert invalid_recovery.status_code == 422


def test_ready_route_fails_closed_without_launcher_probe_verifier() -> None:
    container, _ = _build_container(_AllowGuard())
    container = replace(container, launcher_probe_verifier=None)

    with TestClient(create_app(container)) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "NOT_READY"
    assert any(check["name"] == "launcher_probe" for check in payload["checks"])
