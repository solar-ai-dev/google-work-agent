"""Diagnostic-bundle route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.diagnostic_bundle.create_diagnostic_bundle import (
    CreateDiagnosticBundleHandler,
)


@dataclass(frozen=True, slots=True)
class DiagnosticRouteDependencies:
    api_contract_version: str
    create_diagnostic_bundle_handler: CreateDiagnosticBundleHandler | None


def get_diagnostic_route_dependencies(request: Request) -> DiagnosticRouteDependencies:
    container = get_api_container(request)
    return DiagnosticRouteDependencies(
        api_contract_version=container.api_contract_version,
        create_diagnostic_bundle_handler=container.create_diagnostic_bundle_handler,
    )


DiagnosticRouteDependency = Annotated[
    DiagnosticRouteDependencies,
    Depends(get_diagnostic_route_dependencies),
]
