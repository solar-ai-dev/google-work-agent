# Google Work Agent — API / Composition Canonical ↔ Current Mapping

**Investigation SHA:** `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`  
**Current branch HEAD revalidated:** `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`  
**HEAD moved since this mapping snapshot:** **YES**  
**Current-head reconciliation:** API/composition was not the main #104 cut-over surface; only narrow API files changed after `93f03a91`. The formal `STR-455` row remains owned by Launcher and API retains only a consumer-side cross-reference. Broad concrete development composition is still visible in `launcher/dev.py`, so global single-root closure remains OPEN.
**Mode:** `READ_ONLY_MAPPING`

## 1. Canonical universe

- Repository root: `STR-005` = 1
- Composition roots: `STR-325..326` = 2
- Local API / security transport formally owned here: `STR-438..454,456..457` = 19
- `STR-455` is a **cross-layer reference only** here; its one formal row is owned by Launcher because the canonical producer target is `launcher/bootstrap_secret.py`.
- **Total formal API rows = 22**

Exact complete canonical target paths at the frozen SHA: **13 / 22**.

## 2. Canonical → Current mapping

| ID | Canonical responsibility | Canonical target | Current implementation | Behavior | Structural | Disposition | Required action |
|---|---|---|---|---|---|---|---|
| STR-005 | API repository root / FastAPI transport ownership | `api/` | `src/google_work_agent/api/` exists at snapshot/current HEAD. | **N/A** | **FULL_ROOT** | **KEEP** | Preserve API root and keep business semantics in Application/Domain; concrete composition converges on `api/composition.py`. |
| STR-325 | FastAPI app construction | `api/app.py` → `create_app()` | `api/app.py → create_app(container)` exact; route/middleware assembly is substantial | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Preserve FastAPI assembly, but make create_app consume the single production runtime composition instead of requiring a preassembled broad ApiContainer. |
| STR-326 | production runtime wiring | `api/composition.py` → `build_production_runtime()` | `api/composition.py → build_production_runtime()` exact; currently builds checkpoint/background handoff slice only | **PARTIAL** | **FULL** | **KEEP + EXPAND CANONICAL COMPOSITION** | Preserve 24-pair binding knowledge and handoff composition; make this the actual single concrete wiring root for connector/LLM/system/profile/handlers. |
| STR-438 | GET /api/v1/conversations | `api/routes/conversations.py + api/schemas/conversations/list_conversations.py` | `api/routes/conversations.py` + exact conversation schema file present | **NEAR_FULL** | **FULL** | **KEEP + CALLER NORMALIZATION** | Preserve transport behavior; ensure routes depend only on canonical conversation handlers and no broad service aliases. |
| STR-439 | POST /api/v1/conversations | `api/routes/conversations.py + api/schemas/conversations/create_conversation.py` | `api/routes/conversations.py` + exact conversation schema file present | **NEAR_FULL** | **FULL** | **KEEP + CALLER NORMALIZATION** | Preserve transport behavior; ensure routes depend only on canonical conversation handlers and no broad service aliases. |
| STR-440 | GET /api/v1/conversations/{conversation_id}/history | `api/routes/conversations.py + api/schemas/conversations/get_conversation_history.py` | `api/routes/conversations.py` + exact conversation schema file present | **NEAR_FULL** | **FULL** | **KEEP + CALLER NORMALIZATION** | Preserve transport behavior; ensure routes depend only on canonical conversation handlers and no broad service aliases. |
| STR-441 | POST /api/v1/runs | `api/routes/runs.py + api/schemas/runs/start_run.py` | `api/routes/runs.py` + `schemas/runs/start_run.py` exact; route calls StartRunHandler | **NEAR_FULL** | **FULL** | **KEEP + CALLER NORMALIZATION** | Preserve server-owned ID/selection-handle handling; final dependency wiring comes from canonical composition. |
| STR-442 | GET /api/v1/runs/{run_id} | `api/routes/runs.py + api/schemas/runs/get_run_snapshot.py` | route exact; current schema is `schemas/runs/get_run.py`, not canonical `get_run_snapshot.py` | **NEAR_FULL** | **PATH** | **MOVE_RENAME** | Rename/move response schema to canonical get_run_snapshot.py and keep GetRunSnapshotHandler caller. |
| STR-443 | POST /api/v1/runs/{run_id}/context-adjustments | `api/routes/runs.py + api/schemas/runs/adjust_context.py` | canonical context-adjustment endpoint/schema absent; current GET `/runs/{id}/context` is a different capability | **NONE/PARTIAL_REUSE** | **NONE** | **CREATE + MERGE** | Create exact context-adjustment transport using existing confirmation/retrieval/context machinery; call canonical run.adjust_context only. |
| STR-444 | POST /api/v1/runs/{run_id}/confirm | `api/routes/runs.py + api/schemas/runs/confirm_run.py` | exact run route + confirm_run schema; route invokes ConfirmRunHandler | **NEAR_FULL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Keep transport/controller shape; semantic completion depends on corrected confirmation resume path. |
| STR-445 | POST /api/v1/runs/{run_id}/cancel | `api/routes/runs.py + api/schemas/runs/cancel_run.py` | exact run route + cancel_run schema; RequestCancelHandler used | **NEAR_FULL** | **FULL** | **KEEP + CALLER NORMALIZATION** | Keep; remove legacy coordinator/service seams after canonical cancellation caller cut-over. |
| STR-446 | POST /api/v1/runs/{run_id}/resume | `api/routes/runs.py + api/schemas/runs/resume_run.py` | exact run route + resume_run schema; current ResumeRunHandler is a broad compatibility Application owner | **PARTIAL** | **FULL** | **KEEP TRANSPORT + REWIRE** | Preserve wire discriminant and validation; rewire to canonical resume_safe_checkpoint/reauth/recovery authorities. |
| STR-447 | POST /api/v1/runs/{run_id}/resolve-recovery | `api/routes/runs.py + api/schemas/runs/resolve_recovery.py` | exact run route + resolve_recovery schema; calls canonical ResolveRecoveryHandler | **PARTIAL** | **FULL** | **KEEP + TARGETED_CORRECTION** | Keep transport; semantic completion follows Recovery mapping corrections and handoff target closure. |
| STR-448 | GET /api/v1/runs/{run_id}/events | `api/routes/runs.py + api/schemas/runs/list_run_events.py` | current SSE transport lives under `api/routes/events.py` + `api/schemas/events/get_events.py` | **NEAR_FULL** | **PATH** | **MOVE_RENAME + MERGE** | Move/rename run-event transport to canonical runs/list_run_events ownership while preserving cursor/replay semantics. |
| STR-449 | POST /api/v1/actions/{action_id}/approve | `api/routes/actions.py + api/schemas/actions/approve_action.py` | `api/routes/actions.py` + exact action schema file present | **PARTIAL** | **FULL** | **KEEP + REWIRE** | Preserve Local API validation/idempotency; cut route dependencies to canonical action Application handlers only. |
| STR-450 | POST /api/v1/actions/{action_id}/modify | `api/routes/actions.py + api/schemas/actions/modify_action.py` | `api/routes/actions.py` + exact action schema file present | **PARTIAL** | **FULL** | **KEEP + REWIRE** | Preserve Local API validation/idempotency; cut route dependencies to canonical action Application handlers only. |
| STR-451 | POST /api/v1/actions/{action_id}/reject | `api/routes/actions.py + api/schemas/actions/reject_action.py` | `api/routes/actions.py` + exact action schema file present | **PARTIAL** | **FULL** | **KEEP + REWIRE** | Preserve Local API validation/idempotency; cut route dependencies to canonical action Application handlers only. |
| STR-452 | POST /api/v1/actions/{action_id}/prepare-retry | `api/routes/actions.py + api/schemas/actions/prepare_retry.py` | actions route exists; schema is `prepare_retry_action.py`, not canonical `prepare_retry.py` | **PARTIAL** | **PATH** | **MOVE_RENAME + REWIRE** | Rename schema and point route at canonical action.prepare_write_retry handler. |
| STR-453 | GET /health/live + GET /health/ready | `api/routes/health.py + launcher/readiness.py` | current route is `api/routes/health_checks.py`; canonical `health.py` absent; launcher/readiness.py absent | **PARTIAL** | **NONE** | **MOVE_RENAME + CREATE** | Move existing health route behavior to health.py; materialize canonical launcher readiness projection separately. |
| STR-454 | POST /api/v1/session/bootstrap | `api/routes/session.py + api/security/bootstrap_session.py` | current route `api/routes/sessions.py`; bootstrap establishment in `api/security/bootstrap.py`; canonical names absent | **NEAR_FULL** | **NONE** | **MOVE_RENAME + SPLIT** | Preserve bootstrap grant/session semantics; move establishment-only authority to api/security/bootstrap_session.py and canonical session route. |
| STR-456 | Protected Local Session validation | `api/dependencies/local_session.py` | canonical `api/dependencies/local_session.py` absent; established-session validation spread through access_control/security session helpers | **PARTIAL** | **NONE** | **SPLIT + MOVE** | Extract established Local Session validation to canonical dependency; keep bootstrap establishment separate. |
| STR-457 | Recovery shared wire identity | `api/schemas/runs/recovery.py` → `RecoveryResolutionKindV1 / RunRecoveryTargetV1 / ActionRecoveryTargetV1 / RecoveryTargetV1 / RecoveryUiProjectionV1` | canonical `schemas/runs/recovery.py` absent; recovery identity duplicated across resume/resolve response/request schemas | **PARTIAL** | **NONE** | **MERGE + MOVE** | Create one shared recovery wire identity by merging existing discriminants/fields; other schemas reference it. |


### STR-455 cross-layer reference (not a second formal row)

`STR-455` is formally mapped once in `launcher-installer-release-canonical-current-mapping-6ec3ff49.md`. API owns bootstrap-session **consumption/establishment** (`STR-454`), while Launcher owns Bootstrap Secret **production** (`STR-044`/`STR-455`). Current API bootstrap/security code is reusable consumer-side material only and must not become a second secret producer.

## 3. Current → Canonical reverse mapping

| Current authority | Finding | Disposition |
|---|---|---|
| `api/container.py → ApiContainer` | Broad dependency bag assembled outside canonical composition; it imports LangGraph registries and owns construction defaults such as ResumeTargetRegistry and selection-handle services. | **SPLIT/MERGE into api/composition + narrow API dependency providers; delete as second composition authority after cut-over** |
| `api/lifespan.py` | Current lifecycle helper is useful, but startup ordering must consume injected canonical handlers/runtime from composition. | **KEEP + TARGETED REWIRE** |
| `api/routes/health_checks.py` / `sessions.py` | Noncanonical route naming for canonical health/session resources. | **MOVE_RENAME** |
| `api/security/bootstrap.py` | Mixes bootstrap establishment semantics under a noncanonical file; reusable. | **MOVE_RENAME/SPLIT → bootstrap_session.py** |
| `api/routes/events.py` + `api/schemas/events/get_events.py` | Run SSE transport lives under separate event resource instead of canonical run-event transport mapping. | **MOVE_RENAME/MERGE** |
| `api/schemas/runs/get_run.py` | Same snapshot wire family under old name. | **MOVE_RENAME** |
| `api/schemas/actions/prepare_retry_action.py` | Same action retry wire under old name. | **MOVE_RENAME** |

## 4. High-risk findings

1. `create_app()` does not call/consume `build_production_runtime()` as the canonical single composition boundary; it accepts a preassembled `ApiContainer`.
2. `build_production_runtime()` currently composes only the durable workflow-handoff slice despite containing the 24 concrete binding table.
3. `ApiContainer` is effectively a second broad composition/dependency authority and even constructs ResumeTargetRegistry/selection-handle services in `__post_init__`.
4. Context Adjustment transport is absent.
5. Several wire responsibilities are behaviorally present under noncanonical names (`get_run`, `events/get_events`, `prepare_retry_action`, `health_checks`, `sessions`, `bootstrap`).
6. Protected Local Session validation and shared Recovery wire identity are not realized at the canonical owner paths.

## 5. Verdict

**API / COMPOSITION MAPPING COMPLETE @ `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`**

```text
CANONICAL ROWS                    = 22
CANONICAL -> CURRENT              = 22 / 22 mapped
CURRENT -> CANONICAL              = CLOSED for inspected API/composition scope
AMBIGUOUS DISPOSITION             = 0
EXACT COMPLETE TARGET PATHS       = 13 / 22

IMPLEMENTATION COMPLETE           = NO
SINGLE COMPOSITION AUTHORITY      = NOT CLOSED
CALLER CLOSURE                    = NO
FROZEN                            = NO
```
