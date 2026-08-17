Task: repair the current SufficiencyResultV2 output after a schema/contract failure.
- base_projection is the authoritative runtime input for this node.
- candidate_output is the prior node output to repair.
- failure_record identifies affected_fields and allowed_change_scope.
- Change only fields allowed by allowed_change_scope and only enough to satisfy the declared schema/typing/enum/required-field defect.
- Preserve all unaffected status and issue judgments.
- Do not add new issues, resources, or routes to make the output look complete.
- Return the full repaired output object.
