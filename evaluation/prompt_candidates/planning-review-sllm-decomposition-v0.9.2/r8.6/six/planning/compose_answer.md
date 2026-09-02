Task: produce AnswerDraftCandidateV2.
Decision rules:
1. Answer the user's business question directly and only from supplied evidence and optional work_analysis.
2. Include only evidence_refs actually supporting the answer.
3. Preserve uncertainty, contradictions, and partial-source limitations; do not turn them into certainty.
4. Do not claim that an external write, approval, verification, or recovery occurred unless that fact is explicitly present in the runtime input.
5. Keep user-facing text free of internal route, schema, and workflow jargon unless the user asked for technical detail.
