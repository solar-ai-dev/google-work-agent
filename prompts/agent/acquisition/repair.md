Repair only the JSON structure using validator errors.

Schema-repair guard:
- Preserve source selection, priority, normalized user constraints, budgets, entry mode, result, and route.
- Do not add/remove a source, broaden/narrow a query constraint, change a selected resource, or change NO_FETCH_NEEDED/PLAN_READY for semantic reasons.
- Do not manufacture a page token, resource ID, candidate score, or QueryAttempt.
- This is the single schema-repair attempt for this Node call.

Return the full schema-valid AcquisitionPlanOutputV1 and no prose.
