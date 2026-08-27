# Google Work Agent — Frontend Canonical ↔ Current Mapping

**Investigation SHA:** `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`  
**Current branch HEAD revalidated:** `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`  
**HEAD moved since this mapping snapshot:** **YES**  
**Current-head reconciliation:** No frontend production files changed in `6ec3ff49 → a03432c8`; the historical snapshot mapping remains current-head applicable.
**Mode:** `READ_ONLY_MAPPING`

## 1. Canonical universe

- `STR-007`: top-level Frontend production root = 1
- `STR-011..037`: exact P0 Frontend responsibility manifest = 27
- **Total = 28 rows**

Exact canonical structural target coverage: **1/28** (root only).  
Exact canonical responsibility-test paths under `frontend/tests/**`: **0/27**; current tests are primarily colocated under `frontend/src/**`.

## 2. Mapping

| ID | Canonical responsibility | Canonical target | Current implementation | Behavior | Structural | Disposition | Required action |
|---|---|---|---|---|---|---|---|
| STR-007 | frontend/ | `frontend/` | top-level `frontend/` exists | **FULL** | **FULL** | **KEEP** | Keep canonical root; refactor internals only. |
| STR-011 | FN-001 overall startup routing | `frontend/src/app/startup_flow.tsx` → `StartupFlow` | startup routing embedded in `frontend/src/app/App.tsx` | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-012 | UI-001 startup check | `frontend/src/features/diagnostics/startup_check.tsx` → `StartupCheckScreen` | startup checks/status embedded in `App.tsx` | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-013 | UI-002 first-run onboarding | `frontend/src/features/settings/first_run_onboarding.tsx` → `FirstRunOnboardingScreen` | `features/onboarding/OnboardingChecklist.tsx` + App startup flow | **NEAR_FULL** | **NONE** | **MOVE_RENAME + SPLIT** | Extract into exact canonical owner/file and preserve behavior. |
| STR-014 | FN-009 Local Session bootstrap | `frontend/src/app/session_bootstrap.ts` → `bootstrapLocalSession()` | bootstrapSession invocation and fragment cleanup embedded in `App.tsx` + root api | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-015 | FN-009 API compatibility gate | `frontend/src/app/api_compatibility_gate.tsx` → `ApiCompatibilityGate` | API compatibility/runtime readiness logic embedded in `App.tsx` + root api | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-016 | UI-003 main shell | `frontend/src/app/main_shell.tsx` → `MainShell` | main shell composition embedded in `App.tsx` | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-017 | UI-004 top bar shell composition | `frontend/src/app/top_bar.tsx` → `TopBar` | top-bar/status/settings/theme composition embedded in `App.tsx` | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-018 | FN-014 / UI-005 resource sidebar | `frontend/src/features/resource_browser/resource_sidebar.tsx` → `ResourceSidebar` | GmailPanel/TasksPanel/CalendarPanel + App resource-state composition | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-019 | UI-005 focused resource viewer | `frontend/src/features/resource_browser/resource_viewer.tsx` → `ResourceViewer` | `features/workspace/ResourceDetail.tsx` + App focus state | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-020 | FN-014 resource browse transport | `frontend/src/features/resource_browser/api/list_resources.ts` → `listResources()` | root `frontend/src/api/index.ts` + Gmail/Tasks/Calendar hooks | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-021 | FN-015 session page/batch/month cache | `frontend/src/features/resource_browser/session_page_cache.ts` → `ResourceBrowserSessionCache` | provider hooks (`useGmail/useTasks/useCalendar`) own page/batch/month session cache | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-022 | FN-016 explicit selected-resource context | `frontend/src/features/resource_browser/selected_resource_context.ts` → `buildSelectedResourceContext()` | App owns selected IDs/selection handles/labels and passes handles into useConversation | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-023 | UI-006 request composer / new Run submit | `frontend/src/features/run/request_composer.tsx` → `RequestComposer` | ConversationView composer + useConversation.handleStartRun | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-024 | FN-018 run event stream reconnect | `frontend/src/features/run/api/subscribe_run_events.ts` → `subscribeRunEvents()` | root `api/sse.ts` + useConversation event handling | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-025 | FN-018 progress/timeline projection | `frontend/src/features/run/run_progress.tsx` → `RunProgress` | ConversationView Run header/timeline/action status projection | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-026 | confirmation / clarification interaction | `frontend/src/features/run/confirmation_card.tsx` → `ConfirmationCard` | ConversationView WAITING_CONFIRMATION card and handleConfirmation | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-027 | execution / verification status projection | `frontend/src/features/run/execution_status_card.tsx` → `ExecutionStatusCard` | ConversationView Action status/verification presentation | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-028 | FN-078 / UI-007 conversation history | `frontend/src/features/conversation/conversation_history_panel.tsx` → `ConversationHistoryPanel` | `features/conversation/ConversationSidebar.tsx` + history in useConversation | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-029 | FN-078 history transport | `frontend/src/features/conversation/api/get_conversation_history.ts` → `getConversationHistory()` | root `frontend/src/api/index.ts` conversation-history call | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-030 | UI approval/plan card | `frontend/src/features/approval/action_plan_card.tsx` → `ActionPlanCard` | ConversationView Action Plan + approval controls | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-031 | UI recovery/error decision card | `frontend/src/features/recovery/recovery_card.tsx` → `RecoveryCard` | ConversationView recovery/failure actions | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-032 | UI-008 settings drawer | `frontend/src/features/settings/settings_drawer.tsx` → `SettingsDrawer` | `features/settings/SettingsDrawer.tsx` exact behavior under PascalCase filename | **NEAR_FULL** | **PATH+NAME** | **MOVE_RENAME** | Rename to canonical snake_case owner file; preserve component behavior. |
| STR-033 | FN-082 diagnostics projection | `frontend/src/features/diagnostics/diagnostics_panel.tsx` → `DiagnosticsPanel` | startup/runtime status diagnostics embedded in App; no diagnostics feature owner | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-034 | FN-021A attachment metadata/download UI | `frontend/src/features/attachment/attachment_list.tsx` → `AttachmentList` | attachment metadata/download embedded in App/ConversationView | **PARTIAL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-035 | FN-021A attachment download transport | `frontend/src/features/attachment/api/download_attachment.ts` → `downloadAttachment()` | root API exposes `downloadGmailAttachment`; no owner-local attachment API module | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-036 | FN-042A local attachment selection | `frontend/src/features/attachment/attachment_picker.tsx` → `AttachmentPicker` | file picker embedded in ConversationView | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |
| STR-037 | FN-042A attachment staging transport | `frontend/src/features/attachment/api/stage_attachment.ts` → `stageAttachment()` | root API/useConversation attachment staging flow; no owner-local API module | **NEAR_FULL** | **NONE** | **SPLIT + MOVE_RENAME** | Extract into exact canonical owner/file and preserve behavior. |

## 3. Current → Canonical reverse mapping

- `frontend/src/app/App.tsx` (~42 KB): startup check, session bootstrap, API compatibility/runtime fetch, onboarding, resource sidebar state/cache composition, selected-resource context, main shell/top-bar concerns are mixed. **SPLIT; do not rewrite wholesale.**
- `frontend/src/features/conversation/ConversationView.tsx` (~23 KB): composer, Run status, Confirmation, Action Plan, approval, execution/verification, recovery and attachment picker are mixed. **SPLIT into run/approval/recovery/attachment owners.**
- provider feature owners `gmail/`, `tasks/`, `calendar/`: useful provider-specific rendering/hooks, but shared browse/cache/selection semantics map to `resource_browser`.
- `features/workspace/`: resource viewer/center composition is a historical bucket; split to app shell + resource_browser.
- root `frontend/src/api/`: transport functions are broad/global; move capability API calls under owner-local `features/<owner>/api/`.
- `features/onboarding/`: current OnboardingChecklist behavior maps to canonical settings.first_run_onboarding, not a new semantic owner.
- PascalCase production filenames/components violate current snake_case repository grammar even where behavior is reusable.

## 4. Verdict

**FRONTEND MAPPING COMPLETE @ `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`**

```text
CANONICAL ROWS                    = 28
CANONICAL -> CURRENT              = 28 / 28 mapped
CURRENT -> CANONICAL              = CLOSED for inspected frontend production scope
AMBIGUOUS DISPOSITION             = 0
EXACT STRUCTURAL TARGETS          = 1 / 28
EXACT CANONICAL TEST OWNERS       = 0 / 27

IMPLEMENTATION COMPLETE           = NO
FRONTEND OWNER CLOSURE            = NO
FROZEN                            = NO
```