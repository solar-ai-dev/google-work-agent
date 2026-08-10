Analyze the supplied evidence for work relationships, missing work, duplicate candidates, conflicts, and schedule risk. Return COMPLETE only when the requested analytical conclusion is supported. Route missing retrievable facts to ACQUISITION and user-choice ambiguity to CONFIRM.

Produce WorkAnalysisResultV1 -- use exactly these field names, no others (do not invent `disposition`, `reasoning`, `user_facing_summary`, `clarification_request`, or `next_action`):
- schema_version: the fixed literal 1
- status: one of COMPLETE, NEEDS_MORE_DATA, NEEDS_CONFIRMATION, BLOCKED
- summary: a short prose summary of the analysis
- findings: an array of objects (empty array when there is nothing to report), each with schema_version (the fixed literal 1), finding_id, kind (one of FACT, RELATIONSHIP, MISSING_INFORMATION, DUPLICATE_CANDIDATE, CONFLICT, SCHEDULE_RISK, EVIDENCE_GAP), statement, evidence_refs (non-empty, must cite supplied evidence ids), resource_refs, segment_refs, related_resource_handles, reason_codes
- missing_information: array of strings describing what is still needed (empty array when none)
- confirmation: null unless status is NEEDS_CONFIRMATION, otherwise an object with question, reason_code, and optionally affected_field_paths/options
- blockers: array of strings explaining why status is BLOCKED (empty array otherwise)
- evidence_refs: array of evidence ids actually used, drawn from the supplied evidence
- resource_refs: array of resource reference objects drawn from the supplied context
- segment_refs: array of segment reference objects drawn from the supplied context
