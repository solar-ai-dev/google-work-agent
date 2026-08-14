# 2026-08-15 Export Change Summary

## Canonical version changes

- 05 Context·Retrieval: **v2.12 → v2.13**
- 06 Agent·Workflow: **v7.15 → v7.16**
- 12 Test: **v3.32 → v3.33**
- 15 Agent Capability·Failure·Prompt: **v1.21 → v1.22**

Reference/date synchronization only: 07, 08, 10, 11, 13, 14.

## Retrieval contract

- `RetrievalQueryPlanV2 / RouteQueryIntentV2`
- typed `SemanticRetrievalConstraintV1`
- `ConstraintDeltaV2` for changed SEARCH
- deterministic `SourceFetchPlanBuilder → SourceFetchPlanV1`
- `RetrievalStateV2`
- raw `user_request` is not a separate Retrieval planner authority
- Provider-native query/RFC3339/raw continuation/MCP Arguments remain deterministic-code authority
- `QueryAttempt.added_constraints/removed_constraints` remain observation/follow-up summary only

## Unchanged immutable artifacts

`0001~0005` SQL migrations are historical/checksum artifacts and were copied without content modification. State transition contract/matrix remain Canonical v1.5 while compatibility filenames retain `v1.4`.
