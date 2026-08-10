"""Loopback-only development bootstrap for the local FastAPI service."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

from fastapi import FastAPI

from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.adapters.keyring import OSKeyringSecretStore
from google_work_agent.adapters.langgraph import LangGraphWorkflowRuntime
from google_work_agent.adapters.llm import (
    APIProviderConnectionService,
    ApiStructuredLLMProvider,
    DefaultHardwareProbe,
    DeterministicLLMRuntimeRouter,
    LLMCredentialService,
    LLMRuntimeStatusService,
    LoopbackOllamaProbe,
    OllamaHTTPClient,
    OllamaStructuredLLMProvider,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPGmailUiReadGateway,
    MCPGoogleOAuthCredentialProvider,
    MCPGoogleWorkspaceGateway,
    MCPRuntimeStatusProvider,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.runtime import (
    BuildProfile,
    FileSettingsStore,
    SafeModeController,
    SettingsService,
)
from google_work_agent.api import API_CONTRACT_VERSION, ApiContainer, create_app
from google_work_agent.api.security import (
    InMemoryBootstrapGrantStore,
    InMemoryLocalSessionManager,
    LocalApiAccessGuard,
    LocalBindPolicy,
)
from google_work_agent.application import (
    DisconnectGoogleService,
    GetGoogleConnectionService,
    StartGoogleOAuthService,
)
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.llm import (
    DeleteLLMApiKeyService,
    GetLLMConnectionService,
    LLMRuntimeService,
    StoreLLMApiKeyService,
    TestLLMConnectionService,
)
from google_work_agent.application.queries import QueryService
from google_work_agent.application.resource_queries import ResourceQueryService
from google_work_agent.application.start_run import (
    CreateConversationService,
    ModifyWriteActionService,
    RejectWriteActionService,
    ResumeRunService,
    StartRunService,
)
from google_work_agent.application.workflows.prompt_registry import InactivePromptArtifactError
from google_work_agent.application.write_actions import (
    ApproveWriteActionService,
    PrepareWriteRetryService,
    RequestRunCancellationService,
)
from google_work_agent.ports import (
    AvailabilityState,
    LauncherProbeDecision,
    ProbeResult,
    ProviderResponsePayload,
    ReadinessAggregator,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimePolicy,
    RuntimeStatusProvider,
    RuntimeSummary,
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)
from google_work_agent.ports.mcp_transport import MCPTransportError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
RELEASE_VERSION = "0.1.0-dev"
MCP_MANIFEST_VERSION = "2026-08-07.p0"
MCP_TOOL_REGISTRY_VERSION = "2026-08-06.p0"


@dataclass(frozen=True, slots=True)
class SystemClock:
    def now_ms(self) -> int:
        return time.time_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class UUIDIdGenerator:
    def next_id(self) -> str:
        return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class DevelopmentLauncherProbeVerifier:
    """Bind direct development readiness to this service instance."""

    service_instance_id: str

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        return LauncherProbeDecision(allowed=service_instance_id == self.service_instance_id)


class CoreInitializationError(RuntimeError):
    """Redacted core-startup failure exposed through readiness only."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class _DeferredCoordinator:
    """Keeps the HTTP process live until the core coordinator is available."""

    def __init__(self) -> None:
        self._delegate: LocalRunCoordinator | None = None
        self._started = False

    def start(self) -> None:
        self._started = True
        if self._delegate is not None:
            self._delegate.start()

    def bind(self, delegate: LocalRunCoordinator) -> None:
        self._delegate = delegate
        if self._started:
            delegate.start()

    def stop(self) -> None:
        if self._delegate is not None:
            self._delegate.stop()


class _BootReadinessAggregator(ReadinessAggregator):
    """Expose initialization state without making liveness depend on core startup."""

    def __init__(self, safe_mode: SafeModeController) -> None:
        self._safe_mode = safe_mode
        self._delegate: ReadinessAggregator | None = None
        self._failure_code: str | None = None

    def bind(self, delegate: ReadinessAggregator) -> None:
        self._delegate = delegate

    def fail(self, code: str) -> None:
        self._failure_code = code

    def evaluate(self) -> ReadinessReport:
        if self._failure_code is not None:
            return ReadinessReport(
                state=ReadinessState.SAFE_MODE,
                checks=(
                    ReadinessCheckResult(
                        name="core_initialization",
                        state=ReadinessState.SAFE_MODE,
                        detail=self._failure_code,
                    ),
                ),
            )
        if self._delegate is None:
            return ReadinessReport(
                state=ReadinessState.NOT_READY,
                checks=(
                    ReadinessCheckResult(
                        name="core_initialization",
                        state=ReadinessState.NOT_READY,
                        detail="INITIALIZING",
                    ),
                ),
            )
        return self._delegate.evaluate()


class _BootRuntimeStatusProvider:
    def get_summary(self) -> RuntimeSummary:
        return RuntimeSummary(
            google="NOT_CONFIGURED",
            mcp="INITIALIZING",
            api_llm="NOT_CONFIGURED",
            ollama="NOT_CONFIGURED",
            deployment_profile=BuildProfile.LOCAL_CAPABLE.value,
            recovery_required_run_ids=(),
            open_run_ids=(),
            safe_mode=True,
            safe_mode_reason_codes=("CORE_INITIALIZING",),
        )


class _BootQueryService:
    def get_runtime_summary(self) -> RuntimeSummary:
        return _BootRuntimeStatusProvider().get_summary()


class _DeferredApiContainer:
    """Stable DI shell used by FastAPI while the concrete core is built."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        service_instance_id: str,
        bootstrap_secret: str,
        core_builder: Callable[..., ApiContainer] | None = None,
    ) -> None:
        self._core: ApiContainer | None = None
        self._core_builder = core_builder
        self._closed = False
        self.local_run_coordinator = _DeferredCoordinator()
        self.safe_mode_controller = SafeModeController()
        self.core_initialization_in_progress = True
        self.readiness_aggregator = _BootReadinessAggregator(self.safe_mode_controller)
        self.runtime_status_provider: RuntimeStatusProvider = _BootRuntimeStatusProvider()
        self.query_service: Any = _BootQueryService()
        self.clock = SystemClock()
        self.id_generator = UUIDIdGenerator()
        self.release_version = RELEASE_VERSION
        self.environment = "DEVELOPMENT"
        self.service_instance_id = service_instance_id
        self.api_contract_version = API_CONTRACT_VERSION
        self.local_bind_host = host
        self.local_bind_port = port
        self.max_request_body_bytes = 64 * 1024
        self.api_docs_enabled = False
        self.frontend_site = None
        self.additional_readiness_checks: tuple[Any, ...] = ()
        self.shutdown_callbacks = (self.close,)
        self.startup_callbacks = (self._initialize,)
        self.client_address_resolver: Callable[[Any], str | None] | None = None
        self.operational_log_sink = None
        self.endpoint_policy_registry = None
        self._bootstrap_secret = bootstrap_secret
        self._bootstrap_grant_store = InMemoryBootstrapGrantStore()
        self._session_manager = InMemoryLocalSessionManager()
        self._bootstrap_grant_store.provision(
            secret=bootstrap_secret,
            service_instance_id=service_instance_id,
            now_ms=self.clock.now_ms(),
        )
        self.api_access_guard = LocalApiAccessGuard(
            expected_host=f"{host}:{port}",
            expected_origin=f"http://{host}:{port}",
            service_instance_id=service_instance_id,
            session_manager=self._session_manager,
            release_version=RELEASE_VERSION,
            environment="DEVELOPMENT",
            now_ms=self.clock.now_ms,
        )
        self.launcher_probe_verifier = DevelopmentLauncherProbeVerifier(service_instance_id)
        self.bootstrap_grant_store = self._bootstrap_grant_store
        self.local_session_manager = self._session_manager

    async def _initialize(self) -> None:
        worker = asyncio.create_task(
            asyncio.to_thread(
                self._core_builder or build_container,
                host=self.local_bind_host,
                port=self.local_bind_port,
                bootstrap_secret=self._bootstrap_secret,
                service_instance_id=self.service_instance_id,
                safe_mode_controller=self.safe_mode_controller,
            )
        )
        try:
            core = await asyncio.shield(worker)
        except asyncio.CancelledError:
            self._closed = True
            core = await worker
            _close_container(core)
            raise
        except CoreInitializationError as error:
            self.core_initialization_in_progress = False
            self.safe_mode_controller.enable(error.safe_code)
            self.readiness_aggregator.fail(error.safe_code)
            return
        except Exception:
            self.core_initialization_in_progress = False
            self.safe_mode_controller.enable("CORE_INITIALIZATION_FAILED")
            self.readiness_aggregator.fail("CORE_INITIALIZATION_FAILED")
            return
        if self._closed:
            _close_container(core)
            return
        self._core = core
        self.local_run_coordinator.bind(core.local_run_coordinator)
        self.readiness_aggregator.bind(core.readiness_aggregator)
        self.runtime_status_provider = core.runtime_status_provider
        self.query_service = core.query_service
        self.core_initialization_in_progress = False
        self.safe_mode_controller.disable()

    def close(self) -> None:
        self._closed = True
        if self._core is not None:
            _close_container(self._core)

    def __getattr__(self, name: str) -> Any:
        if self._core is not None:
            return getattr(self._core, name)
        raise RuntimeError("core initialization is incomplete")


@dataclass(frozen=True, slots=True)
class DevelopmentReadinessAggregator(ReadinessAggregator):
    database_path: Path
    transport: SubprocessMCPTransport
    mcp_manifest_path: Path | None = None
    prompt_active: bool = True

    def evaluate(self) -> ReadinessReport:
        checks = (
            self._manifest_asset_check(),
            self._api_contract_check(),
            self._sqlite_check(),
            self._domain_check(),
            self._keyring_check(),
            self._mcp_executable_check(),
            self._mcp_check(),
            self._tool_schema_check(),
        )
        state = (
            ReadinessState.READY
            if all(check.state is ReadinessState.READY for check in checks)
            else ReadinessState.NOT_READY
        )
        return ReadinessReport(state=state, checks=checks)

    def _sqlite_check(self) -> ReadinessCheckResult:
        try:
            with connect_sqlite(self.database_path) as connection:
                row = connection.execute("SELECT COUNT(*) FROM schema_migrations;").fetchone()
            if row is None or int(row[0]) < 1:
                return ReadinessCheckResult(
                    name="sqlite_migrations",
                    state=ReadinessState.NOT_READY,
                    detail="migration receipts are unavailable",
                )
        except sqlite3.Error:
            return ReadinessCheckResult(
                name="sqlite_migrations",
                state=ReadinessState.NOT_READY,
                detail="sqlite is unavailable",
            )
        return ReadinessCheckResult(name="sqlite_migrations", state=ReadinessState.READY)

    def _manifest_asset_check(self) -> ReadinessCheckResult:
        manifest_ok = self.mcp_manifest_path is not None and self.mcp_manifest_path.is_file()
        asset_ok = (PROJECT_ROOT / "frontend" / "index.html").is_file()
        if manifest_ok and asset_ok:
            return ReadinessCheckResult(name="manifest_assets", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="manifest_assets",
            state=ReadinessState.NOT_READY,
            detail="MANIFEST_OR_ASSET_UNAVAILABLE",
        )

    @staticmethod
    def _api_contract_check() -> ReadinessCheckResult:
        if API_CONTRACT_VERSION:
            return ReadinessCheckResult(name="api_contract", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="api_contract", state=ReadinessState.NOT_READY, detail="API_CONTRACT_UNAVAILABLE"
        )

    def _domain_check(self) -> ReadinessCheckResult:
        try:
            with connect_sqlite(self.database_path) as connection:
                row = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'runs';"
                ).fetchone()
        except sqlite3.Error:
            row = None
        if row is not None:
            return ReadinessCheckResult(name="domain_schema", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="domain_schema", state=ReadinessState.NOT_READY, detail="DOMAIN_SCHEMA_UNAVAILABLE"
        )

    @staticmethod
    def _keyring_check() -> ReadinessCheckResult:
        try:
            OSKeyringSecretStore()
        except RuntimeError:
            return ReadinessCheckResult(
                name="keyring_adapter", state=ReadinessState.NOT_READY, detail="KEYRING_UNAVAILABLE"
            )
        return ReadinessCheckResult(name="keyring_adapter", state=ReadinessState.READY)

    @staticmethod
    def _mcp_executable_check() -> ReadinessCheckResult:
        if Path(sys.executable).is_file():
            return ReadinessCheckResult(name="mcp_executable", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="mcp_executable",
            state=ReadinessState.NOT_READY,
            detail="MCP_EXECUTABLE_UNAVAILABLE",
        )

    def _mcp_check(self) -> ReadinessCheckResult:
        metadata = self.transport.runtime_metadata()
        if metadata.process_status != "READY" or metadata.process_instance_id is None:
            return ReadinessCheckResult(
                name="mcp_handshake",
                state=ReadinessState.NOT_READY,
                detail=metadata.last_safe_error_code or metadata.process_status,
            )
        return ReadinessCheckResult(name="mcp_handshake", state=ReadinessState.READY)

    def _tool_schema_check(self) -> ReadinessCheckResult:
        metadata = self.transport.runtime_metadata()
        if (
            metadata.protocol_version == MCP_MANIFEST_VERSION
            and metadata.tool_registry_version == MCP_TOOL_REGISTRY_VERSION
            and metadata.available_tool_count > 0
        ):
            return ReadinessCheckResult(name="tool_schema", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="tool_schema", state=ReadinessState.NOT_READY, detail="TOOL_SCHEMA_UNAVAILABLE"
        )

    def _prompt_check(self) -> ReadinessCheckResult:
        if self.prompt_active:
            return ReadinessCheckResult(name="prompt_activation", state=ReadinessState.READY)
        return ReadinessCheckResult(
            name="prompt_activation",
            state=ReadinessState.NOT_READY,
            detail="PROMPT_NOT_ACTIVE",
        )


class _PromptInactiveWorkflowRuntime:
    """Safe placeholder: workflows cannot execute until prompts are approved."""

    def close(self) -> None:
        return None

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    @staticmethod
    def _not_available(run_id: str, workflow_key: str) -> WorkflowInvocationResult:
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=WorkflowOutcome.FAILED,
            payload={"safe_error_code": "PROMPT_NOT_ACTIVE"},
        )


class _UnavailableApiProviderTransport:
    """Explicit boundary until a real external API-provider adapter is configured."""

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        del api_key, timeout_seconds
        return ProbeResult(
            availability=AvailabilityState.NOT_CONFIGURED,
            safe_error_code="API_PROVIDER_NOT_CONFIGURED",
        )

    def invoke_structured(
        self,
        *,
        prompt_ref: object,
        prompt_input: object,
        output_schema: object,
        timeout_seconds: int,
        api_key: str,
    ) -> ProviderResponsePayload:
        del prompt_ref, prompt_input, output_schema, timeout_seconds, api_key
        raise RuntimeError("External API-provider transport is not configured.")


def build_container(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    runtime_root: Path | None = None,
    bootstrap_secret: str | None = None,
    service_instance_id: str | None = None,
    safe_mode_controller: SafeModeController | None = None,
) -> ApiContainer:
    """Assemble the development service with real local adapters."""

    LocalBindPolicy(host=host, port=port).validate()
    root = (runtime_root or PROJECT_ROOT / "runtime" / "development").resolve()
    root.mkdir(parents=True, exist_ok=True)
    database_path = root / "google-work-agent.sqlite3"
    checkpoint_database_path = root / "langgraph-checkpoints.sqlite3"
    mcp_manifest_path = _write_mcp_manifest(root)
    prompt_manifest_path = PROJECT_ROOT / "prompts" / "agent" / "prompt-manifest-v0.8.2.json"
    clock = SystemClock()
    id_generator = UUIDIdGenerator()
    service_instance_id = service_instance_id or f"dev-{uuid.uuid4()}"

    try:
        with connect_sqlite(database_path) as connection:
            apply_migrations(connection, now_ms=clock.now_ms)
    except sqlite3.Error as error:
        raise CoreInitializationError("MIGRATION_FAILED") from error

    try:
        transport = SubprocessMCPTransport(
            config=MCPArtifactConfig(
                executable_path=str(Path(sys.executable).resolve()),
                manifest_path=str(mcp_manifest_path),
                expected_binary_sha256=calculate_file_sha256(Path(sys.executable).resolve()),
                expected_manifest_sha256=calculate_file_sha256(mcp_manifest_path),
                expected_manifest_version=MCP_MANIFEST_VERSION,
                expected_protocol_version=MCP_MANIFEST_VERSION,
                expected_tool_registry_version=MCP_TOOL_REGISTRY_VERSION,
                startup_timeout_ms=5_000,
                request_timeout_ms=10_000,
                max_restart_count=1,
                environment="DEVELOPMENT",
                service_instance_id=service_instance_id,
                working_directory=str(PROJECT_ROOT),
                extra_environment=None,
            )
        )
    except MCPTransportError as error:
        raise CoreInitializationError("MCP_HANDSHAKE_FAILED") from error
    google_provider = MCPGoogleOAuthCredentialProvider(transport=transport)
    runtime_status_provider = MCPRuntimeStatusProvider(
        google_provider=google_provider,
        transport=transport,
        api_llm="NOT_CONFIGURED",
        ollama="NOT_CONFIGURED",
        deployment_profile=BuildProfile.LOCAL_CAPABLE.value,
    )
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    query_service = QueryService(
        database_path=database_path,
        runtime_status_provider=runtime_status_provider,
    )
    try:
        llm_runtime = _build_llm_runtime(
            settings_path=root / "settings" / "app-settings.json",
            query_service=query_service,
        )
    except RuntimeError as error:
        transport.close()
        raise CoreInitializationError("KEYRING_UNAVAILABLE") from error
    prompt_active = True
    workflow_runtime: LangGraphWorkflowRuntime | _PromptInactiveWorkflowRuntime
    gateway = MCPGoogleWorkspaceGateway(transport=transport)
    try:
        workflow_runtime = LangGraphWorkflowRuntime(
            unit_of_work_factory=unit_of_work_factory,
            llm_runtime=llm_runtime,
            gateway=gateway,
            now_ms=clock.now_ms,
            id_factory=id_generator.next_id,
            signing_secret=secrets.token_hex(32),
            service_instance_id=service_instance_id,
            checkpoint_database_path=checkpoint_database_path,
            prompt_manifest_path=prompt_manifest_path,
        )
    except InactivePromptArtifactError:
        prompt_active = False
        workflow_runtime = _PromptInactiveWorkflowRuntime()
    event_publisher = InMemoryRunEventPublisher(service_instance_id=service_instance_id)
    coordinator = LocalRunCoordinator(
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=workflow_runtime,
        event_publisher=event_publisher,
        now_ms=clock.now_ms,
        api_contract_version=API_CONTRACT_VERSION,
    )
    session_manager = InMemoryLocalSessionManager()
    grant_store = InMemoryBootstrapGrantStore()
    secret = bootstrap_secret or secrets.token_urlsafe(32)
    grant_store.provision(
        secret=secret,
        service_instance_id=service_instance_id,
        now_ms=clock.now_ms(),
    )

    return ApiContainer(
        unit_of_work_factory=unit_of_work_factory,
        query_service=query_service,
        create_conversation_service=CreateConversationService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        start_run_service=StartRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        approve_action_service=ApproveWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        modify_action_service=ModifyWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        reject_action_service=RejectWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        prepare_retry_service=PrepareWriteRetryService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        cancel_run_service=RequestRunCancellationService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        resume_run_service=ResumeRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        local_run_coordinator=coordinator,
        workflow_runtime=workflow_runtime,
        event_publisher=event_publisher,
        readiness_aggregator=DevelopmentReadinessAggregator(
            database_path=database_path,
            transport=transport,
            mcp_manifest_path=mcp_manifest_path,
            prompt_active=prompt_active,
        ),
        runtime_status_provider=runtime_status_provider,
        api_access_guard=LocalApiAccessGuard(
            expected_host=f"{host}:{port}",
            expected_origin=f"http://{host}:{port}",
            service_instance_id=service_instance_id,
            session_manager=session_manager,
            release_version=RELEASE_VERSION,
            environment="DEVELOPMENT",
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=id_generator,
        release_version=RELEASE_VERSION,
        environment="DEVELOPMENT",
        service_instance_id=service_instance_id,
        local_bind_host=host,
        local_bind_port=port,
        launcher_probe_verifier=DevelopmentLauncherProbeVerifier(service_instance_id),
        bootstrap_grant_store=grant_store,
        local_session_manager=session_manager,
        start_google_oauth_service=StartGoogleOAuthService(provider=google_provider),
        get_google_connection_service=GetGoogleConnectionService(
            provider=google_provider,
            account_provisioner=query_service,
            now_ms=clock.now_ms,
        ),
        disconnect_google_service=DisconnectGoogleService(provider=google_provider),
        resource_query_service=ResourceQueryService(
            gateway=gateway,
            gmail_detail_gateway=MCPGmailUiReadGateway(transport=transport),
        ),
        get_llm_connection_service=GetLLMConnectionService(
            runtime_status_service=llm_runtime.status_service,
            settings_service=llm_runtime.settings_service,
        ),
        store_llm_api_key_service=StoreLLMApiKeyService(
            credential_service=llm_runtime.credential_service,
        ),
        delete_llm_api_key_service=DeleteLLMApiKeyService(
            credential_service=llm_runtime.credential_service,
        ),
        test_llm_connection_service=TestLLMConnectionService(runtime_service=llm_runtime),
        safe_mode_controller=safe_mode_controller,
        shutdown_callbacks=(workflow_runtime.close, transport.close),
    )


def create_service_app() -> FastAPI:
    """Return an argument-free application factory for Uvicorn."""

    shell = _DeferredApiContainer(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=secrets.token_urlsafe(32),
    )
    return create_app(cast(ApiContainer, shell))


def main() -> NoReturn:
    """Run the development service on an explicit loopback address."""

    parser = argparse.ArgumentParser(description="Run the Google Work Agent development service.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    LocalBindPolicy(host=args.host, port=args.port).validate()
    bootstrap_secret = secrets.token_urlsafe(32)
    container = _DeferredApiContainer(
        host=args.host,
        port=args.port,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=bootstrap_secret,
    )
    print(
        "Open the Vite development UI with this one-time bootstrap fragment:\n"
        f"http://127.0.0.1:5173/#bootstrap_secret={bootstrap_secret}"
        f"&service_instance_id={container.service_instance_id}",
        flush=True,
    )
    import uvicorn

    uvicorn.run(create_app(cast(ApiContainer, container)), host=args.host, port=args.port)
    raise SystemExit(0)


def _close_container(container: ApiContainer) -> None:
    """Close core-owned resources exactly once when deferred startup loses a race."""

    try:
        container.local_run_coordinator.stop()
    finally:
        for callback in container.shutdown_callbacks:
            callback()


def _build_llm_runtime(*, settings_path: Path, query_service: QueryService) -> LLMRuntimeService:
    settings_service = SettingsService(
        store=FileSettingsStore(settings_path),
        deployment_profile=BuildProfile.LOCAL_CAPABLE,
        approved_model_ids=frozenset(),
        has_active_runs=lambda: bool(query_service.list_open_runs()),
    )
    credential_service = LLMCredentialService(
        provider_name="unconfigured",
        environment="DEVELOPMENT",
        keyring_store=OSKeyringSecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    ollama_transport = OllamaHTTPClient()
    status_service = LLMRuntimeStatusService(
        build_profile=BuildProfile.LOCAL_CAPABLE.value,
        credential_service=credential_service,
        api_connection_service=APIProviderConnectionService(transport=None),
        hardware_probe=DefaultHardwareProbe(),
        ollama_probe=LoopbackOllamaProbe(transport=ollama_transport),
        approved_models={},
        runtime_policy=RuntimePolicy(),
    )
    return LLMRuntimeService(
        settings_service=settings_service.get,
        status_service=status_service,
        credential_service=credential_service,
        api_provider=ApiStructuredLLMProvider(
            provider_name="unconfigured",
            transport=_UnavailableApiProviderTransport(),
            model="unconfigured",
        ),
        ollama_provider_factory=lambda model, settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
    )


def _write_mcp_manifest(runtime_root: Path) -> Path:
    manifest_path = runtime_root / "mcp-manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest_payload(), sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path.resolve()


if __name__ == "__main__":
    main()
