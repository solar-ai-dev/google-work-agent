from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from starlette.requests import Request

from google_work_agent.api.dependencies.runs import get_run_route_dependencies


def _request_with_run_composition() -> tuple[Request, SimpleNamespace]:
    app = FastAPI()

    def unit_of_work_factory() -> None:
        return None

    container = SimpleNamespace(
        api_contract_version="1",
        service_instance_id="svc-test",
        current_account_id_provider=lambda: None,
        unit_of_work_factory=unit_of_work_factory,
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        schedule_run_execution=object(),
        resolve_selection_handle=object(),
        resource_connector_id="google-workspace",
        request_cancel_handler=object(),
        resume_safe_checkpoint_handler=object(),
        resume_after_reauth_handler=object(),
        resolve_recovery_handler=object(),
        confirm_run_handler=object(),
        get_execution_context_handler=object(),
    )
    app.state.container = container
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
        container,
    )


def test_run_dependency__exposes_explicit__canonical_composition_inputs() -> None:
    request, container = _request_with_run_composition()
    dependencies = get_run_route_dependencies(request)

    assert dependencies.graph_profile == "SIX_ROLE_BASELINE"
    assert dependencies.graph_version == "resume-contract-v1"
    assert dependencies.request_cancel_handler is container.request_cancel_handler
    assert dependencies.resume_safe_checkpoint_handler is container.resume_safe_checkpoint_handler
    assert dependencies.resume_after_reauth_handler is container.resume_after_reauth_handler
    assert dependencies.resolve_recovery_handler is container.resolve_recovery_handler
    assert dependencies.confirm_run_handler is container.confirm_run_handler
    assert dependencies.get_execution_context_handler is container.get_execution_context_handler


def test_run_command_dependency__does_not_expose__low_level_authorities() -> None:
    request, _container = _request_with_run_composition()
    dependencies = get_run_route_dependencies(request)

    for attribute in (
        "unit_of_work_factory",
        "read_unit_of_work_factory",
        "checkpoint_port",
        "resolve_resume_authority",
        "resolve_pending_confirmation",
        "operational_command_replay",
        "continue_cancel_resolution",
    ):
        assert not hasattr(dependencies, attribute)
