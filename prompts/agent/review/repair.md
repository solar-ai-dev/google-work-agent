Repair only JSON structure using validator feedback.

Schema-repair guard:
- Preserve PASS/REVISE/RETRIEVE_MORE/CONFIRM/BLOCK meaning, every finding, Action/field localization, failure signature, and route.
- Do not change a review verdict, hide a finding, or repair the plan itself for semantic reasons.
- This is the single schema-repair attempt for this Node call.

Return the full schema-valid PlanReviewResultV1 and no prose.
