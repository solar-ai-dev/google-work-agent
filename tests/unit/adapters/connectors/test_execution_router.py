from collections.abc import Callable
from typing import cast

import pytest

from google_work_agent.adapters.connectors.execution_router import (
    ConnectorExecutionRouter,
    bind_execution_connector_id,
)
from google_work_agent.adapters.langgraph.connector_execution_scope import (
    ConnectorBoundWriteExecutionPhaseCoordinator,
)
from google_work_agent.application.execution_phase import (
    WriteExecutionDisposition,
    WriteExecutionPhaseCoordinator,
    WriteExecutionPhaseRequest,
    WriteExecutionPhaseResult,
)
from google_work_agent.application.ports import ConnectorWriteRequest, PreparedConnectorWrite
from google_work_agent.ports import ResourceSnapshot, UnitOfWork


class _FakeExecutionBackend:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[str] = []
        self.last_request_id = f"request-{name}"
        self.snapshot = cast(ResourceSnapshot, object())

    def prepare_write(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        recovery_fingerprint: str | None,
    ) -> PreparedConnectorWrite:
        self.calls.append(f"prepare:{tool_name}")
        return PreparedConnectorWrite(tool_name=tool_name, arguments=dict(arguments))

    def execute_write(self, request: ConnectorWriteRequest) -> ResourceSnapshot:
        self.calls.append(f"execute:{request.prepared.tool_name}")
        return self.snapshot

    def fetch_verification_snapshot(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        fallback_resource_id: str | None,
    ) -> ResourceSnapshot:
        self.calls.append(f"verify:{tool_name}")
        return self.snapshot

    def search_recovery_candidates(
        self,
        *,
        tool_name: str,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        self.calls.append(f"recover:{tool_name}")
        return (self.snapshot,)


class _ConnectorActionRepository:
    def __init__(self, connector_id: str) -> None:
        self._connector_id = connector_id

    def connector_id_for_action(self, action_id: str) -> str:
        assert action_id == "action-1"
        return self._connector_id


class _ConnectorUnitOfWork:
    def __init__(self, connector_id: str) -> None:
        self.actions = _ConnectorActionRepository(connector_id)

    def __enter__(self) -> "_ConnectorUnitOfWork":
        return self

    def __exit__(self, exc_type: object, exc: object, exc_tb: object) -> None:
        return None


class _PhaseDelegate:
    def __init__(self, router: ConnectorExecutionRouter) -> None:
        self._router = router

    def execute(self, request: WriteExecutionPhaseRequest) -> WriteExecutionPhaseResult:
        self._router.prepare_write(
            tool_name="github_create_issue",
            arguments={"title": request.action_id},
            recovery_fingerprint=None,
        )
        return WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.VERIFIED,
            action_status="VERIFIED",
        )


def test_router_dispatches_only_to_bound_connector() -> None:
    google = _FakeExecutionBackend("google")
    github = _FakeExecutionBackend("github")
    router = ConnectorExecutionRouter(
        {"google_workspace": google, "github": github}
    )

    with bind_execution_connector_id("github"):
        prepared = router.prepare_write(
            tool_name="github_create_issue",
            arguments={"title": "x"},
            recovery_fingerprint=None,
        )
        assert prepared.tool_name == "github_create_issue"
        assert router.last_request_id == "request-github"

    assert google.calls == []
    assert github.calls == ["prepare:github_create_issue"]


def test_router_fails_closed_without_bound_connector() -> None:
    router = ConnectorExecutionRouter(
        {"google_workspace": _FakeExecutionBackend("google")}
    )

    with pytest.raises(RuntimeError, match="without a bound connector"):
        router.prepare_write(
            tool_name="tasks_create_task",
            arguments={},
            recovery_fingerprint=None,
        )


def test_router_fails_closed_for_unregistered_connector() -> None:
    router = ConnectorExecutionRouter(
        {"google_workspace": _FakeExecutionBackend("google")}
    )

    with bind_execution_connector_id("github"):
        with pytest.raises(LookupError, match="backend not registered: github"):
            router.fetch_verification_snapshot(
                tool_name="github_create_issue",
                arguments={},
                fallback_resource_id="issue-1",
            )


def test_phase_scope_routes_from_persisted_action_connector() -> None:
    google = _FakeExecutionBackend("google")
    github = _FakeExecutionBackend("github")
    router = ConnectorExecutionRouter(
        {"google_workspace": google, "github": github}
    )
    delegate = cast(WriteExecutionPhaseCoordinator, _PhaseDelegate(router))
    factory = cast(
        Callable[[], UnitOfWork],
        lambda: _ConnectorUnitOfWork("github"),
    )
    coordinator = ConnectorBoundWriteExecutionPhaseCoordinator(
        delegate=delegate,
        unit_of_work_factory=factory,
    )

    result = coordinator.execute(
        WriteExecutionPhaseRequest(
            run_id="run-1",
            action_id="action-1",
            action_version=0,
        )
    )

    assert result.disposition is WriteExecutionDisposition.VERIFIED
    assert google.calls == []
    assert github.calls == ["prepare:github_create_issue"]
