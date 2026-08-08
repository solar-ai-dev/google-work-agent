Revise the prior RequestIntentV1 using the supplied failure reason, validator/grader feedback, and changed_fields_allowed.

Semantic-revision guard:
- Correct only the failure signature identified by the caller and only within changed_fields_allowed.
- Preserve every already-correct explicit user date, person, email, selected resource, source boundary, duration, no-write constraint, requested outcome, and completion criterion.
- Do not invent candidates or facts that require Google retrieval. A data-dependent ambiguity discovered later belongs to retrieval/context routing, not Request Understanding.
- If the correction requires a value that the user must supply, return NEEDS_CONFIRMATION with one minimal question; if the request itself is unsupported, return INVALID/blocked routing according to the supplied contract.
- Do not perform a second semantic revision for the same failure signature.

Return the full corrected RequestIntentV1 and no prose.
