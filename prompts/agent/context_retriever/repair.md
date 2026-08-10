Repair only the JSON structure using validator feedback.

Schema-repair guard:
- Preserve selected/excluded segment IDs, EvidenceDraft claims and locators, conflict judgments, confidence, ignored untrusted instructions, missing slots, sufficiency, and route.
- Do not add/remove evidence, resolve a conflict, promote a low-confidence candidate, or change sufficiency for semantic reasons.
- Every resource/segment reference must remain one that was already present in the prior output or supplied input.
- This is the single schema-repair attempt for this Node call.
- The correct output shape is whichever JSON Schema this call declares (the same shape the failed `previous_output` was attempting) -- either the Evidence Selection result or the Context Sufficiency result. Match that declared schema exactly; do not invent a different top-level shape.

Return the full schema-valid structured output and no prose.
