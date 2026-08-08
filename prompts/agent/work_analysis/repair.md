Repair only JSON structure using validator feedback.

Schema-repair guard:
- Preserve analytical meaning, evidence references, relation judgments, duplicate classifications, conflicts, schedule-risk judgments, missing-data decisions, and route.
- Do not add a new inference or change COMPLETE/NEEDS_MORE_DATA/NEEDS_CONFIRMATION/BLOCKED for semantic reasons.
- This is the single schema-repair attempt for this Node call.

Return the full schema-valid WorkAnalysisResultV1 and no prose.
