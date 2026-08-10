Revise the previous ActionPlanDraftV1 only for the supplied failure reason and validator/review feedback in review_issues.

Semantic-revision guard:
- Correct only the identified defect and preserve already-correct Actions, Action IDs, ordering, arguments, Evidence IDs, and user scope whenever they are not affected.
- Change only JSON paths listed in each review_issues entry's affected_field_paths. Do not regenerate unrelated arguments or add a merely helpful Action.
- Use only registered P0 Tools. READ requires no approval; CREATE has no existing target; UPDATE retains the exact existing target; SEND retains exact thread/recipient/content bindings; DELETE is only Calendar Event deletion with an exact target.
- Every executable Action must remain grounded in supplied Evidence. Missing evidence routes to retrieval/confirmation; do not invent it.
- Preserve explicit date/time/timezone/duration/recipient/task-list/calendar/content and confirmed duplicate constraints.
- Truly forbidden operations are never transformed into another executable operation merely to make the plan pass. Supported high-impact operations are not blocked solely because they are SEND/DELETE/Task-completion/attendee-update; they must preserve approval and verification requirements.
- Dependencies must stay acyclic.
- All CREATE/UPDATE/SEND/DELETE writes remain proposals requiring approval; READ does not. Do not claim execution or verification.
- Do not perform a second semantic revision for the same failure signature.

Return the full corrected ActionPlanDraftV1 and no prose.
