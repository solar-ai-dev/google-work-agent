# 02. Directory Ownership

**Normative detail of the current Repository Architecture Source.**

Canonical owners are semantic, not historical implementation buckets.

Top-level repository ownership currently closed by this Source:

```
domain/
application/
ports/
adapters/
api/
launcher/
frontend/
installer/
release/
evaluation/
```

`evaluation/` is the **single current top-level root** for all 13-owned experiment/evaluation code and non-Python artifacts. A top-level `experiments/` root and live `evaluation/compat/` tree are not current repository authority; historical inputs remain in Git history. `evaluation/` is a Product-external consumer: Product runtime may not import it, and Evaluation may invoke Product only through a supported public API/CLI/subprocess boundary, never by importing Product Python internals. React/TypeScript Frontend production root is `frontend/` and follows the same closed-world ownership rule. `installer/` and `release/` are release-source/tooling roots and are never imported by product runtime modules. UI behavior remains owned by 02 and installer/runtime semantics by 10; this page only owns deterministic placement/naming.

Domain/Application semantic owner packages are singular. Agent semantic owners are exactly `request_understanding`, `tool_routing`, `retrieval`, `work_analysis`, `planning`, `review`.

Domain transitions/guards are operation-per-file. Final production uses `domain/<owner>/transitions/<verb>_<object>.py` and `domain/<owner>/guards/<verb>_<object>.py`; broad `commands.py`, `transitions.py`, `guards.py`, or equivalent multi-capability buckets are prohibited. Domain model types that share one cohesive invariant set may remain in `domain/<owner>/model.py`.

API resource route collections are plural. Provider resource packages may use Provider-native plural nouns.

Connector MCP Server process-side responsibilities are production code under `adapters/connectors/<provider>/<connector_package>/mcp_server/`. The allowed architecture-role entry/composition files are `entrypoint.py` and `composition.py`; `dispatch_tool.py`, `project_registry.py`, `validate_claim_context.py`, and `credential_provider.py` remain separate single-responsibility files. A broad `mcp/server.py`, `connector_service.py`, or generic service bucket is not a canonical owner.

Agent semantic implementation is operation-per-file under `application/agents/<role>/<verb>_<object>.py`. Owner-local contract types live under `application/agents/<role>/contracts/<artifact_name>.py`; a global catch-all production `contracts/` package is prohibited.

LangGraph routing is operation-per-file under `routing/route_after_<stage>.py`; a catch-all `routing.py` is not final production structure. Input projections live under owner-local `projections/<scope>_projection.py`.


API security/launcher special files are closed as follows:

```text
api/security/bootstrap_session.py      # bootstrap secret consumption + Local Session establishment only
api/dependencies/local_session.py      # established Local Session validation only
launcher/bootstrap_secret.py           # one-time bootstrap secret generation/lifetime only
launcher/readiness.py                  # liveness/readiness projection only
```

These are not generic service buckets and may not absorb business Application use cases.

Process-live handoff reconciliation uses one explicit driving adapter:

```text
adapters/system/workflow_handoff_reconciliation_loop.py  # wake/timer lifecycle only; drives RedriveWorkflowHandoffsHandler
```

This file owns no Repository query, Domain transition, resume-target decision, `WorkflowExecutionPort` call, or LangGraph invocation. Those semantics remain in the injected Application handler. It is not a second scheduler/execution authority and must not become a generic runtime manager.

## Application structural closure

Final Application ownership is semantic-owner based.

- `application/use_cases/<owner>/` owns command/query orchestration for the canonical Application capability.
- deterministic Policy/Schema validation that gates an Action remains owner-local under `application/use_cases/action/`; do not create global `policy/`, `validators/`, or `common/` production authority buckets. Agent artifact semantic validators remain under their Agent owner.
- `application/agents/<role>/` owns Agent semantic operations only.
- `application/` root does not own broad semantic services, read/write facades, workflow runtimes, or migrated concrete authority.
- Final `application/` root production-file expectation is `__init__.py` only, except an architecture-role file explicitly allowed by the Exception Registry.
- `application/workflows/**` is not a final canonical semantic owner. Once its responsibilities are mapped and callers are cut over, the production tree must be absent.

Agent semantic operations are **operation-per-file as a required responsibility boundary**, not merely a naming preference. Every atomic responsibility identified by the current Workflow/Prompt authority maps to one owner-local production operation file unless the owning semantic contract explicitly classifies it as deterministic composition.

Cross-Agent Prompt runtime infrastructure is a structural package, not a seventh semantic Agent owner:

```text
application/prompt_runtime/prompt_registry.py
application/prompt_runtime/assemble_prompt.py
application/prompt_runtime/contracts/prompt_runtime_input_contract.py
application/prompt_runtime/load_prompt_input_contract.py
application/prompt_runtime/prompt_manifest.json
application/prompt_runtime/prompt_runtime_input_contract_v1.json
application/prompt_runtime/sources/<prompt_id>.md
```

Tool Registry structural package is likewise closed and is not an Application semantic owner:

```text
application/tool_registry/signed_tool_registry.py
application/tool_registry/load_signed_tool_registry.py
application/tool_registry/tool_registry_manifest.json
application/tool_registry/contracts/signed_tool_registry_entry.py
```

The validated output passed across the Connector Port boundary is owned separately by the Port layer:

```text
ports/connector/contracts/validated_connector_tool_binding.py
```

`ValidatedConnectorToolBindingV1` is a Port-boundary shared contract consumed by Application and outbound Connector adapters; it is not an Application semantic owner or an Adapter-owned type.


`application/prompt_runtime/` may select/assemble only 15-owned PromptRef/manifest/source artifacts. It may not own Agent semantics, Tool selection, Policy, Domain transitions, or LLM provider selection. `application/tool_registry/`, `application/prompt_runtime/`, and narrow `application/maintenance/` are explicit structural packages and are **not** members of the Application semantic owner closed set. `application/maintenance/` currently contains only `purge_retention.py`; it may not become a generic scheduler/service bucket.

FastAPI Service의 single production entry/composition pair는:

```text
api/app.py         → create_app()
api/composition.py → build_production_runtime()
```

`create_app()`는 Service startup에서 `build_production_runtime()`을 정확히 한 번 호출해 FastAPI dependency providers/routes에 이미 구성된 abstract-boundary dependencies를 주입한다. FastAPI lifespan wiring은 **10의 canonical startup order를 그대로 소비**한다: SQLite/migration/checkpoint readiness → Connector MCP child/Tool-Schema readiness → configured LLM Adapter/Router load → injected `ReconcileInflightExecutionsHandler` bounded startup drain → injected `RedriveWorkflowHandoffsHandler` bounded initial drain → injected `WorkflowHandoffReconciliationLoop` start → READY. live loop는 `ReconcileInflightExecutionsHandler`를 호출하지 않는다. shutdown에서는 loop를 먼저 stop/drain한 뒤 10의 shutdown ordering을 따른다. Handler/loop invocation은 app lifecycle wiring일 뿐 repository/WEP/LangGraph concrete binding authority가 아니다. `api/composition.py`만 concrete adapters를 dependency wiring 목적으로 import할 수 있다. `api/routes/**`, `api/dependencies/**`는 concrete adapters를 import하지 않는다. No second Service composition root may exist in `application/`, `adapters/`, `launcher/`, or FastAPI route/startup helper modules.

## Frontend production grammar

```text
frontend/src/app/                                  # router/shell/startup-flow/session-bootstrap composition only
frontend/src/features/<owner>/<responsibility>.tsx
frontend/src/features/<owner>/<verb>_<object>.ts
frontend/src/features/<owner>/contracts/<artifact>.ts
frontend/src/features/<owner>/api/<verb>_<object>.ts
frontend/src/ui/<presentation_component>.tsx       # presentation-only primitive
frontend/tests/app/<responsibility>.test.ts(x)
frontend/tests/features/<owner>/<responsibility>.test.ts(x)
frontend/tests/features/<owner>/api/<verb>_<object>.test.ts
frontend/tests/architecture/
```

Canonical P0 Frontend feature owners: `conversation`, `resource_browser`, `run`, `approval`, `recovery`, `settings`, `diagnostics`, `attachment`. `frontend/src/ui/`는 presentation primitive만 둔다. `shared/common/utils/service/manager` production owner package를 만들지 않는다. API module은 `/api/v1` transport/projection만 소유한다.


### Frontend exact responsibility manifest

02 owns UI behavior; this table owns only **exact repository realization**. The following P0 responsibility modules are canonical and closed. A Coding Agent may keep tiny private JSX helpers colocated in the owning `.tsx` file or use presentation-only primitives under `frontend/src/ui/`, but may not create a new feature owner or competing responsibility module for these capabilities.

| UI / Functional surface | Canonical owner | Exact production file | Primary symbol | Canonical test owner |
| --- | --- | --- | --- | --- |
| FN-001 overall startup routing | app composition | `frontend/src/app/startup_flow.tsx` | `StartupFlow` | `frontend/tests/app/startup_flow.test.tsx` |
| UI-001 startup check | `diagnostics` | `frontend/src/features/diagnostics/startup_check.tsx` | `StartupCheckScreen` | `frontend/tests/features/diagnostics/startup_check.test.tsx` |
| UI-002 first-run onboarding | `settings` | `frontend/src/features/settings/first_run_onboarding.tsx` | `FirstRunOnboardingScreen` | `frontend/tests/features/settings/first_run_onboarding.test.tsx` |
| FN-009 Local Session bootstrap | app composition | `frontend/src/app/session_bootstrap.ts` | `bootstrapLocalSession()` | `frontend/tests/app/session_bootstrap.test.ts` |
| FN-009 API compatibility gate | app composition | `frontend/src/app/api_compatibility_gate.tsx` | `ApiCompatibilityGate` | `frontend/tests/app/api_compatibility_gate.test.tsx` |
| UI-003 main shell | app composition | `frontend/src/app/main_shell.tsx` | `MainShell` | `frontend/tests/app/main_shell.test.tsx` |
| UI-004 top bar shell composition | app composition | `frontend/src/app/top_bar.tsx` | `TopBar` | `frontend/tests/app/top_bar.test.tsx` |
| FN-014 / UI-005 resource sidebar | `resource_browser` | `frontend/src/features/resource_browser/resource_sidebar.tsx` | `ResourceSidebar` | `frontend/tests/features/resource_browser/resource_sidebar.test.tsx` |
| UI-005 focused resource viewer | `resource_browser` | `frontend/src/features/resource_browser/resource_viewer.tsx` | `ResourceViewer` | `frontend/tests/features/resource_browser/resource_viewer.test.tsx` |
| FN-014 resource browse transport | `resource_browser` | `frontend/src/features/resource_browser/api/list_resources.ts` | `listResources()` | `frontend/tests/features/resource_browser/api/list_resources.test.ts` |
| FN-015 session page/batch/month cache | `resource_browser` | `frontend/src/features/resource_browser/session_page_cache.ts` | `ResourceBrowserSessionCache` | `frontend/tests/features/resource_browser/session_page_cache.test.ts` |
| FN-016 explicit selected-resource context | `resource_browser` | `frontend/src/features/resource_browser/selected_resource_context.ts` | `buildSelectedResourceContext()` | `frontend/tests/features/resource_browser/selected_resource_context.test.ts` |
| UI-006 request composer / new Run submit | `run` | `frontend/src/features/run/request_composer.tsx` | `RequestComposer` | `frontend/tests/features/run/request_composer.test.tsx` |
| FN-018 run event stream reconnect | `run` | `frontend/src/features/run/api/subscribe_run_events.ts` | `subscribeRunEvents()` | `frontend/tests/features/run/api/subscribe_run_events.test.ts` |
| FN-018 progress/timeline projection | `run` | `frontend/src/features/run/run_progress.tsx` | `RunProgress` | `frontend/tests/features/run/run_progress.test.tsx` |
| confirmation / clarification interaction | `run` | `frontend/src/features/run/confirmation_card.tsx` | `ConfirmationCard` | `frontend/tests/features/run/confirmation_card.test.tsx` |
| execution / verification status projection | `run` | `frontend/src/features/run/execution_status_card.tsx` | `ExecutionStatusCard` | `frontend/tests/features/run/execution_status_card.test.tsx` |
| FN-078 / UI-007 conversation history | `conversation` | `frontend/src/features/conversation/conversation_history_panel.tsx` | `ConversationHistoryPanel` | `frontend/tests/features/conversation/conversation_history_panel.test.tsx` |
| FN-078 history transport | `conversation` | `frontend/src/features/conversation/api/get_conversation_history.ts` | `getConversationHistory()` | `frontend/tests/features/conversation/api/get_conversation_history.test.ts` |
| UI approval/plan card | `approval` | `frontend/src/features/approval/action_plan_card.tsx` | `ActionPlanCard` | `frontend/tests/features/approval/action_plan_card.test.tsx` |
| UI recovery/error decision card | `recovery` | `frontend/src/features/recovery/recovery_card.tsx` | `RecoveryCard` | `frontend/tests/features/recovery/recovery_card.test.tsx` |
| UI-008 settings drawer | `settings` | `frontend/src/features/settings/settings_drawer.tsx` | `SettingsDrawer` | `frontend/tests/features/settings/settings_drawer.test.tsx` |
| FN-082 diagnostics projection | `diagnostics` | `frontend/src/features/diagnostics/diagnostics_panel.tsx` | `DiagnosticsPanel` | `frontend/tests/features/diagnostics/diagnostics_panel.test.tsx` |
| FN-021A attachment metadata/download UI | `attachment` | `frontend/src/features/attachment/attachment_list.tsx` | `AttachmentList` | `frontend/tests/features/attachment/attachment_list.test.tsx` |
| FN-021A attachment download transport | `attachment` | `frontend/src/features/attachment/api/download_attachment.ts` | `downloadAttachment()` | `frontend/tests/features/attachment/api/download_attachment.test.ts` |
| FN-042A local attachment selection | `attachment` | `frontend/src/features/attachment/attachment_picker.tsx` | `AttachmentPicker` | `frontend/tests/features/attachment/attachment_picker.test.tsx` |
| FN-042A attachment staging transport | `attachment` | `frontend/src/features/attachment/api/stage_attachment.ts` | `stageAttachment()` | `frontend/tests/features/attachment/api/stage_attachment.test.ts` |

Frontend naming is deterministic: feature component filename is snake_case and exports one PascalCase primary component; non-visual operation/API files export one lowerCamelCase operation matching the file responsibility. The table above is the owner-selection authority for the listed P0 surfaces: for example UI-001 is not free to move between `settings`, `diagnostics`, or a new `onboarding` package. `frontend/src/app/**` owns only shell/startup/session composition and never business/domain semantics.

### Launcher · Installer · Release exact manifest

10 owns process/packaging/signing semantics. This manifest owns the exact repository placement so those requirements do not create ad-hoc roots. `launcher/` is runtime launcher code; `installer/` is declarative Windows installer/uninstaller source; `release/` is release-time assembly/signing tooling. Product runtime code must not import `installer/**` or `release/**`.

#### Launcher runtime

| Responsibility | Exact production file | Primary symbol | Canonical test owner |
| --- | --- | --- | --- |
| launcher executable orchestration | `launcher/entrypoint.py` | `main()` | `tests/unit/launcher/test_entrypoint.py` |
| explicit non-installed development Product orchestration | `launcher/development_entrypoint.py` | `main()` | `tests/integration/launcher/test_development_entrypoint.py` |
| single-instance lock / existing-instance detection | `launcher/acquire_single_instance.py` | `acquire_single_instance()` | `tests/unit/launcher/test_acquire_single_instance.py` |
| installed Release Manifest/signature/hash verification | `launcher/verify_installation.py` | `verify_installation()` | `tests/unit/launcher/test_verify_installation.py` |
| verified Signed Build Config projection from the already-verified Release Manifest | `launcher/release_build_config.py` | `SignedBuildConfigV1`, `load_signed_build_config()` | `tests/unit/launcher/test_release_build_config.py` |
| user data-directory creation + ACL initialization | `launcher/prepare_data_directory.py` | `prepare_data_directory()` | `tests/unit/launcher/test_prepare_data_directory.py` |
| loopback dynamic-port allocation | `launcher/allocate_dynamic_port.py` | `allocate_dynamic_port()` | `tests/unit/launcher/test_allocate_dynamic_port.py` |
| one-time bootstrap secret | `launcher/bootstrap_secret.py` | `create_bootstrap_secret()` | `tests/unit/launcher/test_bootstrap_secret.py` |
| service-instance identity | `launcher/create_service_instance_id.py` | `create_service_instance_id()` | `tests/unit/launcher/test_create_service_instance_id.py` |
| FastAPI child process start | `launcher/start_service.py` | `start_service()` | `tests/unit/launcher/test_start_service.py` |
| service liveness/readiness wait/projection | `launcher/readiness.py` | `wait_for_service_ready()` | `tests/unit/launcher/test_readiness.py` |
| existing Launcher instance-control listener over current-user Named Pipe | `launcher/serve_instance_control.py` | `serve_instance_control()` | `tests/unit/launcher/test_serve_instance_control.py` |
| existing Launcher second-launch UI request over current-user Named Pipe | `launcher/request_existing_instance_ui.py` | `request_existing_instance_ui()` | `tests/unit/launcher/test_request_existing_instance_ui.py` |
| browser open through the existing `BrowserLauncherPort` boundary | `launcher/open_product_ui.py` | `open_product_ui()` | `tests/unit/launcher/test_open_product_ui.py` |
| coordinated service shutdown | `launcher/shutdown_service.py` | `shutdown_service()` | `tests/unit/launcher/test_shutdown_service.py` |

Launcher operation files may contain OS-specific private helpers, but another public `manager/service/runtime/common` owner or second launcher composition root is prohibited. `launcher/entrypoint.py` is thin installed orchestration over the exact operation set above and must not import Domain/Application business owners. `launcher/development_entrypoint.py`는 `ProductionRuntimeConfig.development → api.app.create_app`만 호출하는 non-installed orchestration이며 business Handler/Registry를 직접 구성할 수 없다. Browser/secret-storage 같은 launcher-owned system boundary 입력만 허용한다.

#### Windows installer / package / signing source

| Responsibility | Exact source file | Primary symbol/artifact | Canonical test owner |
| --- | --- | --- | --- |
| Windows installer definition | `installer/windows/installer_definition.py` | `WindowsInstallerDefinition` | `tests/installer/windows/test_installer_definition.py` |
| LOCAL_CAPABLE Ollama/model provisioning definition | `installer/windows/local_runtime_provisioning_definition.py` | `WindowsLocalRuntimeProvisioningDefinition` | `tests/installer/windows/test_local_runtime_provisioning_definition.py` |
| Windows uninstall/data-preservation definition | `installer/windows/uninstall_definition.py` | `WindowsUninstallDefinition` | `tests/installer/windows/test_uninstall_definition.py` |
| in-place upgrade/downgrade-block definition | `installer/windows/upgrade_policy.py` | `WindowsUpgradePolicy` | `tests/installer/windows/test_upgrade_policy.py` |
| `API_ONLY` artifact profile | `release/profiles/api_only.py` | `build_api_only_profile()` | `tests/release/profiles/test_api_only.py` |
| `LOCAL_CAPABLE` artifact profile | `release/profiles/local_capable.py` | `build_local_capable_profile()` | `tests/release/profiles/test_local_capable.py` |
| One-folder Application Bundle assembly | `release/assemble_application_bundle.py` | `assemble_application_bundle()` | `tests/release/test_assemble_application_bundle.py` |
| Windows Installer build | `release/build_windows_installer.py` | `build_windows_installer()` | `tests/release/test_build_windows_installer.py` |
| signed Release Manifest generation | `release/generate_release_manifest.py` | `ReleaseManifestFileV1`, `ReleaseManifestV1`, `generate_release_manifest()` | `tests/release/test_generate_release_manifest.py` |
| `LOCAL_CAPABLE` model allowlist schema/parser | `src/google_work_agent/ports/llm/approved_model_manifest.py` | `ApprovedModelEntryV2`, `ModelManifestV2` | `tests/release/test_generate_model_manifest.py` |
| `LOCAL_CAPABLE` model allowlist manifest generation | `release/generate_model_manifest.py` | `generate_model_manifest()` | `tests/release/test_generate_model_manifest.py` |
| `LOCAL_CAPABLE` model profile decision schema/parser | `src/google_work_agent/ports/llm/local_model_product_decision.py` | `LocalModelTierBindingV1`, `LocalModelProfileV1`, `LocalModelProductDecisionV2` | `tests/release/test_generate_local_model_product_decision.py` |
| `LOCAL_CAPABLE` model profile decision materialization | `release/generate_local_model_product_decision.py` | `generate_local_model_product_decision()` | `tests/release/test_generate_local_model_product_decision.py` |
| Code Signing + Timestamp application | `release/sign_release_artifacts.py` | `sign_release_artifacts()` | `tests/release/test_sign_release_artifacts.py` |

The specific installer backend invocation, subprocess arguments, temporary staging data structure, and batching are private implementation choices **inside these canonical release operations**. They do not justify `packaging/`, `build/`, `scripts/release/`, `installer_service.py`, or a second manifest/signing authority. Release signing order and required signed artifact set remain owned by 10/09; 16 only fixes where the implementation lives.

Signed Prompt bundle의 installed path authority는 `%INSTALL_ROOT%/manifests/prompt/` 하나다. `release/assemble_application_bundle.py`는 CLI가 선택한 `prompt_manifest.json`과 sibling input contract, exact 21 source, referenced activation evidence를 기존 `PromptRegistry`로 검증한 뒤 이 경로에 materialize한다. `release/generate_release_manifest.py`는 materialized bundle을 같은 Registry로 다시 검증하고 모든 파일을 Release Manifest hash chain에 포함한다. `api/composition.py`의 `SIGNED_RELEASE_MANIFEST` composition은 이 verified installed manifest만 선택하며 service distribution 내부 package 기본 Prompt로 fallback하지 않는다. Package 기본 Prompt는 `EXPLICIT_DEVELOPMENT`의 `DEVELOPMENT_SMOKE`에만 사용한다.

#### Signed Build Config repository closure

10의 `release-manifest.json + .sig`가 유일한 installed Signed Build Config artifact다. 별도 production `build-config.json`/`config.json`/unsigned environment authority를 만들지 않는다.

```text
release/generate_release_manifest.py → ReleaseManifestV1 / generate_release_manifest()
    owns closed raw manifest schema + materialization of 10-owned signed build fields into release-manifest.json

launcher/verify_installation.py → verify_installation()
    owns signature + referenced-file hash verification

launcher/release_build_config.py → SignedBuildConfigV1 / load_signed_build_config()
    owns typed projection from an already-verified manifest only

launcher/start_service.py → start_service()
    consumes SignedBuildConfigV1 for service startup composition

api/composition.py
    consumes only the verified startup projection supplied by Launcher; ambient env/Settings do not redefine signed-locked fields

Connector MCP child environment
    GOOGLE_OAUTH_ENV + GOOGLE_OAUTH_CLIENT_ID are injected from SignedBuildConfigV1, not read as ambient Production config
```

`model-manifest-v2.json` is the separate runtime/model allowlist artifact represented and parsed only by `src/google_work_agent/ports/llm/approved_model_manifest.py::ModelManifestV2`; `release/generate_model_manifest.py → generate_model_manifest()` materializes it without redefining the schema. It owns the approved Ollama installer artifact identity/hash plus `approved_models(model_id, model_digest, parameter_class, download_size_bytes)`.

`local-model-product-decision-v2.json` is represented and parsed only by `src/google_work_agent/ports/llm/local_model_product_decision.py::LocalModelProductDecisionV2`; `release/generate_local_model_product_decision.py → generate_local_model_product_decision()` materializes exactly one active `LocalModelProfileV1(WORKER|REASONING tier bindings)` plus evaluated hardware/platform thresholds and binds it to the canonical Model Manifest hash/current release version. `SignedBuildConfigV1`, `SettingsViewV1`, Prompt sources and Agent code do not duplicate those fields. `LOCAL_CAPABLE` requires both V2 artifacts and the provisioning definition; `API_ONLY` forbids all Local Runtime/model effects. Tests are `tests/release/test_generate_release_manifest.py`, `tests/release/test_generate_model_manifest.py`, `tests/release/test_generate_local_model_product_decision.py`, `tests/installer/windows/test_local_runtime_provisioning_definition.py`, `tests/unit/launcher/test_verify_installation.py`, `tests/unit/launcher/test_release_build_config.py`, and the installed-like production-composition Local runtime tests.

V1 files/types remain implementation migration inputs only until V2 cut-over; final Release profile assembly contains one schema generation, never a mixed V1/V2 authority set.

