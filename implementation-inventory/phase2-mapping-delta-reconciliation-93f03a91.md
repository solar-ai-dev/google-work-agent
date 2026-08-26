# Google Work Agent — Phase-2 Mapping Delta Reconciliation

**Base mapping snapshot:** `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`  
**Observed branch HEAD:** `93f03a918cbd9cfd047da1c1b1ee70aca76da8f6`  
**Delta:** 2 commits (`72ae...` docs mapping + `93f03...` #101 durable workflow runtime cutover)

## 1. Rule

Existing layer mappings remain historical snapshots at their declared SHA. This document records only semantic/structural changes required to interpret them against current HEAD; it does not silently rewrite evidence from a later revision into the older snapshot.

## 2. Affected layer reconciliation

| Layer | #101 delta | Mapping impact | Current disposition |
|---|---|---|---|
| Persistence / UoW | ExecutionAttempt repository gains reconciliation-candidate/query support; WorkflowHandoff settlement/CAS strengthened; checkpoint adapter expanded. | STR-157/158 move materially closer to canonical surface; STR-330/331 KEEP evidence strengthened. CommandReceipt/Retention/Run/Action semantic-authority gaps remain. | **NO DISPOSITION REVERSAL**; upgrade affected coverage only. |
| Application | `execution_attempt/reconcile_inflight_executions.py` added; `application/coordinator.py` removed; cancel/resume/action handlers cut over further. | ReconcileInflight row changes from missing to live PARTIAL/NEAR_FULL canonical authority; broad coordinator reverse-authority blocker removed. | **IMPROVED**; Application implementation still not closed. |
| Application / Approval | `approve_action.py` changed for durable handoff. | Approval now stages PREFLIGHT handoff more canonically, but still calls `plans.activate_waiting()` for `Plan=WAITING_APPROVAL`. | **SEMANTIC DEFECT REMAINS**: approval-gated Write Plan must not become ACTIVE. |
| LangGraph / Checkpoint | state/workflow/background executor/checkpoint adapter expanded; `registry/checkpoint_target_resolver.py` added. | Durable checkpoint lineage/recovery is stronger. New resolver translates legacy runnable/phase names through ResumeTargetRegistry. | **TEMPORARY COMPAT / MIGRATION BRIDGE**; delete or collapse after canonical node/profile/control identity cut-over. |
| API / Composition | composition builds inflight reconciler and handoff runtime; ApiContainer removed internal selection-service construction and is more purely a dependency contract. | Single-root direction improved. `build_production_runtime()` still realizes mainly durable workflow slice; broad dev launcher still performs concrete product composition. | **IMPROVED, NOT CLOSED**. |
| Launcher | `src/google_work_agent/launcher/dev.py` modified heavily. | This misplaced broad development launcher already existed at base SHA and was missed in first Layer-9 reverse pass. Layer-9 artifact has been corrected to map it explicitly. | **SPLIT/MOVE/MERGE**, not greenfield CREATE. |
| Agent / Frontend / Evaluation / Prompt runtime / Installer / Release | No relevant production delta in #101. | Existing 6ec mappings remain applicable. | **UNCHANGED**. |

## 3. High-risk current-HEAD facts

- `ReconcileInflightExecutionsHandler` is now a real canonical Application path and never resends the original Write; however UNKNOWN_RESULT_UNRESOLVED still enters explicit Recovery rather than itself owning external existing-result lookup, so surrounding recovery path remains relevant.
- `ApproveActionHandler` still persists `Plan WAITING_APPROVAL → ACTIVE`, contrary to the current Write-plan lifecycle contract.
- `NativeCheckpointTargetResolver` is useful migration material but contains maps from legacy runnable/phase names and fallback behavior; it must not become a second permanent resume-target registry.
- `api/composition.py` is stronger, but production-wide concrete construction is still partly performed in `src/google_work_agent/launcher/dev.py`.

## 4. Delta verdict

```text
BASE MAPPINGS INVALIDATED              = NO
AFFECTED COVERAGE RECONCILIATION       = COMPLETE
DISPOSITION REVERSALS                  = 0
NEW REVERSE AUTHORITY TO TRACK         = checkpoint_target_resolver.py (compat bridge)
REMOVED REVERSE AUTHORITY              = application/coordinator.py
CURRENT HEAD FOR GLOBAL CLOSURE        = 93f03a918cbd9cfd047da1c1b1ee70aca76da8f6
```
