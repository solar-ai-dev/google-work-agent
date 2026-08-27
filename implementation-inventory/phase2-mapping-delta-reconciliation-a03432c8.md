# Google Work Agent — Phase-2 Current-HEAD Delta Reconciliation

**Historical mapping base:** `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d` (with Domain/Persistence base at `453e7f0c...`)  
**Previous reconciled HEAD:** `93f03a918cbd9cfd047da1c1b1ee70aca76da8f6`  
**Current reconciled HEAD:** `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`  
**Observed delta from previous HEAD:** 3 commits; includes Issue #104 Domain closure implementation plus mapping/closure evidence commits.

## 1. Reconciliation rule

Historical mapping files retain their declared investigation SHA and preservation-first disposition. This file owns **current implementation-status overrides**. A row whose migration action has been executed at current HEAD is not rewritten as if that code had existed at the historical snapshot.

## 2. Material current-head changes

| Layer | Current-head change | Mapping override | Current status |
|---|---|---|---|
| Domain | `ports/models.py` and `domain/enums.py` removed; owner-local models added/expanded; broad Run/Action transition tables removed; exact model/transition modules added; Domain concrete barrel emptied. Repository closure evidence records 15/15 models + 39/39 transitions. | Historical Domain MOVE/SPLIT/TARGETED_CORRECTION actions for the #104 bounded 54 rows are now largely **executed**. | **#104 BOUNDED CORE CLOSED (54/54)**; repaired vocab rows handled separately. |
| Domain vocabulary | Status enums moved to aggregate model files; `RecoveryReasonV1` remains exact. | `STR-354..358` change from wrong/mixed owner to **owner-local semantic authority**, but current symbols are `RunStatus`, `ActionStatus`, `PlanStatus`, `ApprovalStatus`, `ExecutionAttemptStatus`, not exact Ledger `*StatusV1`. | **BEHAVIOR FULL / OWNER FULL / EXACT SYMBOL PARTIAL** for 354..358; `STR-359` **FULL**. |
| Application | Canonical Domain transition calls are wired into handlers; duplicate approval use-case and multiple broad Run wrappers removed; ExecutionAttempt begin/abort handlers added. | Many 6ec migration dispositions are executed or materially advanced. | **IMPROVED; NOT GLOBAL-FROZEN**. |
| Approval/Plan safety | `ApproveActionHandler` no longer activates `Plan WAITING_APPROVAL → ACTIVE`; it calls `transition_approve_action()` and explicitly keeps Write Plans `WAITING_APPROVAL`. | Previous 93f semantic defect is closed. | **CLOSED @ current HEAD**. |
| Persistence | Repositories now import owner-local Domain models; Run/Action repositories are narrowed to persistence/query/CAS surfaces. | Major duplicate lifecycle-authority blocker removed for the #104 path. | **MATERIALLY IMPROVED; independent persistence-wide closure still required**. |
| Agent tool routing | Tool-routing semantic operations and LangGraph adapters were substantially refactored. | 6ec tool-routing rows require current-status override; preservation source remains valid. | **IMPROVED; per-operation behavior remains governed by canonical rows**. |
| Agent retrieval contracts | No materialization of `application/agents/retrieval/contracts/segment_identity.py` or `query_attempt.py`. Current contracts dir still contains only `__init__.py`. | `STR-477`, `STR-478` remain OPEN structural moves from existing semantics. | **OPEN**. |
| LangGraph | State/workflow, planning/corrective-plan persistence, write execution/recovery and tool-routing graph files changed materially. | Runtime is closer to owner-local Domain/Application contracts. `checkpoint_target_resolver.py` remains a legacy-name translation/fallback bridge. | **IMPROVED; COMPAT BRIDGE OPEN**. |
| Ports / Connector / MCP | Small MCP/stdio changes; Domain record import cut-over occurred. `McpConnectorWriteAdapter` still directly composes provider operations through `GoogleWorkspaceGateway`. | Single external execution seam remains incomplete. | **CONNECTOR MCP BYPASS OPEN**. |
| Tool Registry artifacts | `application/tool_registry/` remains absent. | `STR-303` / `STR-305` and assigned NPA manifest/projection work remain required. | **OPEN**. |
| LLM leaves | Broad `api_provider.py`, `gemini.py`, `ollama.py` and runtime routers remain; exact provider-family/Ollama leaf package files are not materialized. | `STR-459..462,464` remain SPLIT/MOVE migrations, not greenfield rewrites. | **OPEN**. |
| API / Composition | Only narrow API files changed in the #104 delta; main composition findings are not reversed. | API root formal row remains closed; Bootstrap Secret formal row remains Launcher-owned. | **MAPPING CLOSED / RUNTIME ROOT NOT GLOBALLY CLOSED**. |
| Frontend | No production delta observed. | Snapshot applies. | **UNCHANGED**. |
| Launcher / Installer / Release | Launcher only marginally changed; broad `launcher/dev.py` composition remains. | Existing SPLIT/MOVE/MERGE and artifact dispositions remain. | **OPEN**. |
| Observability / Evaluation / architecture enforcement | Domain closure architecture test added; Domain negative proof improved. Evaluation/Prompt/diagnostics artifact families did not receive equivalent closure. | Structural evidence improves, but global freeze remains open. | **PARTIAL / OPEN**. |

## 3. Repaired-row current status

| Repaired row family | Current HEAD result |
|---|---|
| `STR-001..005` repository roots | Roots exist; ownership-root mapping **FULL**. Child closure remains governed by each layer. |
| `STR-303`, `STR-305` | Exact implementation manifest/projection authority still absent → **OPEN**. |
| `STR-354..358` | Owner-local status semantics now live; exact Ledger `*StatusV1` symbol closure remains → **PARTIAL**. |
| `STR-359` | `domain/recovery/model.py::RecoveryReasonV1` exact → **FULL**. |
| `STR-459..462,464` | Exact provider/Ollama leaf package files still absent; reuse broad transports/providers → **OPEN**. |
| `STR-477`, `STR-478` | Exact retrieval contract files still absent; existing `SourceSegment` / `QueryAttempt` semantics remain migration sources → **OPEN**. |
| 36 repaired NPA rows | Formal inventory coverage is closed. Artifact existence/packaging varies and must not be inferred from mapping-row presence. |

## 4. Negative-proof deltas

### Closed since `93f03a91`

- duplicate/broad Domain model authority in `ports/models.py`
- broad root Domain status authority in `domain/enums.py`
- concrete Domain barrel re-export authority
- broad Run and Action transition-table authorities
- duplicate Application approval use-case path
- approval-gated Write Plan activation defect
- major command-specific lifecycle mutation surface in Run/Action SQLite repositories for the #104 path

### Still open

- connector runtime single seam: Registry → `MCPClientPort` is not the only execution path
- exact Signed Tool Registry implementation mirror + connector descriptor projection
- exact LLM leaf package authorities
- exact retrieval owner-local contract files
- legacy checkpoint target translation/fallback bridge
- broad development launcher composition
- Installer/Release/Prompt/Evaluation/diagnostics artifact and negative-proof closure
- exact `*StatusV1` symbols for `STR-354..358`
- production-wide caller/import/export/test negative proof across every canonical row

## 5. Current-head verdict

```text
BASE HISTORICAL MAPPINGS INVALIDATED       = NO
FORMAL CANONICAL EXACT-SET                 = 142 CAP + 473 STR + 85 NPA / PASS
CURRENT-HEAD RECONCILIATION                = COMPLETE THROUGH a03432c8
DOMAIN #104 BOUNDED CORE                   = 54/54 CLOSED
APPROVAL PLAN ACTIVATION DEFECT            = CLOSED
GLOBAL SINGLE-PRODUCTION-AUTHORITY CLOSURE = OPEN
STRUCTURAL CONTRACT PASS                   = NO
ARCHITECTURE FROZEN                        = NO
```
