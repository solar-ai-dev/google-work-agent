Task: repair the current node output after a schema/contract failure.
- base_projection is the authoritative runtime input for this node.
- candidate_output is the prior node output to repair.
- failure_record identifies affected_fields and allowed_change_scope.
- Change only fields allowed by allowed_change_scope and only enough to satisfy the declared schema/typing/enum/required-field defect.
- Preserve all unaffected semantics, scope, route facts, evidence references, and user intent.
- Do not add new facts, resources, routes, actions, or evidence to make the output look complete.
- Return the full repaired output object.
