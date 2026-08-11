Revise the previous AnswerDraftV1 only for the supplied failure reason and validator/review feedback in review_issues.

Semantic-revision guard:
- Correct only the identified defect and preserve already-correct answer text, evidence_refs, resource_refs, and reason_codes whenever they are not affected.
- Change only JSON paths listed in each review_issues entry's affected_field_paths. Do not regenerate unrelated content.
- Every claim in the answer must remain grounded in supplied Evidence. Missing evidence routes to NEEDS_CONFIRMATION or BLOCKED; do not invent facts, resources, or sources.
- Never turn the answer draft into an executable Action; this Node produces zero Actions regardless of the failure reason.
- Preserve the user's input language for the answer and any clarification text.
- Do not perform a second semantic revision for the same failure signature.

Return the full corrected AnswerDraftV1 and no prose.
