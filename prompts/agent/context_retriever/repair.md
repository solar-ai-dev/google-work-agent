Repair only the JSON structure using validator feedback.

Schema-repair guard:
- Preserve selected/excluded segment IDs, EvidenceDraft claims and locators, conflict judgments, confidence, ignored untrusted instructions, missing slots, sufficiency, and route.
- Do not add/remove evidence, resolve a conflict, promote a low-confidence candidate, or change sufficiency for semantic reasons.
- Every resource/segment reference must remain one that was already present in the prior output or supplied input.
- This is the single schema-repair attempt for this Node call.

Return the full schema-valid ContextRetrievalResultV1 and no prose.
