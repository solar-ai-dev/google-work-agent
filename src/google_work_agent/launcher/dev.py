"""Loopback-only development bootstrap for the local FastAPI service."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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

from google_work_agent.adapters.connectors import (
    GoogleWorkspaceExecutionBackend,
)
from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.adapters.keyring import OSKeyringSecretStore
from google_work_agent.adapters.langgraph import LangGraphWorkflowRuntime
from google_work_agent.adapters.llm import (
    DEFAULT_GEMINI_MODEL_ID,
    APIProviderConnectionService,
    ApiStructuredLLMProvider,
    DefaultHardwareProbe,
    DeterministicLLMRuntimeRouter,
    GeminiHTTPClient,
    LLMCredentialService,
    LLMRuntimeStatusService,
    LoopbackOllamaProbe,
    OllamaHTTPClient,
    OllamaStructuredLLMProvider,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.mcp import (
    build_manifest_payload,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.runtime import (
    BuildProfile,
    FileSettingsStore,
    SafeModeController,
    SettingsService,
)
from google_work_agent.adapters.runtime.attachment_staging import (
    LocalAttachmentStaging,
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
from google_work_agent.application.attachments import (
    GetGmailAttachmentService,
    StageAttachmentService,
)
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.llm import (
    DeleteLLMApiKeyService,
    GetLLMConnectionService,
    LLMRuntimeService,
    PromptRepairSchemaRepairer,
    StoreLLMApiKeyService,
    TestLLMConnectionService,
)
from google_work_agent.application.queries import QueryService
from google_work_agent.application.resource_queries import ResourceQueryService
from google_work_agent.application.settings import GetSettingsService, PatchSettingsService
from google_work_agent.application.start_run import (
    CreateConversationService,
    ModifyWriteActionService,
    RejectWriteActionService,
    ResumeRunService,
    StartRunService,
)
from google_work_agent.application.workflows.prompt_registry import (
    InactivePromptArtifactError,
    default_prompt_manifest_path,
    resolve_instruction_text,
)
from google_work_agent.application.write_actions import (
    ApproveWriteActionService,
    FinalizeRunCancellationService,
    PrepareWriteRetryService,
    RequestRunCancellationService,
)
from google_work_agent.domain import CalendarWorkHours
from google_work_agent.launcher.connector_composition import build_connectors
from google_work_agent.launcher.development_constants import (
    PROJECT_ROOT,
)
from google_work_agent.launcher.development_readiness import (
    DevelopmentReadinessAggregator as DevelopmentReadinessAggregator,
)
from google_work_agent.ports import (
    ApprovedModelInfo,
    LauncherProbeDecision,
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

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
RELEASE_VERSION = "0.1.0-dev"
# Dev-mode local model allowlist: LOCAL_GPU routing refuses to invoke a model
# that is not "approved" (see DeterministicLLMRuntimeRouter._local_runtime_reason),
# so at least one already-`ollama pull`-ed model must be listed here. This never
# pulls or downloads anything; override via env var if a different model is
# installed locally.
DEFAULT_DEV_OLLAMA_MODEL_ID = os.environ.get("GWA_DEV_APPROVED_OLLAMA_MODEL", "qwen2.5:3b")


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
    """Keeps the HTTP process live until the core coordinator is available.

    ``local_run_coordinator`` is set once as a real instance attribute on
    ``_DeferredApiContainer`` (see below), so Python attribute lookup never
    falls through to ``__getattr__``'s post-init delegation for it -- this
    wrapper must itself forward every method the routes call, not just
    start/stop, or a call made after core initialization completes still
    hits this placeholder instead of the real coordinator.
    """

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

    def enqueue_start(self, *, run_id: str, request_id: str, command_id: str) -> None:
        self._require_delegate().enqueue_start(
            run_id=run_id, request_id=request_id, command_id=command_id
        )

    def enqueue_resume(
        self,
        *,
        run_id: str,
        request_id: str,
        command_id: str | None,
        resume_kind: str,
        resume_payload: dict[str, object],
    ) -> None:
        self._require_delegate().enqueue_resume(
            run_id=run_id,
            request_id=request_id,
            command_id=command_id,
            resume_kind=resume_kind,
            resume_payload=resume_payload,
        )

    def request_cancel(self, *, run_id: str, request_id: str, reason_code: str) -> None:
        self._require_delegate().request_cancel(
            run_id=run_id, request_id=request_id, reason_code=reason_code
        )

    def _require_delegate(self) -> LocalRunCoordinator:
        if self._delegate is None:
            raise RuntimeError("core initialization is incomplete")
        return self._delegate


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
    prompt_manifest_path = default_prompt_manifest_path()
    clock = SystemClock()
    id_generator = UUIDIdGenerator()
    service_instance_id = service_instance_id or f"dev-{uuid.uuid4()}"
    attachment_staging_dir = root / "attachments" / "staging"
    attachment_staging = LocalAttachmentStaging(
        staging_dir=attachment_staging_dir,
        now_ms=clock.now_ms,
    )
    attachment_staging.cleanup_expired()

    try:
        with connect_sqlite(database_path) as connection:
            apply_migrations(connection, now_ms=clock.now_ms)
    except sqlite3.Error as error:
        raise CoreInitializationError("MIGRATION_FAILED") from error

    try:
        connector_bundle = build_connectors(
            mcp_manifest_path=mcp_manifest_path,
            service_instance_id=service_instance_id,
            attachment_staging_dir=attachment_staging_dir,
            python_executable=Path(sys.executable).resolve(),
            working_directory=PROJECT_ROOT,
        )
    except MCPTransportError as error:
        raise CoreInitializationError("MCP_HANDSHAKE_FAILED") from error
    connector_registry = connector_bundle.registry
    google_connector = connector_bundle.google_connector
    runtime_status_provider = connector_bundle.runtime_status_provider
    google_provider = google_connector.oauth_provider
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    query_service = QueryService(
        database_path=database_path,
        connection_factory=connect_sqlite,
        runtime_status_provider=runtime_status_provider,
    )
    try:
        llm_runtime, settings_service = _build_llm_runtime(
            settings_path=root / "settings" / "app-settings.json",
            query_service=query_service,
            prompt_manifest_path=prompt_manifest_path,
        )
    except RuntimeError as error:
        connector_registry.close_all()
        raise CoreInitializationError("KEYRING_UNAVAILABLE") from error
    prompt_active = True
    workflow_runtime: LangGraphWorkflowRuntime | _PromptInactiveWorkflowRuntime
    gateway = google_connector.workspace_gateway
    try:
        workflow_runtime = LangGraphWorkflowRuntime(
            unit_of_work_factory=unit_of_work_factory,
            llm_runtime=llm_runtime,
            gateway=gateway,
            connector_execution=GoogleWorkspaceExecutionBackend(gateway=gateway),
            now_ms=clock.now_ms,
            id_factory=id_generator.next_id,
            signing_secret=secrets.token_hex(32),
            service_instance_id=service_instance_id,
            checkpoint_database_path=checkpoint_database_path,
            prompt_manifest_path=prompt_manifest_path,
            timezone_provider=lambda: settings_service.get().timezone,
            work_hours_provider=lambda: CalendarWorkHours(
                timezone=settings_service.get().timezone,
                days=settings_service.get().work_hours.days,
                start=settings_service.get().work_hours.start,
                end=settings_service.get().work_hours.end,
            ),
        )
    except InactivePromptArtifactError:
        prompt_active = False
        workflow_runtime = _PromptInactiveWorkflowRuntime()
    event_publisher = InMemoryRunEventPublisher(service_instance_id=service_instance_id)
    request_cancel_service = RequestRunCancellationService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
    )
    finalize_cancel_service = FinalizeRunCancellationService(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
    )
    coordinator = LocalRunCoordinator(
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=workflow_runtime,
        event_publisher=event_publisher,
        now_ms=clock.now_ms,
        api_contract_version=API_CONTRACT_VERSION,
        finalize_cancel_service=finalize_cancel_service,
        id_factory=id_generator.next_id,
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
            gateway=gateway,
            work_hours_provider=lambda: CalendarWorkHours(
                timezone=settings_service.get().timezone,
                days=settings_service.get().work_hours.days,
                start=settings_service.get().work_hours.start,
                end=settings_service.get().work_hours.end,
            ),
        ),
        reject_action_service=RejectWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        prepare_retry_service=PrepareWriteRetryService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        cancel_run_service=request_cancel_service,
        resume_run_service=ResumeRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        local_run_coordinator=coordinator,
        workflow_runtime=workflow_runtime,
        event_publisher=event_publisher,
        readiness_aggregator=DevelopmentReadinessAggregator(
            database_path=database_path,
            connector_registry=connector_registry,
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
            gmail_detail_gateway=google_connector.gmail_ui_gateway,
            default_calendar_id_provider=lambda: llm_runtime.settings_service().default_calendar_id,
            default_tasklist_id_provider=lambda: llm_runtime.settings_service().default_tasklist_id,
            timezone_provider=lambda: llm_runtime.settings_service().timezone,
        ),
        get_gmail_attachment_service=GetGmailAttachmentService(
            gateway=google_connector.gmail_attachment_gateway,
        ),
        stage_attachment_service=StageAttachmentService(staging=attachment_staging),
        get_llm_connection_service=GetLLMConnectionService(
            runtime_status_service=llm_runtime.status_service,
            settings_service=llm_runtime.settings_service,
        ),
        get_settings_service=GetSettingsService(service=settings_service),
        patch_settings_service=PatchSettingsService(service=settings_service),
        store_llm_api_key_service=StoreLLMApiKeyService(
            credential_service=llm_runtime.credential_service,
        ),
        delete_llm_api_key_service=DeleteLLMApiKeyService(
            credential_service=llm_runtime.credential_service,
        ),
        test_llm_connection_service=TestLLMConnectionService(runtime_service=llm_runtime),
        safe_mode_controller=safe_mode_controller,
        shutdown_callbacks=(workflow_runtime.close, connector_registry.close_all),
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


def _build_llm_runtime(
    *,
    settings_path: Path,
    query_service: QueryService,
    prompt_manifest_path: Path,
) -> tuple[LLMRuntimeService, SettingsService]:
    settings_service = SettingsService(
        store=FileSettingsStore(settings_path),
        deployment_profile=BuildProfile.LOCAL_CAPABLE,
        approved_model_ids=frozenset({DEFAULT_DEV_OLLAMA_MODEL_ID}),
        has_active_runs=lambda: bool(query_service.list_open_runs()),
    )
    credential_service = LLMCredentialService(
        provider_name="gemini",
        environment="DEVELOPMENT",
        keyring_store=OSKeyringSecretStore(),
        session_store=SessionMemorySecretStore(),
    )
    ollama_transport = OllamaHTTPClient()
    gemini_transport = GeminiHTTPClient()
    status_service = LLMRuntimeStatusService(
        build_profile=BuildProfile.LOCAL_CAPABLE.value,
        credential_service=credential_service,
        api_connection_service=APIProviderConnectionService(transport=gemini_transport),
        hardware_probe=DefaultHardwareProbe(),
        ollama_probe=LoopbackOllamaProbe(transport=ollama_transport),
        approved_models={
            DEFAULT_DEV_OLLAMA_MODEL_ID: ApprovedModelInfo(
                model_id=DEFAULT_DEV_OLLAMA_MODEL_ID,
                runtime="OLLAMA",
                manifest_version="1",
                schema_version="1",
            )
        },
        runtime_policy=RuntimePolicy(),
    )
    llm_runtime = LLMRuntimeService(
        settings_service=settings_service.get,
        status_service=status_service,
        credential_service=credential_service,
        api_provider=ApiStructuredLLMProvider(
            provider_name="gemini",
            transport=gemini_transport,
            model=DEFAULT_GEMINI_MODEL_ID,
            resolve_instruction_text=lambda prompt_ref: resolve_instruction_text(
                prompt_ref.prompt_id, prompt_manifest_path
            ),
        ),
        ollama_provider_factory=lambda model, settings: OllamaStructuredLLMProvider(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            resolve_instruction_text=lambda prompt_ref: resolve_instruction_text(
                prompt_ref.prompt_id, prompt_manifest_path
            ),
        ),
        router=DeterministicLLMRuntimeRouter(),
        runtime_policy=RuntimePolicy(),
        schema_repairer=PromptRepairSchemaRepairer(manifest_path=prompt_manifest_path),
    )
    return llm_runtime, settings_service


def _write_mcp_manifest(runtime_root: Path) -> Path:
    manifest_path = runtime_root / "mcp-manifest.json"
    manifest_path.write_text(
        json.dumps(build_manifest_payload(), sort_keys=True),
        encoding="utf-8",
    )
    return manifest_path.resolve()


if __name__ == "__main__":
    main()
