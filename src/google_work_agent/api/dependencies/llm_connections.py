"""LLM-connection route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.llm_credential.delete_llm_credential import (
    DeleteLlmCredentialHandler,
)
from google_work_agent.application.use_cases.llm_credential.get_llm_credential_status import (
    GetLlmCredentialStatusHandler,
)
from google_work_agent.application.use_cases.llm_credential.store_llm_credential import (
    StoreLlmCredentialHandler,
)


@dataclass(frozen=True, slots=True)
class LLMRouteDependencies:
    api_contract_version: str
    get_llm_credential_status_handler: GetLlmCredentialStatusHandler | None
    store_llm_credential_handler: StoreLlmCredentialHandler | None
    delete_llm_credential_handler: DeleteLlmCredentialHandler | None


def get_llm_route_dependencies(request: Request) -> LLMRouteDependencies:
    container = get_api_container(request)
    return LLMRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_llm_credential_status_handler=container.get_llm_credential_status_handler,
        store_llm_credential_handler=container.store_llm_credential_handler,
        delete_llm_credential_handler=container.delete_llm_credential_handler,
    )


LLMRouteDependency = Annotated[
    LLMRouteDependencies,
    Depends(get_llm_route_dependencies),
]
