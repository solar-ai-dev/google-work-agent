"""Loopback-only development bootstrap for the local FastAPI service."""

from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

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
    MCPGoogleOAuthCredentialProvider,
    MCPGoogleWorkspaceGateway,
    MCPRuntimeStatusProvider,
    SubprocessMCPTransport,
    build_manifest_payload,
    calculate_file_sha256,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.runtime import BuildProfile, FileSettingsStore, SettingsService
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
from google_work_agent.application.start_run import (
    CreateConversationService,
    ModifyWriteActionService,
    RejectWriteActionService,
    ResumeRunService,
    StartRunService,
)
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
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
RELEASE_VERSION = "0.1.0-dev"
MCP_MANIFEST_VERSION = "2026-08-07.p0"
MCP_TOOL_REGISTRY_VERSION = "2026-08-06.p0"
DEVELOPMENT_RUNTIME_PROMPT_IDS = frozenset(
    {
        "request_understanding.classify",
        "request_understanding.clarify",
        "acquisition.plan_sources",
        "context.select_evidence",
        "context.assess_sufficiency",
        "analysis.analyze",
        "planning.answer_only",
        "planning.draft_plan",
        "planning.revise_plan",
        "review.inspect",
        "review.recheck",
        "profile.single.request_source.initial",
        "profile.single.reason_plan.initial",
        "profile.single.self_review.initial",
        "profile.single.self_review.recheck",
        "profile.three.stage1.initial",
        "profile.three.stage2.initial",
    }
)


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


@dataclass(frozen=True, slots=True)
class DevelopmentReadinessAggregator(ReadinessAggregator):
    database_path: Path
    transport: SubprocessMCPTransport

    def evaluate(self) -> ReadinessReport:
        checks = (self._sqlite_check(), self._mcp_check())
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

    def _mcp_check(self) -> ReadinessCheckResult:
        metadata = self.transport.runtime_metadata()
        if metadata.process_status != "READY" or metadata.process_instance_id is None:
            return ReadinessCheckResult(
                name="mcp_handshake",
                state=ReadinessState.NOT_READY,
                detail=metadata.last_safe_error_code or metadata.process_status,
            )
        return ReadinessCheckResult(name="mcp_handshake", state=ReadinessState.READY)


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
) -> ApiContainer:
    """Assemble the development service with real local adapters."""

    LocalBindPolicy(host=host, port=port).validate()
    root = (runtime_root or PROJECT_ROOT / "runtime" / "development").resolve()
    root.mkdir(parents=True, exist_ok=True)
    database_path = root / "google-work-agent.sqlite3"
    checkpoint_database_path = root / "langgraph-checkpoints.sqlite3"
    mcp_manifest_path = _write_mcp_manifest(root)
    workspace_manifest_path = _write_empty_workspace_manifest(root)
    prompt_manifest_path = _write_development_prompt_manifest(root)
    clock = SystemClock()
    id_generator = UUIDIdGenerator()
    service_instance_id = f"dev-{uuid.uuid4()}"

    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=clock.now_ms)

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
            extra_environment={
                "GWA_TEST_KEYRING_PATH": str((root / "mcp-keyring.json").resolve()),
                "GWA_PRODUCT_FIXTURE_MANIFEST": str(workspace_manifest_path),
            },
        )
    )
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
    llm_runtime = _build_llm_runtime(
        settings_path=root / "settings" / "app-settings.json",
        query_service=query_service,
    )
    workflow_runtime = LangGraphWorkflowRuntime(
        unit_of_work_factory=unit_of_work_factory,
        llm_runtime=llm_runtime,
        gateway=MCPGoogleWorkspaceGateway(transport=transport),
        now_ms=clock.now_ms,
        id_factory=id_generator.next_id,
        signing_secret=secrets.token_hex(32),
        service_instance_id=service_instance_id,
        checkpoint_database_path=checkpoint_database_path,
        prompt_manifest_path=prompt_manifest_path,
    )
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
        readiness_aggregator=DevelopmentReadinessAggregator(database_path, transport),
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
        get_google_connection_service=GetGoogleConnectionService(provider=google_provider),
        disconnect_google_service=DisconnectGoogleService(provider=google_provider),
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
        shutdown_callbacks=(workflow_runtime.close, transport.close),
    )


def create_service_app() -> FastAPI:
    """Return an argument-free application factory for Uvicorn."""

    return create_app(build_container())


def main() -> NoReturn:
    """Run the development service on an explicit loopback address."""

    parser = argparse.ArgumentParser(description="Run the Google Work Agent development service.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    LocalBindPolicy(host=args.host, port=args.port).validate()
    bootstrap_secret = secrets.token_urlsafe(32)
    container = build_container(
        host=args.host,
        port=args.port,
        bootstrap_secret=bootstrap_secret,
    )
    print(
        "Open the Vite development UI with this one-time bootstrap fragment:\n"
        f"http://127.0.0.1:5173/#bootstrap_secret={bootstrap_secret}"
        f"&service_instance_id={container.service_instance_id}",
        flush=True,
    )
    import uvicorn

    uvicorn.run(create_app(container), host=args.host, port=args.port)
    raise SystemExit(0)


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


def _write_empty_workspace_manifest(runtime_root: Path) -> Path:
    manifest_path = runtime_root / "development-workspace.json"
    manifest_path.write_text(
        json.dumps({"snapshot_id": "development-empty", "resources": [], "faults": []}),
        encoding="utf-8",
    )
    return manifest_path.resolve()


def _write_development_prompt_manifest(runtime_root: Path) -> Path:
    """Derive a DEV-only runtime selection without editing the source prompt pack."""

    source_path = PROJECT_ROOT / "prompts" / "agent" / "prompt-manifest-v0.8.2.json"
    manifest = json.loads(source_path.read_text(encoding="utf-8"))
    slots = manifest.get("slots")
    if not isinstance(slots, list):
        raise ValueError("prompt manifest slots are unavailable")
    activated: set[str] = set()
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError("prompt manifest slot is invalid")
        slot_id = slot.get("slot_id")
        if isinstance(slot_id, str) and slot_id in DEVELOPMENT_RUNTIME_PROMPT_IDS:
            slot["activation_status"] = "RUNTIME_ACTIVE"
            activated.add(slot_id)
    missing = DEVELOPMENT_RUNTIME_PROMPT_IDS - activated
    if missing:
        raise ValueError(f"development prompt slots are missing: {sorted(missing)}")
    manifest_path = runtime_root / "prompt-manifest-development.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path.resolve()


if __name__ == "__main__":
    main()
