Repair only JSON structure using validator feedback.

Schema-repair guard:
- Preserve answer-vs-plan routing, Action set and IDs, Tool, effect type, target, arguments, Evidence IDs, dependencies, expected results, risks, approval flags, and blocked/confirmation decisions.
- Do not add/remove/reorder an Action for semantic reasons and do not alter user-visible business values merely to satisfy schema validation.
- READ/CREATE/UPDATE/SEND/DELETE meaning and target identity must remain unchanged.
- This is the single schema-repair attempt for this Node call.

Return the full schema-valid ActionPlanDraftV1 and no prose.
