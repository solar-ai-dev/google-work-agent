# Google Work Agent — Ports / Outbound Adapters / Connector Canonical ↔ Current Mapping

**Repository:** `solar-ai-dev/google-work-agent`  
**Branch:** `refactor/canonical-architecture-migration`  
**Investigation SHA:** `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`  
**Mode:** `READ_ONLY_MAPPING`

## 1. Bounded universe

- `STR-062..109`: 24 non-persistence Port↔Adapter pairs = **48 rows**
- `STR-110..144`: Signed Tool Registry / Connector Runtime / Google Workspace MCP / provider operations = **35 rows**
- Adjacent contract/runtime rows `STR-302,304,314,328,329,333,334` = **7 rows**
- **Total = 90 rows**

Exact canonical-path presence at the frozen SHA:

```text
Port/Adapter rows                 48 / 48
Registry/MCP/provider rows        20 / 35
Adjacent contract/runtime rows     4 / 7
-----------------------------------------
Exact structural paths            72 / 90
```

Exact-path presence is not a behavioral PASS. In particular the current Connector read/write adapters use `GoogleWorkspaceGateway` directly instead of the canonical `ValidatedConnectorToolBindingV1 → ConnectorRuntimeRegistry → MCPClientPort` boundary.

## Non-persistence Port / Adapter rows

| ID | Canonical responsibility | Canonical target | Current implementation | Behavior | Structural | Disposition | Required action |
|---|---|---|---|---|---|---|---|
| STR-062 | ConnectorReadPort | `ports/connector/connector_read_port.py` → `ConnectorReadPort` | exact path/symbol present | **PARTIAL** | **FULL** | **TARGETED_CORRECTION** | Align ConnectorReadPort request with ValidatedConnectorToolBindingV1 and connector-neutral read contract; preserve existing read normalization semantics. |
| STR-063 | McpConnectorReadAdapter | `adapters/connectors/runtime/mcp_connector_read.py` → `McpConnectorReadAdapter` | exact path/symbol present | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve acquisition/read normalization, but replace direct GoogleWorkspaceGateway dependency with validated binding + ConnectorRuntimeRegistry + MCPClientPort. |
| STR-064 | ConnectorWritePort | `ports/connector/connector_write_port.py` → `ConnectorWritePort` | exact path/symbol present | **PARTIAL** | **FULL** | **TARGETED_CORRECTION** | Align ConnectorWritePort with validated connector binding and MCP-only external I/O boundary. |
| STR-065 | McpConnectorWriteAdapter | `adapters/connectors/runtime/mcp_connector_write.py` → `McpConnectorWriteAdapter` | exact path/symbol present | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve write argument/verification operation composition; rewire through validated binding + ConnectorRuntimeRegistry + MCPClientPort instead of direct GoogleWorkspaceGateway/provider operation calls from Core. |
| STR-066 | MCPClientPort | `ports/connector/mcp_client_port.py` → `MCPClientPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-067 | StdioMCPClientAdapter | `adapters/connectors/runtime/stdio_mcp_client.py` → `StdioMCPClientAdapter` | exact path/symbol present | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve stdio protocol/artifact verification/process mechanics; stop owning per-descriptor connector selection and resolve connector_id through single ConnectorRuntimeRegistry. |
| STR-068 | OAuthCredentialPort | `ports/connector/oauth_credential_port.py` → `OAuthCredentialPort` | exact path/symbol present | **PARTIAL** | **FULL** | **MOVE_RENAME + TARGETED_CORRECTION** | Current file is an alias of GoogleOAuthCredentialProvider; converge to connector-parameterized OAuthCredentialPort contract. |
| STR-069 | McpOAuthCredentialAdapter | `adapters/connectors/runtime/mcp_oauth_credential.py` → `McpOAuthCredentialAdapter` | exact path/symbol present | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve MCP control-call behavior; add connector_id → ConnectorRuntimeRegistry + MCPClientPort selection instead of one injected transport. |
| STR-070 | StructuredInferencePort | `ports/llm/structured_inference_port.py` → `StructuredInferencePort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-071 | StructuredInferenceRuntimeRouter | `adapters/llm/runtime/structured_inference_router.py` → `StructuredInferenceRuntimeRouter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-072 | LlmCredentialPort | `ports/llm/llm_credential_port.py` → `LlmCredentialPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-073 | LlmCredentialRouter | `adapters/llm/runtime/llm_credential_router.py` → `LlmCredentialRouter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-074 | LlmRuntimeStatusPort | `ports/llm/llm_runtime_status_port.py` → `LlmRuntimeStatusPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-075 | LlmRuntimeStatusRouter | `adapters/llm/runtime/llm_runtime_status_router.py` → `LlmRuntimeStatusRouter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-076 | SecretStorePort | `ports/keyring/secret_store_port.py` → `SecretStorePort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-077 | OsKeyringSecretStoreAdapter | `adapters/keyring/os_keyring_secret_store.py` → `OsKeyringSecretStoreAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-078 | CheckpointPort | `ports/system/checkpoint_port.py` → `CheckpointPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-079 | SqliteCheckpointAdapter | `adapters/system/sqlite_checkpoint.py` → `SqliteCheckpointAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-080 | RunRetrievalCachePort | `ports/system/run_retrieval_cache_port.py` → `RunRetrievalCachePort` | exact path/symbol present | **PARTIAL** | **FULL** | **TARGETED_CORRECTION** | Replace generic get/put/delete object cache contract with typed RunRetrievalCache entry/resolve/discard_run semantics. |
| STR-081 | InMemoryRunRetrievalCache | `adapters/system/memory/run_retrieval_cache.py` → `InMemoryRunRetrievalCache` | exact path/symbol present | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve in-memory storage; implement typed run/route/query binding, FOUND\|EXHAUSTED\|MISSING\|CROSS_RUN\|BINDING_MISMATCH, and discard_run. |
| STR-082 | WorkflowExecutionPort | `ports/system/workflow_execution_port.py` → `WorkflowExecutionPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-083 | BackgroundRunExecutorAdapter | `adapters/langgraph/runtime/background_run_executor.py` → `BackgroundRunExecutorAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-084 | SettingsPort | `ports/system/settings_port.py` → `SettingsPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-085 | JsonSettingsAdapter | `adapters/system/json_settings.py` → `JsonSettingsAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-086 | RuntimeModePort | `ports/system/runtime_mode_port.py` → `RuntimeModePort` | exact path/symbol present | **PARTIAL** | **FULL** | **TARGETED_CORRECTION** | Current Port only exposes current_mode(); add canonical mutable requested-mode operation semantics needed by runtime_mode Application owner. |
| STR-087 | ProcessRuntimeModeAdapter | `adapters/system/process_runtime_mode.py` → `ProcessRuntimeModeAdapter` | exact path/symbol present | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve process-local mode state but support validated mode update rather than frozen dataclass-only current_mode. |
| STR-088 | BackupPort | `ports/system/backup_port.py` → `BackupPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-089 | FilesystemBackupAdapter | `adapters/system/filesystem_backup.py` → `FilesystemBackupAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-090 | DiagnosticsPort | `ports/system/diagnostics_port.py` → `DiagnosticsPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-091 | FilesystemDiagnosticsAdapter | `adapters/system/filesystem_diagnostics.py` → `FilesystemDiagnosticsAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-092 | ShutdownPort | `ports/system/shutdown_port.py` → `ShutdownPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-093 | ProcessShutdownAdapter | `adapters/system/process_shutdown.py` → `ProcessShutdownAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-094 | OperationalCommandReplayPort | `ports/system/operational_command_replay_port.py` → `OperationalCommandReplayPort` | exact path/symbol present | **PARTIAL** | **FULL** | **TARGETED_CORRECTION** | Keep reservation API; split typed replay contract values to ports/system/contracts/operational_command_replay.py and add canonical reconcile result. |
| STR-095 | FilesystemOperationalCommandReplayAdapter | `adapters/system/filesystem_operational_command_replay.py` → `FilesystemOperationalCommandReplayAdapter` | exact path/symbol present | **NEAR_FULL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve crash-safe filesystem reservation journal; align exact typed contract and operation-specific reconcile surfaces. |
| STR-096 | AttachmentStagingPort | `ports/system/attachment_staging_port.py` → `AttachmentStagingPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-097 | FilesystemAttachmentStagingAdapter | `adapters/system/filesystem_attachment_staging.py` → `FilesystemAttachmentStagingAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-098 | ClockPort | `ports/system/clock_port.py` → `ClockPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-099 | SystemClockAdapter | `adapters/system/system_clock.py` → `SystemClockAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-100 | UUIDPort | `ports/system/uuid_port.py` → `UUIDPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-101 | Uuid4Adapter | `adapters/system/uuid4.py` → `Uuid4Adapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-102 | HardwareProbePort | `ports/system/hardware_probe_port.py` → `HardwareProbePort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-103 | WindowsHardwareProbeAdapter | `adapters/system/windows_hardware_probe.py` → `WindowsHardwareProbeAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-104 | BrowserLauncherPort | `ports/system/browser_launcher_port.py` → `BrowserLauncherPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-105 | DefaultBrowserLauncherAdapter | `adapters/system/default_browser_launcher.py` → `DefaultBrowserLauncherAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-106 | ComponentCircuitStatePort | `ports/system/component_circuit_state_port.py` → `ComponentCircuitStatePort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-107 | ProcessComponentCircuitStateAdapter | `adapters/system/process_component_circuit_state.py` → `ProcessComponentCircuitStateAdapter` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-108 | SseEventBufferPort | `ports/system/sse_event_buffer_port.py` → `SseEventBufferPort` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |
| STR-109 | InMemorySseEventBuffer | `adapters/system/memory/sse_event_buffer.py` → `InMemorySseEventBuffer` | exact path/symbol present | **FULL** | **FULL** | **KEEP** | Keep current Port/Adapter authority. |

## Registry / MCP server / provider operation rows

| ID | Canonical responsibility | Canonical target | Current implementation | Behavior | Structural | Disposition | Required action |
|---|---|---|---|---|---|---|---|
| STR-110 | Signed Tool Registry | `application/tool_registry/signed_tool_registry.py` → `SignedToolRegistry` | domain/tool_registry.py → SignedToolRegistry + ConnectorToolCatalog | **NEAR_FULL** | **PATH** | **MOVE + SPLIT + TARGETED_CORRECTION** | Move SignedToolRegistry to application/tool_registry; keep connector catalog/process lookup concerns separate; add canonical bind/descriptor expectations. |
| STR-111 | SignedToolRegistryEntryV1 | `application/tool_registry/contracts/signed_tool_registry_entry.py` → `SignedToolRegistryEntryV1` | domain/tool_registry.py → ToolRegistryEntry | **PARTIAL** | **PATH+NAME** | **MOVE_RENAME + TARGETED_CORRECTION** | Move/rename to SignedToolRegistryEntryV1 and align the exact 07 closed fields/schema/version semantics. |
| STR-112 | ValidatedConnectorToolBindingV1 | `ports/connector/contracts/validated_connector_tool_binding.py` → `ValidatedConnectorToolBindingV1` | no ports/connector/contracts/ package | **NONE_AS_TYPED_CONTRACT** | **NONE** | **CREATE (reuse registry snapshot semantics)** | Create shared validated Port-boundary value from already-validated registry entry/binding facts; do not create a second registry. |
| STR-113 | SignedToolRegistryManifestV1 | `application/tool_registry/tool_registry_manifest.json` → `SignedToolRegistryManifestV1` | manifest payload generation exists in stdio_mcp_client.py; no canonical JSON artifact | **PARTIAL** | **NONE** | **SPLIT + MATERIALIZE** | Extract manifest projection from current registry/stdio logic and materialize canonical tool_registry_manifest.json exact mirror. |
| STR-114 | load_signed_tool_registry() | `application/tool_registry/load_signed_tool_registry.py` → `load_signed_tool_registry()` | build_p0_tool_registry()/build_google_workspace_tool_registry + stdio manifest validation; no loader | **PARTIAL** | **NONE** | **CREATE + MERGE** | Create single load_signed_tool_registry() by merging current builder/manifest validation semantics and release-hash verification. |
| STR-115 | InstalledConnectorManifestV1 | `adapters/connectors/runtime/installed_connector_manifest.json` → `InstalledConnectorManifestV1` | stdio_mcp_client.py → MCPArtifactConfig/MCPConnectorDescriptor; no installed manifest | **PARTIAL** | **NONE** | **CREATE + MERGE** | Materialize InstalledConnectorManifestV1 from current descriptor/process metadata under verified Release Manifest authority. |
| STR-116 | load_installed_connector_manifest() | `adapters/connectors/runtime/load_installed_connector_manifest.py` → `load_installed_connector_manifest()` | no loader; artifact validation embedded in StdioMCPClientAdapter | **PARTIAL** | **NONE** | **SPLIT + CREATE** | Extract installed-manifest loading/validation from current artifact config/client startup logic. |
| STR-117 | Connector Runtime Registry | `adapters/connectors/runtime/connector_runtime_registry.py` → `ConnectorRuntimeRegistry` | no ConnectorRuntimeRegistry; process binding owned per StdioMCPClientAdapter instance | **PARTIAL** | **NONE** | **CREATE + MERGE** | Centralize connector_id→runtime handle from existing per-client process state; then make StdioMCPClientAdapter resolve through it. |
| STR-118 | GoogleWorkspaceMcpServerEntrypoint | `adapters/connectors/google/workspace/mcp_server/entrypoint.py` → `GoogleWorkspaceMcpServerEntrypoint` | google/mcp/verified_server.py + 92KB workspace_tools.py broad MCP server | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Split reusable server/OAuth/dispatch/claim/tool-projection logic into canonical google/workspace/mcp_server operation-per-file owner. |
| STR-119 | GoogleWorkspaceMcpServerComposition | `adapters/connectors/google/workspace/mcp_server/composition.py` → `GoogleWorkspaceMcpServerComposition` | google/mcp/verified_server.py + 92KB workspace_tools.py broad MCP server | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Split reusable server/OAuth/dispatch/claim/tool-projection logic into canonical google/workspace/mcp_server operation-per-file owner. |
| STR-120 | dispatch_tool | `adapters/connectors/google/workspace/mcp_server/dispatch_tool.py` → `dispatch_tool` | google/mcp/verified_server.py + 92KB workspace_tools.py broad MCP server | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Split reusable server/OAuth/dispatch/claim/tool-projection logic into canonical google/workspace/mcp_server operation-per-file owner. |
| STR-121 | project_registry | `adapters/connectors/google/workspace/mcp_server/project_registry.py` → `project_registry` | google/mcp/verified_server.py + 92KB workspace_tools.py broad MCP server | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Split reusable server/OAuth/dispatch/claim/tool-projection logic into canonical google/workspace/mcp_server operation-per-file owner. |
| STR-122 | validate_claim_context | `adapters/connectors/google/workspace/mcp_server/validate_claim_context.py` → `validate_claim_context` | google/mcp/verified_server.py + 92KB workspace_tools.py broad MCP server | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Split reusable server/OAuth/dispatch/claim/tool-projection logic into canonical google/workspace/mcp_server operation-per-file owner. |
| STR-123 | GoogleWorkspaceCredentialProvider | `adapters/connectors/google/workspace/mcp_server/credential_provider.py` → `GoogleWorkspaceCredentialProvider` | google/mcp/verified_server.py + 92KB workspace_tools.py broad MCP server | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Split reusable server/OAuth/dispatch/claim/tool-projection logic into canonical google/workspace/mcp_server operation-per-file owner. |
| STR-124 | gmail_search_threads | `adapters/connectors/google/gmail/threads/search_threads.py` → `SearchThreadsOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-125 | gmail_get_thread | `adapters/connectors/google/gmail/threads/get_thread.py` → `GetThreadOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-126 | gmail_get_message | `adapters/connectors/google/gmail/messages/get_message.py` → `GetMessageOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-127 | gmail_get_attachment | `adapters/connectors/google/gmail/attachments/get_attachment.py` → `GetAttachmentOperation` | exact attachments/get_attachment.py absent; attachment read logic remains in broad google/mcp/workspace_tools.py | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract existing Gmail attachment fetch/bounds logic into canonical GetAttachmentOperation; do not rewrite from scratch. |
| STR-128 | gmail_create_draft | `adapters/connectors/google/gmail/drafts/create_draft.py` → `CreateDraftOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-129 | gmail_update_draft | `adapters/connectors/google/gmail/drafts/update_draft.py` → `UpdateDraftOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-130 | gmail_get_draft | `adapters/connectors/google/gmail/drafts/get_draft.py` → `GetDraftOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-131 | gmail_send | `adapters/connectors/google/gmail/messages/send_message.py` → `SendMessageOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-132 | tasks_list_tasklists | `adapters/connectors/google/tasks/tasklists/list_tasklists.py` → `ListTasklistsOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-133 | tasks_list_tasks | `adapters/connectors/google/tasks/tasks/list_tasks.py` → `ListTasksOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-134 | tasks_get_task | `adapters/connectors/google/tasks/tasks/get_task.py` → `GetTaskOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-135 | tasks_create_task | `adapters/connectors/google/tasks/tasks/create_task.py` → `CreateTaskOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-136 | tasks_update_task | `adapters/connectors/google/tasks/tasks/update_task.py` → `UpdateTaskOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-137 | tasks_delete_task | `adapters/connectors/google/tasks/tasks/delete_task.py` → `DeleteTaskOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-138 | calendar_list_calendars | `adapters/connectors/google/calendar/calendars/list_calendars.py` → `ListCalendarsOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-139 | calendar_list_events | `adapters/connectors/google/calendar/events/list_events.py` → `ListEventsOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-140 | calendar_query_freebusy | `adapters/connectors/google/calendar/freebusy/query_freebusy.py` → `QueryFreebusyOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-141 | calendar_get_event | `adapters/connectors/google/calendar/events/get_event.py` → `GetEventOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-142 | calendar_create_event | `adapters/connectors/google/calendar/events/create_event.py` → `CreateEventOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-143 | calendar_update_event | `adapters/connectors/google/calendar/events/update_event.py` → `UpdateEventOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |
| STR-144 | calendar_delete_event | `adapters/connectors/google/calendar/events/delete_event.py` → `DeleteEventOperation` | exact provider operation file/symbol present | **FULL** | **FULL** | **KEEP** | Keep provider operation implementation; rewire callers so only canonical MCP server dispatches it. |

## Adjacent connector/workflow contract rows

| ID | Canonical responsibility | Canonical target | Current implementation | Behavior | Structural | Disposition | Required action |
|---|---|---|---|---|---|---|---|
| STR-302 | Installed Connector manifest | `adapters/connectors/runtime/installed_connector_manifest.json → InstalledConnectorManifestV1` | same missing installed manifest as STR-115 | **PARTIAL** | **NONE** | **CREATE + MERGE** | Same canonical installed-manifest realization; this row is contract/install coverage, not a second artifact. |
| STR-304 | Validated Tool binding contract | `ports/connector/contracts/validated_connector_tool_binding.py` | same missing ValidatedConnectorToolBindingV1 as STR-112 | **NONE_AS_TYPED_CONTRACT** | **NONE** | **CREATE** | Same shared Port-boundary contract; no duplicate type. |
| STR-314 | same-Run workflow/profile binding typed contract only | `ports/system/contracts/workflow_binding.py` → `GraphProfileIdV1, WorkflowBindingV1` | ports/system/contracts/workflow_binding.py exact | **FULL** | **FULL** | **KEEP** | Keep exact WorkflowBindingV1/GraphProfileIdV1 contract. |
| STR-328 | handoff reconciliation loop | `adapters/system/workflow_handoff_reconciliation_loop.py` → `WorkflowHandoffReconciliationLoop` | adapters/system/workflow_handoff_reconciliation_loop.py exact | **FULL** | **FULL** | **KEEP** | Keep thin wake/timer driving adapter; it already calls RedriveWorkflowHandoffsHandler. |
| STR-329 | durable workflow handoff contracts | `ports/system/contracts/workflow_handoff.py` → `WorkflowHandoffStageV1 / WorkflowHandoffV1 / WorkflowExecutionBindingV1 / WorkflowExecutionAdmissionV1 / WorkflowExecutionReleaseReasonV1 / WorkflowExecutionSettlementV1 / WorkflowControlEnvelopeV1 / WorkflowExecutionSubmissionV2` | ports/system/contracts/workflow_handoff.py exact | **FULL** | **FULL** | **KEEP** | Keep durable handoff/admission/control contracts. |
| STR-333 | retrieval head | `ports/system/contracts/retrieval_head.py` → `RetrievalHeadV1` | ports/system/contracts/retrieval_head.py exact | **FULL** | **FULL** | **KEEP** | Keep RetrievalHeadV1 typed metadata contract. |
| STR-334 | non-Domain operational replay | `ports/system/contracts/operational_command_replay.py` → `OperationalCommandContextV1 / OperationalReplayDecisionV2 / OperationalReconcileResultV1` | OperationalCommandContextV1/OperationalReplayDecisionV2 live inside operational_command_replay_port.py; contract file absent | **PARTIAL** | **PATH** | **SPLIT + MOVE + TARGETED_CORRECTION** | Move typed values into canonical contracts/operational_command_replay.py and add OperationalReconcileResultV1; Port imports the contract. |

## 5. Current → Canonical reverse mapping — hidden / broad authority

| Current authority | Finding | Disposition |
|---|---|---|
| `domain/tool_registry.py` | `SignedToolRegistry`, `ToolRegistryEntry`, `ConnectorToolCatalog` currently own Application/runtime registry semantics in Domain; exported through `domain/__init__.py`. | **MOVE/SPLIT/MERGE → canonical application/tool_registry; delete old concrete Domain authority after callers cut over** |
| `adapters/connectors/runtime/mcp_connector_read.py` | Exact canonical path, but Core adapter directly consumes `GoogleWorkspaceGateway` and orchestration contracts. It is not MCP-backed in the canonical sense. | **KEEP useful read normalization + TARGETED REWIRE** |
| `adapters/connectors/runtime/mcp_connector_write.py` | Exact path but imports provider operation classes and invokes them through `GoogleWorkspaceGateway` directly from Core. | **KEEP operation composition + TARGETED REWIRE through binding/registry/MCPClientPort** |
| `adapters/connectors/runtime/stdio_mcp_client.py` | Strong stdio/artifact/process code, but it owns a single `MCPConnectorDescriptor`/process directly; no central `ConnectorRuntimeRegistry`. | **KEEP process mechanics + SPLIT runtime-selection authority** |
| `adapters/connectors/google/mcp/workspace_tools.py` | ~92KB broad child-process authority: OAuth, credentials, claim validation, provider calls, dispatch and tool handling. | **SPLIT + MOVE into google/workspace/mcp_server + provider operation files; delete broad authority after cut-over** |
| `adapters/connectors/google/mcp/verified_server.py` | Existing server entry/verification material under noncanonical package. | **MOVE/SPLIT/MERGE into canonical MCP server entry/composition** |
| `ports/connector/oauth_credential_port.py` | Canonical path exists but is an alias of Google-specific `GoogleOAuthCredentialProvider`. | **MOVE_RENAME/TARGETED connector-neutral contract correction** |
| `ports/system/operational_command_replay_port.py` | Owns both Port and typed replay values; canonical contract file is absent. | **SPLIT typed values to contracts/operational_command_replay.py** |

## 6. High-risk findings

1. **External Connector I/O boundary is not closed.** `McpConnectorReadAdapter` and `McpConnectorWriteAdapter` bypass `ConnectorRuntimeRegistry + MCPClientPort` through `GoogleWorkspaceGateway`.
2. **ConnectorRuntimeRegistry is absent.** The current stdio client owns descriptor/process state per instance.
3. **InstalledConnectorManifestV1 and loader are absent.** Current artifact/process metadata is embedded in `MCPArtifactConfig/MCPConnectorDescriptor`.
4. **Signed Tool Registry is misplaced in Domain.** The semantic implementation is valuable and should be moved, not rewritten.
5. **ValidatedConnectorToolBindingV1 is absent.** A single shared Port-boundary value contract must be created from current validated registry facts.
6. **Google Workspace MCP server is a broad legacy island.** Canonical six-file MCP server grammar is 0/6 exact while reusable logic is concentrated in `google/mcp/workspace_tools.py` and `verified_server.py`.
7. **Provider operation preservation is high.** 20/21 canonical provider operation files already exist; only Gmail attachment exact operation is missing and its behavior is reusable from the broad MCP module.
8. **RunRetrievalCachePort is structurally present but semantically too generic.** It currently exposes `get/put/delete(object)` rather than typed binding/result semantics.
9. **Operational replay contract split is incomplete.** Values remain in the Port module and `OperationalReconcileResultV1` contract file is absent.

## 7. Mapping verdict

**PORTS / OUTBOUND ADAPTERS / CONNECTOR MAPPING COMPLETE @ `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`**

```text
BOUNDED CANONICAL ROWS             = 90
CANONICAL -> CURRENT               = 90 / 90 mapped
CURRENT -> CANONICAL               = CLOSED for inspected Port/connector/runtime scope
AMBIGUOUS DISPOSITION              = 0
EXACT STRUCTURAL PATHS             = 72 / 90

IMPLEMENTATION COMPLETE            = NO
SINGLE PRODUCTION AUTHORITY CLOSED = NO
CALLER CLOSURE                     = NO
FROZEN                             = NO
```