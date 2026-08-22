from __future__ import annotations

from types import SimpleNamespace
from fastapi import FastAPI
from starlette.requests import Request
from tests.support.fakes import FakeClock

from google_work_agent.api.dependencies.runs import get_run_route_dependencies


def _request_with_run_composition() -> tuple[Request, object]:
    app = FastAPI()
    unit_of_work_factory = lambda: None
    app.state.container = SimpleNamespace(
        api_contract_version="1",
        query_service=SimpleNamespace(get_run_execution_context=lambda _run_id: None),
        unit_of_work_factory=unit_of_work_factory,
        start_run_service=object(),
        local_run_coordinator=object(),
        workflow_runtime=object(),
        clock=FakeClock(1),
        id_generator=object(),
    )
    return (
        Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [],
                "app": app,
            }
        ),
        unit_of_work_factory,
    )


def test_run_dependency_exposes_explicit_canonical_composition_inputs() -> None:
    request, unit_of_work_factory = _request_with_run_composition()
    dependencies = get_run_route_dependencies(request)

    assert dependencies.unit_of_work_factory is unit_of_work_factory
    assert dependencies.reserve_queue_slot is None
    assert dependencies.release_queue_slot is None


def test_run_dependency_resolver_fails_closed_without_checkpoint_authority() -> None:
    request, _unit_of_work_factory = _request_with_run_composition()
    dependencies = get_run_route_dependencies(request)

    assert (
        dependencies.resolve_resume_authority(
            run_id="run-1", resume_kind="CONFIRMATION"
        )
        is None
    )
