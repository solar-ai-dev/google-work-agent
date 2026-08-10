Classify the request.

Produce RequestIntentV1. Every field listed below with sub-fields is a JSON object or an array of JSON objects, never a plain string or an array of plain strings -- always emit the full object shape even when a sub-field only restates the parent value.

- schema_version: the fixed literal 2
- goal: an object -- summary (one-line summary of the request) and user_visible_objective (the outcome the user will see)
- completion_criteria: an array of strings; observable criteria that mark the request done
- semantic_constraints: an object with these array fields (empty array when none apply):
  - topics: array of objects -- text, source_text
  - people: array of objects -- mention, role_hint (or null), source_text
  - time: array of objects -- mention, granularity_hint (one of DATE, DATETIME, RANGE, RELATIVE, UNKNOWN), source_text
  - sources: array of objects -- source (one of GMAIL, TASKS, CALENDAR, UNKNOWN), mention, confidence (one of HIGH, MEDIUM, LOW)
  - status_or_state: array of objects -- mention, source_text
  - negative_constraints: array of strings
  - policy_or_safety_constraints: array of strings
- ambiguity: an object -- is_ambiguous, and if true, items: array of objects (field_path, reason_code, user_question) for each unresolved value
- unsupported_scope: an object -- is_unsupported, reason_code, explanation (reason_code and explanation are null when supported)

Do not ask a confirmation question for information that can be read from an explicitly selected resource or deterministically normalized from the supplied current time and timezone.
