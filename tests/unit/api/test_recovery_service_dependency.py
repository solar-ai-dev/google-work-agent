from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from starlette.requests import Request
from tests.support.fakes import FakeClockPort

from google_work_agent.api.dependencies.runs import get_run_route_dependencies


def _request_with_run_composition() -> tuple[Request, object]:
    app = FastAPI()

    def unit_of_work_factory() -> None:
        return None

    app.state.container = SimpleNamespace(
        api_contract_version="1",
        current_account_id_provider=lambda: None,
        unit_of_work_factory=unit_of_work_factory,
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        resume_target_registry=object(),
        schedule_run_execution=object(),
        checkpoint_port=object(),
        workflow_runtime=object(),
        clock=FakeClockPort(1),
        id_generator=object(),
        resolve_selection_handle=object(),
        resource_connector_id="google-workspace",
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
    assert dependencies.graph_profile == "SIX_ROLE_BASELINE"
    assert dependencies.graph_version == "resume-contract-v1"


def test_run_dependency_resolver_fails_closed_without_checkpoint_authority() -> None:
    request, _unit_of_work_factory = _request_with_run_composition()
    dependencies = get_run_route_dependencies(request)

    assert dependencies.resolve_resume_authority(run_id="run-1", resume_kind="CONFIRMATION") is None
