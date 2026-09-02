Task: revise the current node output after an allowed semantic defect was detected.
- Use base_projection as the only source of runtime facts.
- Use candidate_output as the starting point.
- Change only failure_record.affected_fields within failure_record.allowed_change_scope.
- Correct the identified local semantic defect without widening user scope or taking over another node's responsibility.
- If the defect belongs to another node's responsibility, do not silently compensate by inventing route/evidence/action facts.
- Return the full revised output object.
