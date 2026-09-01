"""Project the canonical bounded Runtime Detail contract from abstract facts."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from google_work_agent.ports.connector.oauth_credential_port import OAuthCredentialPort
from google_work_agent.ports.llm.llm_runtime_status_port import (
    LlmProviderRuntimeStatus,
    LlmRuntimeStatusPort,
)
from google_work_agent.ports.system.component_circuit_state_port import (
    ComponentCircuitKey,
    ComponentCircuitStatePort,
)
from google_work_agent.ports.system.runtime_mode_port import RequestedRuntimeModeV1, RuntimeModePort


@dataclass(frozen=True, slots=True)
class _ConnectorRuntimeStatus:
    schema_version: Literal[1]
    connector_id: str
    connection_status: Literal[
        "CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"
    ]
    account_ref: str | None
    scope_status: Literal["READY", "INSUFFICIENT", "UNKNOWN"]
    retry_at_ms: int | None


@dataclass(frozen=True, slots=True)
class _ComponentCircuitStatus:
    schema_version: Literal[1]
    key: ComponentCircuitKey
    state: Literal["CLOSED", "OPEN"]
    retry_at_ms: int | None


@dataclass(frozen=True, slots=True)
class _RuntimeModeStatus:
    schema_version: Literal[1]
    requested_mode: RequestedRuntimeModeV1
    actual_runtime: Literal["LOCAL_GPU", "API_LLM", "MIXED"] | None
    fallback_reason: str | None


@dataclass(frozen=True, slots=True)
class _RunBudgetSummary:
    schema_version: Literal[1]
    profile: Literal["NORMAL", "RETRIEVAL_HEAVY", "REVISION_HEAVY"]
    llm_calls_used: int
    llm_call_limit: int
    connector_calls_used: int
    max_connector_calls: int
    source_page_calls_used: int
    max_source_page_calls: int
    detail_fetches_used: int
    max_detail_fetches: int
    context_tokens_used: int
    max_context_tokens: int
    retry_attempts_used: int
    max_retry_attempts: int
    elapsed_ms: int
    max_execution_ms: int


@dataclass(frozen=True, slots=True)
class GetRuntimeStatusQuery:
    connector_ids: tuple[str, ...] = ("google_workspace",)
    llm_providers: tuple[Literal["API_LLM", "LOCAL_GPU"], ...] = (
        "API_LLM",
        "LOCAL_GPU",
    )
    session_established: bool = False


@dataclass(frozen=True, slots=True)
class GetRuntimeStatusResult:
    schema_version: Literal[1]
    service_instance_id: str
    connectors: tuple[_ConnectorRuntimeStatus, ...]
    llm_providers: tuple[LlmProviderRuntimeStatus, ...]
    component_circuits: tuple[_ComponentCircuitStatus, ...]
    active_run_budget: _RunBudgetSummary | None
    recovery_required: bool
    release_version: str
    frontend_build_version: str
    api_contract_version: str
    deployment_profile: str
    runtime_mode: _RuntimeModeStatus
    database_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    migration_status: Literal["READY", "PENDING", "FAILED"]
    sse_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    recent_sanitized_error_code: str | None
    launcher_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    manifest_status: Literal["VALID", "INVALID", "UNAVAILABLE"]
    session_status: Literal["ESTABLISHED", "NOT_ESTABLISHED"]
    safe_mode: bool
    last_backup_status: str | None
    last_migration_status: str | None


class GetRuntimeStatusHandler:
    def __init__(
        self,
        *,
        runtime_mode: RuntimeModePort,
        oauth: OAuthCredentialPort,
        llm_status: LlmRuntimeStatusPort,
        circuits: ComponentCircuitStatePort,
        service_instance_id: str = "unavailable",
        release_version: str = "unavailable",
        frontend_build_version: str = "unavailable",
        api_contract_version: str = "1",
        deployment_profile: str = "unavailable",
        active_run_budget: Callable[[], _RunBudgetSummary | None] = lambda: None,
        recovery_required: Callable[[], bool] = lambda: False,
        database_status: Callable[[], Literal["READY", "DEGRADED", "UNAVAILABLE"]] = (
            lambda: "UNAVAILABLE"
        ),
        migration_status: Callable[[], Literal["READY", "PENDING", "FAILED"]] = (lambda: "PENDING"),
        sse_status: Callable[[], Literal["READY", "DEGRADED", "UNAVAILABLE"]] = (
            lambda: "UNAVAILABLE"
        ),
        recent_sanitized_error_code: Callable[[], str | None] = lambda: None,
        launcher_status: Callable[[], Literal["READY", "DEGRADED", "UNAVAILABLE"]] = (
            lambda: "UNAVAILABLE"
        ),
        manifest_status: Callable[[], Literal["VALID", "INVALID", "UNAVAILABLE"]] = (
            lambda: "UNAVAILABLE"
        ),
        session_status: Callable[[], Literal["ESTABLISHED", "NOT_ESTABLISHED"]] = lambda: (
            "NOT_ESTABLISHED"
        ),
        safe_mode: Callable[[], bool] = lambda: False,
        last_backup_status: Callable[[], str | None] = lambda: None,
        last_migration_status: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._runtime_mode = runtime_mode
        self._oauth = oauth
        self._llm_status = llm_status
        self._circuits = circuits
        self._service_instance_id = service_instance_id
        self._release_version = release_version
        self._frontend_build_version = frontend_build_version
        self._api_contract_version = api_contract_version
        self._deployment_profile = deployment_profile
        self._active_run_budget = active_run_budget
        self._recovery_required = recovery_required
        self._database_status = database_status
        self._migration_status = migration_status
        self._sse_status = sse_status
        self._recent_sanitized_error_code = recent_sanitized_error_code
        self._launcher_status = launcher_status
        self._manifest_status = manifest_status
        self._session_status = session_status
        self._safe_mode = safe_mode
        self._last_backup_status = last_backup_status
        self._last_migration_status = last_migration_status

    def __call__(self, query: GetRuntimeStatusQuery) -> GetRuntimeStatusResult:
        connector_keys = tuple(
            ComponentCircuitKey(1, "CONNECTOR", connector_id, None)
            for connector_id in query.connector_ids
        )
        llm_keys = tuple(
            ComponentCircuitKey(1, "LLM_RUNTIME", None, provider)
            for provider in query.llm_providers
        )
        circuit_states = tuple(
            self._circuits.get_state(key) for key in (*connector_keys, *llm_keys)
        )
        retry_by_connector = {
            state.key.connector_id: state.retry_at_ms
            for state in circuit_states
            if state.key.kind == "CONNECTOR"
        }
        connectors: list[_ConnectorRuntimeStatus] = []
        for connector_id in query.connector_ids:
            connection = self._oauth.get_connection_status(connector_id)
            connectors.append(
                _ConnectorRuntimeStatus(
                    schema_version=1,
                    connector_id=connector_id,
                    connection_status=connection.connection_status,
                    account_ref=connection.account_id,
                    scope_status=(
                        "INSUFFICIENT"
                        if connection.missing_required_scopes
                        else "READY"
                        if connection.connection_status == "CONNECTED"
                        else "UNKNOWN"
                    ),
                    retry_at_ms=retry_by_connector.get(connector_id),
                )
            )
        return GetRuntimeStatusResult(
            schema_version=1,
            service_instance_id=self._service_instance_id,
            connectors=tuple(connectors),
            llm_providers=tuple(self._llm_status.get_status(item) for item in query.llm_providers),
            component_circuits=tuple(
                _ComponentCircuitStatus(1, state.key, state.state, state.retry_at_ms)
                for state in circuit_states
            ),
            active_run_budget=self._active_run_budget(),
            recovery_required=self._recovery_required(),
            release_version=self._release_version,
            frontend_build_version=self._frontend_build_version,
            api_contract_version=self._api_contract_version,
            deployment_profile=self._deployment_profile,
            runtime_mode=_RuntimeModeStatus(1, self._runtime_mode.get_requested_mode(), None, None),
            database_status=self._database_status(),
            migration_status=self._migration_status(),
            sse_status=self._sse_status(),
            recent_sanitized_error_code=self._recent_sanitized_error_code(),
            launcher_status=self._launcher_status(),
            manifest_status=self._manifest_status(),
            session_status=("ESTABLISHED" if query.session_established else self._session_status()),
            safe_mode=self._safe_mode(),
            last_backup_status=self._last_backup_status(),
            last_migration_status=self._last_migration_status(),
        )


__all__ = [
    "GetRuntimeStatusHandler",
    "GetRuntimeStatusQuery",
    "GetRuntimeStatusResult",
]
