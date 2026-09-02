Task: produce RetrievalQueryPlanV2.
Decision rules:
1. Use only supplied frozen route_id values. Do not add, replace, or widen a route.
2. required_information describes business facts needed to satisfy the request, not provider syntax.
3. Each route query has operation SEARCH, NEXT_PAGE, DETAIL_FETCH, or FREEBUSY and reason_codes linked to the fixed route or unresolved sufficiency issues.
4. Initial SEARCH uses search_spec.mode INITIAL with a non-empty constraints list. Follow-up changed SEARCH uses mode CHANGED with constraint_delta.upsert_constraints and constraint_delta.remove_constraint_kinds. Each constraint contains its semantic value; never emit name-only deltas.
5. DETAIL_FETCH requires exactly one bounded detail_candidate_ref. NEXT_PAGE carries neither a search_spec nor a detail_candidate_ref.
6. Temporal constraints use local ISO date/datetime values plus an IANA timezone; do not emit provider RFC3339 values.
7. detail_candidate_ref is an opaque bounded candidate reference, never an external resource ID.
8. Do not emit raw page tokens, raw continuations, provider-native query strings, MCP arguments, arbitrary tool IDs, external resource IDs, or raw user_request-derived authority.
9. retrieval_order contains route_id values only. If current routes cannot provide required information, later sufficiency assessment owns route reconsideration.
