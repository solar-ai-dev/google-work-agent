# 07. Connector · API · Persistence Grammar

**Normative detail of the current Repository Architecture Source.**

Connector path:

```
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
```

MCP wire tool IDs remain existing contract IDs and are not renamed for structural convenience.

API:

```
api/routes/<plural_resource>.py
api/schemas/<plural_resource>/<verb>_<object>.py
api/dependencies/<concern>.py
```

Transport does not own business semantics.

Persistence:

```
ports/persistence/<owner>_repository.py
adapters/persistence/sqlite/repositories/<owner>_repository.py
```

Non-persistence outbound Ports:

```
ports/<boundary>/<capability>_port.py
→ <Capability>Port
```

The current closed boundary package vocabulary is `connector`, `llm`, `keyring`, and `system`. These packages realize the outbound abstractions required by 03/07/09/10 without importing concrete adapters into Application. Adding another boundary package requires an explicit Repository Architecture contract update and Source Guide synchronization before implementation; version numbers are traceability metadata, not an independent Gate. Persistence remains a Repository abstraction and keeps the separate persistence grammar above.

Canonical non-persistence Port↔Adapter mapping required by the current behavioral contracts is defined by the single closed table below. The table is the only exact Port-set authority in this page; do not maintain a second path/symbol list.

| Boundary | Canonical Port path | Abstract Port | Canonical concrete P0 path | Canonical symbol |
| --- | --- | --- | --- | --- |
| Connector | `ports/connector/connector_read_port.py` | `ConnectorReadPort` | `adapters/connectors/runtime/mcp_connector_read.py` | `McpConnectorReadAdapter` |
| Connector | `ports/connector/connector_write_port.py` | `ConnectorWritePort` | `adapters/connectors/runtime/mcp_connector_write.py` | `McpConnectorWriteAdapter` |
| Connector | `ports/connector/oauth_credential_port.py` | `OAuthCredentialPort` | `adapters/connectors/runtime/mcp_oauth_credential.py` | `McpOAuthCredentialAdapter` |
| Connector | `ports/connector/mcp_client_port.py` | `MCPClientPort` | `adapters/connectors/runtime/stdio_mcp_client.py` | `StdioMCPClientAdapter` |
| LLM | `ports/llm/structured_inference_port.py` | `StructuredInferencePort` | `adapters/llm/runtime/structured_inference_router.py` | `StructuredInferenceRuntimeRouter` |
| LLM | `ports/llm/llm_credential_port.py` | `LlmCredentialPort` | `adapters/llm/runtime/llm_credential_router.py` | `LlmCredentialRouter` |
| LLM | `ports/llm/llm_runtime_status_port.py` | `LlmRuntimeStatusPort` | `adapters/llm/runtime/llm_runtime_status_router.py` | `LlmRuntimeStatusRouter` |
| Keyring | `ports/keyring/secret_store_port.py` | `SecretStorePort` | `adapters/keyring/os_keyring_secret_store.py` | `OsKeyringSecretStoreAdapter` |
| System | `ports/system/checkpoint_port.py` | `CheckpointPort` | `adapters/system/sqlite_checkpoint.py` | `SqliteCheckpointAdapter` |
| System | `ports/system/run_retrieval_cache_port.py` | `RunRetrievalCachePort` | `adapters/system/memory/run_retrieval_cache.py` | `InMemoryRunRetrievalCache` |
| System | `ports/system/workflow_execution_port.py` | `WorkflowExecutionPort` | `adapters/langgraph/runtime/background_run_executor.py` | `BackgroundRunExecutorAdapter` |
| System | `ports/system/settings_port.py` | `SettingsPort` | `adapters/system/json_settings.py` | `JsonSettingsAdapter` |
| System | `ports/system/runtime_mode_port.py` | `RuntimeModePort` | `adapters/system/process_runtime_mode.py` | `ProcessRuntimeModeAdapter` |
| System | `ports/system/local_runtime_provisioning_port.py` | `LocalRuntimeProvisioningPort` | `adapters/system/ollama_local_runtime_provisioning.py` | `OllamaLocalRuntimeProvisioningAdapter` |
| System | `ports/system/backup_port.py` | `BackupPort` | `adapters/system/filesystem_backup.py` | `FilesystemBackupAdapter` |
| System | `ports/system/diagnostics_port.py` | `DiagnosticsPort` | `adapters/system/filesystem_diagnostics.py` | `FilesystemDiagnosticsAdapter` |
| System | `ports/system/shutdown_port.py` | `ShutdownPort` | `adapters/system/process_shutdown.py` | `ProcessShutdownAdapter` |
| System | `ports/system/operational_command_replay_port.py` | `OperationalCommandReplayPort` | `adapters/system/filesystem_operational_command_replay.py` | `FilesystemOperationalCommandReplayAdapter` |
| System | `ports/system/attachment_staging_port.py` | `AttachmentStagingPort` | `adapters/system/filesystem_attachment_staging.py` | `FilesystemAttachmentStagingAdapter` |
| System | `ports/system/clock_port.py` | `ClockPort` | `adapters/system/system_clock.py` | `SystemClockAdapter` |
| System | `ports/system/uuid_port.py` | `UUIDPort` | `adapters/system/uuid4.py` | `Uuid4Adapter` |
| System | `ports/system/hardware_probe_port.py` | `HardwareProbePort` | `adapters/system/windows_hardware_probe.py` | `WindowsHardwareProbeAdapter` |
| System | `ports/system/browser_launcher_port.py` | `BrowserLauncherPort` | `adapters/system/default_browser_launcher.py` | `DefaultBrowserLauncherAdapter` |
| System | `ports/system/component_circuit_state_port.py` | `ComponentCircuitStatePort` | `adapters/system/process_component_circuit_state.py` | `ProcessComponentCircuitStateAdapter` |
| System | `ports/system/sse_event_buffer_port.py` | `SseEventBufferPort` | `adapters/system/memory/sse_event_buffer.py` | `InMemorySseEventBuffer` |

Boundary rules:

- Connector browse/detail/retrieval/verification/recovery reads depend on `ConnectorReadPort`; approved writes depend on `ConnectorWritePort`.
- `MCPClientPort` is the replaceable Connector Runtime client/transport test seam required by 03. It sits behind Connector Application Ports and must not become a direct FastAPI Route, Agent, or Domain dependency.
- OAuth connection Application use cases depend on `OAuthCredentialPort`; P0 `google_workspace` is an adapter/runtime binding, not an Application package owner.
- Product LLM semantic operations depend on `StructuredInferencePort`. LLM key store/delete operations depend on `LlmCredentialPort`; Runtime Detail uses `LlmRuntimeStatusPort`. The LLM adapter, not FastAPI Route or Agent code, owns OS-keyring access for LLM credentials.
- `SecretStorePort` is the replaceable Keyring abstraction required by 03/09/10. Connector/LLM credential adapters may consume it behind their own boundary contracts; Browser/FastAPI routes never receive raw secret-store access.
- `CheckpointPort` is distinct from Domain Repository persistence. It owns graph checkpoint availability/load/store needed by same-Run resume/recovery coordination. A Domain Repository must not expose checkpoint rows as aggregate persistence, and Application/LangGraph must not import a concrete SQLite checkpointer.
- `WorkflowExecutionPort` is the single Application→background LangGraph execution seam. It accepts only committed Run execution refs; FastAPI routes never choose `asyncio.create_task`, BackgroundTasks, worker queues, or concrete LangGraph executors directly.
- Settings/Backup/Diagnostics/Shutdown/Attachment staging/Hardware probe/Clock/UUID are local system boundaries. `BrowserLauncherPort` is the Launcher/system browser-opening seam and does not own OAuth semantics. Application or Launcher composition depends on these abstract Ports only where required by 03/07/08/10/11.
- Gmail attachment bytes are read through `ConnectorReadPort`; `AttachmentStagingPort` owns only bounded local staging lifecycle.

Repository means Domain persistence only; it must not become workflow/application authority. LangGraph checkpoint persistence is explicitly separate and uses `CheckpointPort`, even if its concrete implementation shares the same SQLite file.

**Concrete Adapter mapping status:** Connector operation adapters, SQLite repositories, and every required non-persistence Port have deterministic P0 placement. The non-persistence exact mapping is the single table above; Application/LangGraph import abstract Ports only and composition root owns concrete binding.

## Concrete non-persistence Adapter rules

The exact Port path, abstract symbol, concrete Adapter path, and concrete symbol are the single table above. Application/LangGraph import abstract Ports only; composition root owns concrete binding.

Operational replay callables are closed by 07: `FilesystemOperationalCommandReplayAdapter` persists/returns stable `operation_ref`; every mutable non-Domain operation uses its exact operation-specific reconcile callable before any retry. `McpOAuthCredentialAdapter`, `LlmCredentialRouter`, `JsonSettingsAdapter`, `ProcessRuntimeModeAdapter`, `FilesystemBackupAdapter`, `FilesystemDiagnosticsAdapter`, `ProcessShutdownAdapter`, and `FilesystemAttachmentStagingAdapter` implement those callables at their existing Port boundaries. Artifact adapters receive `operation_ref` for create/stage; Restore uses `backup_ref + operation_ref`. Application code never scans filesystem/keyring/process internals or invents deterministic names outside adapters.

`McpConnectorReadAdapter`, `McpConnectorWriteAdapter`는 Application이 생성한 `ValidatedConnectorToolBindingV1`을 받아 `ConnectorRuntimeRegistry` + injected descriptor expectations로 transport binding을 검증한 뒤 `MCPClientPort`를 호출하는 Core-side boundary adapter다. `McpOAuthCredentialAdapter`는 `connector_id`로 `ConnectorRuntimeRegistry + MCPClientPort`만 사용한다. 이 Adapter들은 `application/tool_registry/**`를 import/call하지 않는다. Provider-native API/SDK와 raw credential을 소유하지 않는다. `StdioMCPClientAdapter`는 `ConnectorRuntimeRegistry`로 connector_id를 정확히 하나의 active process handle에 resolve한다. Provider-specific operation/credential 구현은 해당 Connector MCP Server 내부 grammar를 따른다.

`StructuredInferenceRuntimeRouter`가 `StructuredInferencePort`의 **유일한 production binding**이다. LLM leaf placement/symbol은 다음 exact grammar로 닫는다.

```text
adapters/llm/<provider>/structured_inference.py → <Provider>StructuredInferenceAdapter
adapters/llm/<provider>/credential.py → <Provider>LlmCredentialAdapter
adapters/llm/<provider>/runtime_status.py → <Provider>LlmRuntimeStatusAdapter

adapters/llm/ollama/structured_inference.py → OllamaStructuredInferenceAdapter
adapters/llm/ollama/runtime_status.py → OllamaLlmRuntimeStatusAdapter
```

Router만 03/10의 requested mode·availability·fallback 규칙으로 inference leaf를 선택하고 `StructuredInferenceResultV1(actual_runtime, provider, model, fallback_reason, ...)`를 반환한다. leaf adapter는 Prompt 선택이나 fallback policy를 소유하지 않는다.

같은 closed binding rule을 provider-parameterized LLM support Ports에도 적용한다. `LlmCredentialPort`의 유일한 production binding은 `LlmCredentialRouter`, `LlmRuntimeStatusPort`의 유일한 production binding은 `LlmRuntimeStatusRouter`다. External API-provider credential/status leaves는 위 exact symbols를 사용하며 Router 내부 dependency다. Ollama는 `OllamaLlmRuntimeStatusAdapter`만 support-status leaf로 가지며 API credential이 없으므로 `adapters/llm/ollama/credential.py` production artifact는 금지한다. Application/API가 어떤 leaf도 직접 선택하지 않는다.

`<provider>`는 current Release authority가 승인/등록한 external API LLM provider의 repository package parameter다. **Repository Architecture는 concrete P0 API provider/model name을 closed identifier로 정하지 않는다.** 10/13의 current Release/configuration selection이 concrete provider/model을 정하기 전에는 구현자가 Gemini/OpenAI/기타 이름을 추측하거나 default로 고정하면 안 된다. 신규 API LLM Provider 추가는 release-approved provider registration + 위 leaf family + Router registration만 추가하며 Application owner/Port를 만들지 않는다.

Concrete adapter tests are exact mirrors:

```text
tests/unit/adapters/llm/<provider>/test_structured_inference.py
tests/unit/adapters/llm/<provider>/test_credential.py
tests/unit/adapters/llm/<provider>/test_runtime_status.py
tests/unit/adapters/llm/ollama/test_structured_inference.py
tests/unit/adapters/llm/ollama/test_runtime_status.py
```

Composition wiring만 concrete implementation을 선택할 수 있다.

## Local Runtime provisioning Adapter rule

`OllamaLocalRuntimeProvisioningAdapter` is the only concrete owner of runtime/model download, staging, Authenticode/hash/digest verification, installer invocation, existing-install detection, Ollama readiness and model preparation. It consumes a verified `ModelManifestV2`, a verified `LocalModelProductDecisionV2`, and stable `operation_ref`; Browser strings and Prompt/Agent output never reach command-line/download authority. It validates `product_decision.model_manifest_hash`, exact release version, two-tier completeness, and every tier binding against the Model Manifest before any side effect. The Adapter distinguishes `PREEXISTING` from `PRODUCT_PROVISIONED`, does not remove shared Ollama on product shutdown/uninstall, and exposes reconciliation through `LocalRuntimeProvisioningPort`.

`StructuredInferenceRuntimeRouter` receives `InferenceTierV1` and resolves it only through `LocalModelProductDecisionV2.active_profile`, then validates the resolved model identity/digest against `ModelManifestV2`. Leaf adapters receive an already-resolved model identity; no Application/Agent/provider leaf owns a competing tier→model table.

V1 parser/generator paths are migration baseline only. V2 activation requires old production caller/export/artifact authority zero.

## Connector Runtime Registry exact authority

Production connector process lookup authority는 **`ConnectorRuntimeRegistry` 하나만** 존재한다. 이것은 Port가 아니며 provider/tool semantics도 소유하지 않는다.

```text
adapters/connectors/runtime/connector_runtime_registry.py
→ ConnectorRuntimeRegistry
```

Canonical responsibility:

```text
register(connector_id, runtime_handle)
lookup_required(connector_id) -> opaque ConnectorRuntimeHandle
remove(connector_id)
list_registered_connector_ids()
```

`ConnectorRuntimeHandle`의 process-handle/stdio 내부 표현은 adapter-local implementation choice다. 등록 source는 `adapters/connectors/runtime/installed_connector_manifest.json`을 10의 verified Release Manifest와 대조해 `load_installed_connector_manifest()`가 반환한 exact row다. `api/composition.py`는 이 row의 `executable_path`를 spawn하고 `tool_projection_path` handshake를 검증한 뒤 runtime handle을 등록하며 P0는 `google_workspace` 하나다. `StdioMCPClientAdapter`의 list/call/restart/health는 반드시 이 Registry로 connector_id를 lookup한 뒤 **그 exact child process만** 대상으로 한다.

Signed Tool Registry와 역할을 합치지 않는다:

- `ConnectorRuntimeRegistry`: process-local connector_id → active runtime handle
- `SignedToolRegistry`: connector/resource/tool/effect/schema/policy-related semantic metadata

Canonical Service startup sequence:

```text
verified release-manifest.json
→ load_installed_connector_manifest()
→ load_signed_tool_registry()
→ SignedToolRegistry.descriptor_expectations(connector_id)
→ spawn exact executable_path
→ child loads exact tool_projection_path
→ handshake descriptor hash/schema exact-match
→ ConnectorRuntimeRegistry.register(connector_id, runtime_handle)
```

No provider switch, executable-name parsing, Adapter→Application Registry import, or second Tool Registry is allowed.

Tests:

```text
tests/unit/adapters/connectors/runtime/test_connector_runtime_registry.py
tests/architecture/connectors/test_connector_runtime_binding.py
```

Second Connector는 같은 `ConnectorRuntimeRegistry`에 runtime binding 하나를 추가하며 별도 connector-registry Port, generic service, provider-specific Core registry를 만들지 않는다.

## Connector Runtime · Signed Tool Registry · MCP Server process grammar

Core-side single authorities:

```text
application/tool_registry/signed_tool_registry.py → SignedToolRegistry
application/tool_registry/contracts/signed_tool_registry_entry.py → SignedToolRegistryEntryV1
ports/connector/contracts/validated_connector_tool_binding.py → ValidatedConnectorToolBindingV1

`ValidatedConnectorToolBindingV1` is a **shared Port-boundary value contract**, not an Application-owned concrete type. `SignedToolRegistry` materializes it; `ConnectorReadPort`/`ConnectorWritePort` accept it; outbound Connector adapters may import it from `ports/connector/contracts/**`. This avoids both `adapters/** → application/**` and any newly invented registry-shaped Port.
application/tool_registry/tool_registry_manifest.json → SignedToolRegistryManifestV1 implementation mirror
application/tool_registry/load_signed_tool_registry.py → load_signed_tool_registry()
adapters/connectors/runtime/installed_connector_manifest.json → InstalledConnectorManifestV1 implementation source
adapters/connectors/runtime/load_installed_connector_manifest.py → load_installed_connector_manifest()
adapters/connectors/runtime/connector_runtime_registry.py → ConnectorRuntimeRegistry
adapters/connectors/runtime/stdio_mcp_client.py → StdioMCPClientAdapter
adapters/connectors/runtime/mcp_oauth_credential.py → McpOAuthCredentialAdapter
```

`SignedToolRegistry` owns connector/resource/tool/effect/scope/retry/verification/recovery/schema metadata **inside Application** and materializes `ValidatedConnectorToolBindingV1`; Connector adapters consume only that immutable binding/descriptor expectation and never import the concrete Registry. `ConnectorRuntimeRegistry` owns only process-local `connector_id → process instance/stdio handle/handshake` binding.

Each registered Connector MCP Server uses this closed grammar; broad `mcp/server.py`, `connector_service.py`, provider manager buckets are prohibited. **`connector_package` is the repository package identity for one registered `connector_id`; it is not the Provider product/resource package.** It is explicitly mapped below and must not be inferred by splitting `connector_id` or Tool IDs:

| `connector_id` | provider namespace | `connector_package` | MCP Server root |
| --- | --- | --- | --- |
| `google_workspace` | `google` | `workspace` | `adapters/connectors/google/workspace/mcp_server/` |

New Connector registration adds exactly one row with `(connector_id, provider namespace, connector_package)` before implementation. A multi-product Connector still has **one** MCP Server root for that connector; Tool provider operations may live under separate product packages such as `google/gmail`, `google/tasks`, `google/calendar`.

```text
adapters/connectors/<provider>/<connector_package>/mcp_server/entrypoint.py → <Connector>McpServerEntrypoint
adapters/connectors/<provider>/<connector_package>/mcp_server/composition.py → <Connector>McpServerComposition
adapters/connectors/<provider>/<connector_package>/mcp_server/dispatch_tool.py → dispatch_tool
adapters/connectors/<provider>/<connector_package>/mcp_server/project_registry.py → project_registry
adapters/connectors/<provider>/<connector_package>/mcp_server/validate_claim_context.py → validate_claim_context
adapters/connectors/<provider>/<connector_package>/mcp_server/credential_provider.py → <Connector>CredentialProvider
```

P0 Google Workspace maps to `adapters/connectors/google/workspace/mcp_server/`. `project_registry.py` loads/verifies only the connector-specific `MCPToolProjectionManifestV1` selected by InstalledConnectorManifest and cannot import/consume the Core `SignedToolRegistry` or redefine semantic metadata. `dispatch_tool.py` dispatches a validated Tool ID to the exact operation-per-file provider adapter. `validate_claim_context.py` owns Claim signature/TTL/nonce/binding verification before WRITE handler invocation. `credential_provider.py` alone owns Google OAuth Token/Keyring application inside the MCP process.

Tests mirror `tests/unit/application/tool_registry/`, `tests/unit/adapters/connectors/runtime/`, and `tests/unit/adapters/connectors/<provider>/<connector_package>/mcp_server/`. Adding a Connector registers one runtime binding + Signed Tool Registry rows + one process-side grammar instance + operation-per-file provider adapters; it does not create another Application service or Tool Registry authority.

## Registered P0 Connector Tool → provider operation placement

Core `ConnectorReadPort`/`ConnectorWritePort`는 MCP tool invocation만 소유한다. **Provider-native API/SDK 호출은 Google Workspace MCP Server 내부의 아래 operation-per-file adapter가 소유한다.** 현재 registered Tool 하나가 새 semantic operation 하나를 요구하면 아래 grammar에 따라 정확히 하나의 canonical provider operation file을 추가하고 Tool Registry row와 함께 변경한다. 여러 Tool을 `gmail_service.py`, `tasks_service.py`, `calendar_service.py` 같은 broad production authority에 합치지 않는다.

| MCP Tool ID | Canonical provider operation path | Canonical symbol |
| --- | --- | --- |
| `gmail_search_threads` | `adapters/connectors/google/gmail/threads/search_threads.py` | `SearchThreadsOperation` |
| `gmail_get_thread` | `adapters/connectors/google/gmail/threads/get_thread.py` | `GetThreadOperation` |
| `gmail_get_message` | `adapters/connectors/google/gmail/messages/get_message.py` | `GetMessageOperation` |
| `gmail_get_attachment` | `adapters/connectors/google/gmail/attachments/get_attachment.py` | `GetAttachmentOperation` |
| `gmail_create_draft` | `adapters/connectors/google/gmail/drafts/create_draft.py` | `CreateDraftOperation` |
| `gmail_update_draft` | `adapters/connectors/google/gmail/drafts/update_draft.py` | `UpdateDraftOperation` |
| `gmail_get_draft` | `adapters/connectors/google/gmail/drafts/get_draft.py` | `GetDraftOperation` |
| `gmail_send` | `adapters/connectors/google/gmail/messages/send_message.py` | `SendMessageOperation` |
| `tasks_list_tasklists` | `adapters/connectors/google/tasks/tasklists/list_tasklists.py` | `ListTasklistsOperation` |
| `tasks_list_tasks` | `adapters/connectors/google/tasks/tasks/list_tasks.py` | `ListTasksOperation` |
| `tasks_get_task` | `adapters/connectors/google/tasks/tasks/get_task.py` | `GetTaskOperation` |
| `tasks_create_task` | `adapters/connectors/google/tasks/tasks/create_task.py` | `CreateTaskOperation` |
| `tasks_update_task` | `adapters/connectors/google/tasks/tasks/update_task.py` | `UpdateTaskOperation` |
| `tasks_delete_task` | `adapters/connectors/google/tasks/tasks/delete_task.py` | `DeleteTaskOperation` |
| `calendar_list_calendars` | `adapters/connectors/google/calendar/calendars/list_calendars.py` | `ListCalendarsOperation` |
| `calendar_list_events` | `adapters/connectors/google/calendar/events/list_events.py` | `ListEventsOperation` |
| `calendar_query_freebusy` | `adapters/connectors/google/calendar/freebusy/query_freebusy.py` | `QueryFreebusyOperation` |
| `calendar_get_event` | `adapters/connectors/google/calendar/events/get_event.py` | `GetEventOperation` |
| `calendar_create_event` | `adapters/connectors/google/calendar/events/create_event.py` | `CreateEventOperation` |
| `calendar_update_event` | `adapters/connectors/google/calendar/events/update_event.py` | `UpdateEventOperation` |
| `calendar_delete_event` | `adapters/connectors/google/calendar/events/delete_event.py` | `DeleteEventOperation` |

Tool-specific transport/schema validation remains owned by 07 Interface. Provider operation files translate validated MCP Tool input to provider-native API calls and normalize provider responses only; Policy, Approval, Domain lifecycle, Retry authority, Verification decision을 흡수하지 않는다. Shared low-level OAuth/client construction may be dependency-only infrastructure, but it may not become a second semantic operation authority.

## Domain Repository exact capability manifest

04의 persistence semantics를 구현하는 current Repository decomposition은 아래가 **유일한 production decomposition**이다. Repository는 persistence abstraction만 소유하고 lifecycle/business rule을 재정의하지 않는다.

| Persistence concern | Port / repository | SQLite adapter | Required callable surface | Primary caller | Test |
| --- | --- | --- | --- | --- | --- |
| Conversation | `ports/persistence/conversation_repository.py → ConversationRepository` | `adapters/persistence/sqlite/repositories/conversation_repository.py → SqliteConversationRepository` | `create`, `get`, `list_keyset`, `touch_updated_at` | conversation queries + `run.start_run` UoW | `tests/unit/adapters/persistence/sqlite/repositories/test_conversation_repository.py` |
| Message | `ports/persistence/message_repository.py → MessageRepository` | `adapters/persistence/sqlite/repositories/message_repository.py → SqliteMessageRepository` | `append_user_message`, `append_terminal_assistant_message`, `list_by_conversation_keyset` | `run.start_run`, terminal lifecycle handlers, message query | `tests/unit/adapters/persistence/sqlite/repositories/test_message_repository.py` |
| Run | `ports/persistence/run_repository.py → RunRepository` | `adapters/persistence/sqlite/repositories/run_repository.py → SqliteRunRepository` | `create`, `get`, `get_snapshot`, `find_open_by_conversation`, `update_if_version_and_status(run_id, expected_version, expected_statuses, values) -> bool` | Run lifecycle handlers | `tests/unit/adapters/persistence/sqlite/repositories/test_run_repository.py` |
| Plan | `ports/persistence/plan_repository.py → PlanRepository` | `adapters/persistence/sqlite/repositories/plan_repository.py → SqlitePlanRepository` | `insert_revision`, `get_current`, `load_bundle`, `record_review_result`, `update_if_version_and_status(plan_id, expected_version, expected_statuses, values) -> bool` | plan lifecycle + review persistence | `tests/unit/adapters/persistence/sqlite/repositories/test_plan_repository.py` |
| Action | `ports/persistence/action_repository.py → ActionRepository` | `adapters/persistence/sqlite/repositories/action_repository.py → SqliteActionRepository` | `insert_for_plan`, `get`, `list_for_plan`, `update_if_version_and_status(action_id, expected_version, expected_statuses, values) -> bool`, `list_dependents`, `is_dependency_ready(action_id) -> bool` | Action/Claim/Attempt/Verification handlers | `tests/unit/adapters/persistence/sqlite/repositories/test_action_repository.py` |
| Approval | `ports/persistence/approval_repository.py → ApprovalRepository` | `adapters/persistence/sqlite/repositories/approval_repository.py → SqliteApprovalRepository` | `insert_active_snapshot`, `get_active_for_action`, `list_active_for_plan(plan_id) -> list[Approval]`, `update_if_status(approval_id, expected_status, values) -> bool` | Action/Approval/Claim lifecycle UoW + published-Plan supersession cleanup | `tests/unit/adapters/persistence/sqlite/repositories/test_approval_repository.py` |
| Execution Attempt | `ports/persistence/execution_attempt_repository.py → ExecutionAttemptRepository` | `adapters/persistence/sqlite/repositories/execution_attempt_repository.py → SqliteExecutionAttemptRepository` | `insert_claimed`, `get`, `get_active_for_approval`, `list_reconciliation_candidates(limit) -> list[ExecutionReconciliationCandidateV1]`, `update_if_version_and_status(execution_attempt_id, expected_version, expected_statuses, values) -> bool` | Claim + execution-attempt handlers + startup `ReconcileInflightExecutionsHandler` | `tests/unit/adapters/persistence/sqlite/repositories/test_execution_attempt_repository.py` |
| Verification | `ports/persistence/verification_repository.py → VerificationRepository` | `adapters/persistence/sqlite/repositories/verification_repository.py → SqliteVerificationRepository` | `insert`, `get_latest_for_attempt`, `list_for_action` | `verification.store_verification`, snapshot query | `tests/unit/adapters/persistence/sqlite/repositories/test_verification_repository.py` |
| Recovery | `ports/persistence/recovery_repository.py → RecoveryRepository` | `adapters/persistence/sqlite/repositories/recovery_repository.py → SqliteRecoveryRepository` | `store_context`, `load_current_context`, `clear_context`, `list_candidates_bounded` | `require_recovery`, `resolve_recovery`, startup reconciliation | `tests/unit/adapters/persistence/sqlite/repositories/test_recovery_repository.py` |
| ResourceRef | `ports/persistence/resource_ref_repository.py → ResourceRefRepository` | `adapters/persistence/sqlite/repositories/resource_ref_repository.py → SqliteResourceRefRepository` | `upsert_bound_ref`, `get`, `list_for_run_bounded` | resource_ref use cases / evidence materialization | `tests/unit/adapters/persistence/sqlite/repositories/test_resource_ref_repository.py` |
| Evidence | `ports/persistence/evidence_repository.py → EvidenceRepository` | `adapters/persistence/sqlite/repositories/evidence_repository.py → SqliteEvidenceRepository` | `insert_bounded`, `list_for_run`, `list_for_action` | Retrieval/Planning persistence projections | `tests/unit/adapters/persistence/sqlite/repositories/test_evidence_repository.py` |
| Command Receipt | `ports/persistence/command_receipt_repository.py → CommandReceiptRepository` | `adapters/persistence/sqlite/repositories/command_receipt_repository.py → SqliteCommandReceiptRepository` | `get_by_command_id`, `reserve_or_replay`, `store_result` | Domain aggregate lifecycle/state-changing handlers governed by the Domain Command Receipt contract only; non-Domain commands use `OperationalCommandReplayPort` | `tests/unit/adapters/persistence/sqlite/repositories/test_command_receipt_repository.py` |
| Retention | `ports/persistence/retention_repository.py → RetentionRepository` | `adapters/persistence/sqlite/repositories/retention_repository.py → SqliteRetentionRepository` | `purge_batch(cutoffs, batch_limit)` only; `cutoffs` is the 04-typed category cutoff set derived from persisted P0 `retention_days(1..30)` plus fixed Audit 90-day rule; purge ordering preserves open-run/replay/audit invariants | `application/maintenance/purge_retention.py → PurgeRetentionHandler` inside `UnitOfWork` | `tests/unit/adapters/persistence/sqlite/repositories/test_retention_repository.py` + `tests/unit/application/maintenance/test_purge_retention.py` |

`update_if_version_and_status(...)` is the **exact public mutation method symbol** on `RunRepository`, `PlanRepository`, `ActionRepository`, and `ExecutionAttemptRepository`. `ApprovalRepository` uses the exact `update_if_status(approval_id, expected_status, values) -> bool` symbol because Approval concurrency is guarded by current status plus the enclosing Action/Command expected-version UoW rather than a separate Approval version authority. `expected_statuses` is the caller-authorized source-state set and `values` contains only already-validated persisted fields for that owner. The repository performs identity/version/status compare-and-set and returns success/failure only; it does **not** choose next status, evaluate lifecycle guards, or infer command semantics. Lifecycle handlers may not add alternate public mutation aliases such as `transition_status`, `compare_and_set`, `apply_transition`, `update_status`, or command-specific repository methods. SQLite adapters implement the same method name/signature.

Atomicity rule:

```text
Application Domain lifecycle handler
→ UnitOfWork
→ CommandReceiptRepository
→ required owner repositories
→ required AuditEventRepository
→ COMMIT
```

`ClaimExecution` is **not** a `ClaimRepository`: its atomic mutation coordinates `PlanRepository + ActionRepository + ApprovalRepository + ExecutionAttemptRepository + CommandReceiptRepository + AuditEventRepository` in one `UnitOfWork`. The handler reads `PlanRepository.get_current(run_id)` inside that same UoW and requires the Action's owning Plan to equal the current published `WAITING_APPROVAL` Plan before any Action/Approval/Attempt mutation. A concurrent `BeginPlanning` supersession and stale Claim therefore serialize on the same SQLite write transaction; whichever commits second must observe the changed parent authority and fail its guard rather than create a stale Attempt.

Published-Plan `BeginPlanning` and `ResolveRecovery(CREATE_CORRECTIVE_PLAN)` are compound lifecycle UoWs over existing repositories: `ApprovalRepository.list_active_for_plan(old_plan_id)` enumerates the exact rows to close, `ApprovalRepository.update_if_status(... ACTIVE → REVOKED)` revokes each, followed by `PlanRepository.update_if_version_and_status(... → SUPERSEDED)`, Run transition/Receipt/Audit, then commit. This is an internal Approval-row effect of the owning Run/Recovery command, **not** a new `RevokeApproval` Application use case or command-specific repository method. Old Action rows may remain historical but no later mutable command/Claim may treat them as current authority.

Likewise no `GenericRepository`, `DomainRepository`, `CRUDRepository`, state setter, or hidden dependency-result repository may be added.

Plan `load_bundle` is a read projection over Plan + Action/dependency/evidence relations; it does not take mutable Action lifecycle authority away from `ActionRepository`. `RecoveryRepository` stores/loads the durable RecoveryContext required by 04/State Contract; its exact physical table/column/JSON realization remains a 04 implementation choice.

`PurgeRetentionHandler` is a narrow maintenance orchestration that reads the persisted `retention_days`, validates the 01-B P0 range through the canonical Settings contract, derives only the 04-owned typed category cutoffs, opens one `UnitOfWork`, calls `RetentionRepository.purge_batch`, and emits the required 11-owned purge Audit. It does not decide which data category is retention-controlled. Trigger cadence/timer implementation is Infrastructure configuration; no `RetentionService`/manager/scheduler semantic authority is created.

## Observability persistence and transaction boundary

```text
ports/persistence/unit_of_work.py                         → UnitOfWork
adapters/persistence/sqlite/unit_of_work.py              → SqliteUnitOfWork
ports/persistence/trace_event_repository.py               → TraceEventRepository
adapters/persistence/sqlite/repositories/trace_event_repository.py → SqliteTraceEventRepository
ports/persistence/audit_event_repository.py               → AuditEventRepository
adapters/persistence/sqlite/repositories/audit_event_repository.py → SqliteAuditEventRepository
```

Callable contract:

- `TraceEventRepository.append(event)`, `list_page(cursor, limit)`, `purge_before(timestamp_ms)`; Trace writes may use an independent short UoW and never become Domain truth.
- `AuditEventRepository.append(event)`, `list_page(cursor, limit)`, `purge_before(timestamp_ms)`; required lifecycle Audit append occurs only inside the same `UnitOfWork` as CommandReceipt + Domain mutation.
- `UnitOfWork.commit()` is allowed only after all deterministic guards and repository writes succeed. `rollback()` removes Receipt reservation, Domain mutation, and required Audit together.
- Connector/Provider/MCP/LLM external I/O is forbidden while a `SqliteUnitOfWork` transaction is open. Execution dispatch, Verification reread, Recovery lookup occur outside transaction; their results are persisted by a later short UoW.


## SSE Event Buffer boundary

```text
ports/system/sse_event_buffer_port.py          → SseEventBufferPort
adapters/system/memory/sse_event_buffer.py     → InMemorySseEventBuffer
```

This buffer is process-local UI projection infrastructure only. Capacity, terminal TTL, and replay query limit are bounded **Infrastructure configuration choices owned by 10**, not Repository Architecture constants. It must not be imported by Domain, must not replace Checkpoint/Trace/Audit, and may be lost on restart; `CURSOR_EXPIRED → Run Snapshot fallback` is the required SSE recovery contract.

## Run Retrieval Cache boundary

```text
ports/system/run_retrieval_cache_port.py       → RunRetrievalCachePort
adapters/system/memory/run_retrieval_cache.py  → InMemoryRunRetrievalCache
```

`SqliteCheckpointAdapter` writes the bounded `GraphCheckpointEnvelopeV1.retrieval_cache_requirements` projection alongside the opaque blob so Application reconciliation can detect missing cache dependencies without blob deserialization; this metadata contains no raw Connector result/token.

This cache is process-local Retrieval infrastructure, not Domain persistence or LangGraph State. `put_read_result/resolve_read_result/discard_run` are its only public lifetime surface. `api/composition.py` binds one instance per Service process. Raw continuation must not appear in SQLite, checkpoint metadata/blob, Prompt, Trace, or Audit. Capacity/eviction bounds are **Infrastructure choices owned by 10**; eviction or process restart may make a handle unavailable, and required-handle loss is normalized only through `run.reconcile_retrieval_cache_restart → RETRIEVAL_CACHE_RESTART`, never by reconstructing `next_page_token` or using SSE `CURSOR_EXPIRED` semantics.

### OperationalCommandReplayPort boundary rule

`OperationalCommandReplayPort` is a system Port, not a Domain repository and not a semantic owner. `api/composition.py` binds it once to `FilesystemOperationalCommandReplayAdapter`. Every non-Domain command handler with `command_id` uses it before its operation Port. Domain lifecycle handlers must not use it; they continue to use `CommandReceiptRepository`.
