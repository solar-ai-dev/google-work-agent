Repair only JSON structure using validator feedback.

Schema-repair guard:
- Preserve PASS/REVISE/RETRIEVE_MORE/CONFIRM/BLOCK meaning, every finding, Action/field localization, failure signature, and route.
- Do not change a review verdict, hide a finding, or repair the plan itself for semantic reasons.
- If validator feedback says a field is forbidden for the verdict already chosen (for example: "PASS must not include confirmation"), set only that named field to its empty default (null, or []) and keep the verdict unchanged. If validator feedback says a field is missing (for example: "CONFIRM requires confirmation"), populate only that named field and keep the verdict unchanged. Never change the verdict itself to resolve this kind of feedback.
- This is the single schema-repair attempt for this Node call.

Return the full schema-valid PlanReviewResultV1 and no prose.
