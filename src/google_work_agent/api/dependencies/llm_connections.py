"""LLM-connection route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.llm import TestLLMConnectionService


@dataclass(frozen=True, slots=True)
class LLMRouteDependencies:
    api_contract_version: str
    get_llm_credential_status_handler: Callable[[], object | None]
    store_llm_credential_handler: Callable[[], object | None]
    delete_llm_credential_handler: Callable[[], object | None]
    test_llm_connection_service: Callable[[], TestLLMConnectionService | None]


def get_llm_route_dependencies(request: Request) -> LLMRouteDependencies:
    container = get_api_container(request)
    return LLMRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_llm_credential_status_handler=lambda: container.get_llm_credential_status_handler,
        store_llm_credential_handler=lambda: container.store_llm_credential_handler,
        delete_llm_credential_handler=lambda: container.delete_llm_credential_handler,
        test_llm_connection_service=lambda: container.test_llm_connection_service,
    )


LLMRouteDependency = Annotated[
    LLMRouteDependencies,
    Depends(get_llm_route_dependencies),
]
