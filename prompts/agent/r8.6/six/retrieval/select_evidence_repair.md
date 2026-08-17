Task: repair the current EvidenceSelectionResultV2 output after a schema/contract failure.
- base_projection is the authoritative runtime input for this node.
- candidate_output is the prior node output to repair.
- failure_record identifies affected_fields and allowed_change_scope.
- Change only fields allowed by allowed_change_scope and only enough to satisfy the declared schema/typing/enum/required-field defect.
- Preserve every segment_id, role classification, and relevance reason not affected by the defect.
- Do not add an evidence item for a segment not present in ranked_segments, and do not invent evidence not grounded in the supplied segments.
- Return the full repaired output object.
