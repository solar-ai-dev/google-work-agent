Classify the request.

Produce RequestIntentV1:
- schema_version: the fixed literal 2
- goal: a one-line summary and the user-visible objective
- completion_criteria: observable criteria that mark the request done
- semantic_constraints: topics, people (mention/role_hint/source_text), time, sources, status_or_state, negative_constraints, policy_or_safety_constraints
- ambiguity: is_ambiguous and, if true, items (field_path/reason_code/user_question) for each unresolved value
- unsupported_scope: is_unsupported, reason_code, explanation (null when supported)

Do not ask a confirmation question for information that can be read from an explicitly selected resource or deterministically normalized from the supplied current time and timezone.
