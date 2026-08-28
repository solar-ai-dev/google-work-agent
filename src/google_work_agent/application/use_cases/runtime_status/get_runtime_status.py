"""Project a token-free runtime status from canonical Ports."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.ports.connector.oauth_credential_port import (
    ConnectionMetadataV1,
    OAuthCredentialPort,
)
from google_work_agent.ports.llm.llm_runtime_status_port import (
    LlmRuntimeStatusPort,
    LlmRuntimeStatusV1,
)
from google_work_agent.ports.system.component_circuit_state_port import (
    ComponentCircuitKeyV1,
    ComponentCircuitStatePort,
    ComponentCircuitStateV1,
)
from google_work_agent.ports.system.runtime_mode_port import RequestedRuntimeModeV1, RuntimeModePort


@dataclass(frozen=True, slots=True)
class GetRuntimeStatusQuery:
    connector_id: str = "google_workspace"
    llm_providers: tuple[Literal["API_LLM", "LOCAL_GPU"], ...] = (
        "API_LLM",
        "LOCAL_GPU",
    )


@dataclass(frozen=True, slots=True)
class GetRuntimeStatusResult:
    schema_version: int
    requested_mode: RequestedRuntimeModeV1
    connector: ConnectionMetadataV1
    llm_runtimes: tuple[LlmRuntimeStatusV1, ...]
    component_circuits: tuple[ComponentCircuitStateV1, ...]
    active_run_budget_count: int


class GetRuntimeStatusHandler:
    def __init__(
        self,
        *,
        runtime_mode: RuntimeModePort,
        oauth: OAuthCredentialPort,
        llm_status: LlmRuntimeStatusPort,
        circuits: ComponentCircuitStatePort,
        active_run_budget_count: Callable[[], int] = lambda: 0,
    ) -> None:
        self._runtime_mode = runtime_mode
        self._oauth = oauth
        self._llm_status = llm_status
        self._circuits = circuits
        self._active_run_budget_count = active_run_budget_count

    def __call__(self, query: GetRuntimeStatusQuery) -> GetRuntimeStatusResult:
        keys = (
            ComponentCircuitKeyV1(1, "CONNECTOR", query.connector_id, None),
            *(
                ComponentCircuitKeyV1(1, "LLM_RUNTIME", None, provider)
                for provider in query.llm_providers
            ),
        )
        return GetRuntimeStatusResult(
            schema_version=1,
            requested_mode=self._runtime_mode.get_requested_mode(),
            connector=self._oauth.get_connection_status(query.connector_id),
            llm_runtimes=tuple(self._llm_status.get_status(item) for item in query.llm_providers),
            component_circuits=tuple(self._circuits.get_state(key) for key in keys),
            active_run_budget_count=max(0, self._active_run_budget_count()),
        )


__all__ = ["GetRuntimeStatusHandler", "GetRuntimeStatusQuery", "GetRuntimeStatusResult"]
