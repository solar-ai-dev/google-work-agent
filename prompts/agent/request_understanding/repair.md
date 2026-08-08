Repair only the JSON structure using the validator errors.

Schema-repair guard:
- Preserve the previous goal, requested outcome, entry mode, explicit constraints, ambiguity judgment, unsupported-scope judgment, and route.
- Change only fields necessary to satisfy the schema or enum contract.
- Do not infer a missing business fact, add a candidate, remove a user constraint, or convert COMPLETE/NEEDS_CONFIRMATION/INVALID for semantic reasons.
- If semantic correction would be required, keep the semantic decision unchanged and let the caller route to semantic revision.
- This is the single schema-repair attempt for this Node call.

Return the full schema-valid RequestIntentV1 and no prose.
