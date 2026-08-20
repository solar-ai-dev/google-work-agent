from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from google_work_agent.api.dependencies import get_run_route_dependencies
from google_work_agent.application.write_actions import ResolveMismatchRecoveryService


def _request_with_recovery_service(service: object | None) -> Request:
    app = FastAPI()
    app.state.container = SimpleNamespace(
        api_contract_version="1",
        query_service=object(),
        start_run_service=object(),
        cancel_run_service=object(),
        resume_run_service=object(),
        resolve_recovery_service=service,
        local_run_coordinator=object(),
        id_generator=object(),
    )
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "app": app,
        }
    )


def test_run_dependency_returns_composition_owned_recovery_service() -> None:
    service = cast(ResolveMismatchRecoveryService, object())
    dependencies = get_run_route_dependencies(_request_with_recovery_service(service))

    assert dependencies.resolve_recovery_service() is service


def test_run_dependency_does_not_construct_missing_recovery_service() -> None:
    dependencies = get_run_route_dependencies(_request_with_recovery_service(None))

    with pytest.raises(RuntimeError, match="resolve_recovery_service is not configured"):
        dependencies.resolve_recovery_service()
