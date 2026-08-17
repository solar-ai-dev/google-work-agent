Task: revise the current EvidenceSelectionResultV2 output after an allowed semantic defect was detected.
- Use base_projection as the only source of runtime facts.
- Use candidate_output as the starting point.
- Change only failure_record.affected_fields within failure_record.allowed_change_scope.
- Correct the identified local defect (for example a wrong SUPPORTS/CONTRADICTS/CONTEXT role, a wrongly included or excluded segment_id, or a relevance reason not grounded in request_intent) without widening scope or taking over another node's responsibility.
- If the defect belongs to another node's responsibility (query planning, sufficiency), do not silently compensate by inventing route, query, or sufficiency facts.
- Return the full revised output object.
