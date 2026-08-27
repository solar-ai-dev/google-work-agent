# Google Work Agent — Implementation Inventory

This directory is an **implementation guide**, not a document-history system.

Its purpose is only to answer, for every canonical capability/artifact:

1. **What does the design require?**
2. **Where is the corresponding code now?**
3. **What must change to converge on the design?**
4. **Has the production caller/test/legacy negative proof been closed?**

**Evidence ref:** `bc0870aa78540f49472a2549d0ff996e66cc0fe2`

`ledger.md` defines the canonical universe. The mapping files record current-code evidence and the required migration. Historical SHA/delta/cycle reports are intentionally not part of this operational set.

## Read order

1. `README.md`
2. `ledger.md`
3. the relevant owner mapping below

## Owner maps

- `domain.md`
- `persistence.md`
- `application.md`
- `agent.md`
- `langgraph.md`
- `ports-connectors.md`
- `api-composition.md`
- `frontend.md`
- `launcher-installer-release.md`
- `observability-evaluation-structural.md`

## Migration rule

```text
KEEP
→ MOVE / MERGE / SPLIT / TARGETED_CORRECTION
→ cut every production caller over
→ delete old/duplicate authority only after cut-over
→ CREATE only the behavior that has no reusable implementation
```

A row is not complete merely because the canonical file exists. It is complete only when:

```text
canonical target exists and owns the behavior
+ intended production callers use it
+ legacy/duplicate authority and old imports are zero
+ exact owner test exists where the Ledger requires one
+ required negative proof is satisfied
```

## Full capability audit at current code

### Application — 99/99 capabilities inspected end-to-end

- exact canonical target present after the current Domain/Application correction slice: **52**
- exact canonical target still absent / requires move, split, merge, targeted correction, or minimal creation: **47**
- exact test ownership is tracked per capability row; corrected Domain-lifecycle mirrors are present, but repository-wide exact-test closure remains **OPEN**
- corrected Domain-lifecycle Application owners/tests are materially present, but global caller/duplicate negative proof is still **OPEN**
- `RejectAction` remains a cross-capability exception: it still directly performs `CompleteWriteRun` parent completion instead of delegating that Application authority


Important current-code corrections are written directly into `application.md`; there is no separate delta document.

### Agent — 43/43 capabilities inspected end-to-end

- exact canonical operation present: **40**
- exact operation absent: **3** (`resolve_policy_preconditions`, `resolve_availability`, `resolve_default_container`)
- exact Ledger test owner present: **10**
- canonical production graph confirmed, legacy/negative proof still open: **14**
- production still uses broad orchestration instead of the exact operations: **23**
- canonical Planning graph selected but semantic invoke wiring is inactive: **3**
- exact operation absent with reusable behavior elsewhere: **3**


## Current Domain/Application correction reflected in this inventory

At the current evidence ref, the formal Domain universe is **61/61** (root + 15 models + 6 vocabularies + 39 lifecycle transitions). The exact `*StatusV1` symbols now exist. Exact persisted Application owners/tests were added for the corrected Run/Plan/Action/Approval/ExecutionAttempt slice, and legacy Action production services were moved out of `src/`.

This does **not** close unrelated Application, Agent, Connector, API, Frontend, LangGraph, Prompt Runtime, Evaluation, Launcher/Release, or global negative-proof work. It also does not waive cross-capability ownership defects such as `RejectAction` directly completing the parent Run.

## Cross-cutting current blockers
- CommandReceipt immutable-finality CAS is now closed; remaining work is caller cut-over from compatibility receipt methods to `reserve_or_replay/store_result`.
- Signed Tool Registry/tool contracts were removed from Domain but currently sit under `ports/connector/migration_contracts`; they still need final ownership in `application/tool_registry`.

- `run.get_run_snapshot`: canonical API caller exists, but broad `QueryService.get_run_snapshot()` remains.
- Conversation transport is not yet canonical: create-conversation still accepts Browser-owned conversation/account identity; list/history use generic wire projections and hard-coded bounds/search semantics differ from the versioned contract.
- `RejectAction` no longer performs the old fake `BeginVerification`, but it still directly performs parent Run `CompleteWriteRun`; that lifecycle responsibility must be delegated to `run.complete_write_run`.
- `ClaimExecution` owns durable claim state correctly but still authors the claim token/context; `claim.build_claim_context` remains absent and must become the single context/token authority.
- current verification flow still combines verification read/compare, Verification persistence/Action transition, and Recovery escalation; split those into the canonical verification/recovery capabilities without discarding the strong implementation.
- Retrieval production still uses `ProjectedContextRetrieverSubgraph → ContextRetrieverSubgraph/ContextRetrievalAgent` instead of the exact Retrieval operations.
- Work Analysis production still uses the broad `WorkAnalysisAgent` path.
- Review production still uses `RuntimeActiveReviewSubgraph` backed by broad `PlanReviewAgent` semantics.
- Planning semantic nodes `compose_answer`, `draft_action_objective_per_output_route`, and `compose_arguments_per_output_route` are selected by the canonical graph but currently receive `_inactive_invoke`; wire real `PlanningRuntimeDependencies`.
- `McpConnectorReadAdapter` and `McpConnectorWriteAdapter` still depend directly on `GoogleWorkspaceGateway`; the registry/MCP port seam is not the sole production connector boundary.
- several exact Port/Adapter paths exist but their callable contracts are still partial (MCP client, structured inference, LLM credential/status, SecretStore, Checkpoint external-LLM scope, Settings, Backup/Restore, Diagnostics, Shutdown, Attachment staging, UUID method, Hardware profile, Component Circuit, SSE buffer). Path presence is not closure.
- non-Domain operational commands must consistently use the existing `OperationalCommandReplayPort` before side effects and reconcile `RECOVER_RESERVED`; current Settings/Backup/Diagnostics/Shutdown/Attachment/credential/connection paths are not all cut over.
- Retrieval `segment_id` is still ordinal `seg-N`; `STR-477 SourceSegmentIdentityV1` remains open.
- exact LLM provider/Ollama leaf structures and Tool Registry implementation/projection rows remain open.
- global caller/import/duplicate/test negative proof remains open; no architecture freeze is declared.

## Formal inventory invariant

The mapping files in this directory must contain every formal Ledger ID exactly once:

```text
CAP = 142
STR = 473
NPA = 85
TOTAL = 700

missing = 0
extra = 0
duplicate = 0
```
