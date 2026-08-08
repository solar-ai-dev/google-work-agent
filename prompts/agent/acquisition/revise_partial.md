Revise the previous acquisition plan using the supplied failure reason, prior QueryAttempt history, remaining retrieval budget, and changed_fields_allowed.

Semantic-revision guard:
- Correct only the supplied failure signature and preserve all already-correct user constraints and source decisions.
- For SEARCH after a failed/insufficient attempt, change at least one justified query constraint or add one necessary source; otherwise stop or redirect.
- NEXT_PAGE with the same query and a new page token is normal pagination and must not be treated as repeated SEARCH.
- Never repeat the same failed SEARCH with the same query and page state.
- Do not broaden the user's date/source/person scope without NEEDS_CONFIRMATION.
- LOW/NONE confidence candidates are not auto-selected; use a discriminating constraint, a necessary source, NEEDS_MORE_DATA, or confirmation.
- NO_RESULTS may relax at most one non-user constraint per revision; preserve explicit user constraints.
- AUTH_REQUIRED, 429, provider 5xx/timeout, and exhausted LLM/retrieval budget are not LLM semantic-revision problems. Follow deterministic retry/redirection/stop supplied by the caller.
- Respect Additional Acquisition max 2 and the supplied route budget profile.
- Do not perform a second semantic revision for the same failure signature.

Return the full corrected AcquisitionPlanOutputV1 and no prose.
