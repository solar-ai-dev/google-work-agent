Task: produce RetrievalQueryPlanV1.
Decision rules:
1. Use only supplied frozen route_id values. Do not add, replace, or widen a route.
2. required_information describes business facts needed to satisfy the request, not provider syntax.
3. Each route query has operation_kind SEARCH, NEXT_PAGE, DETAIL_FETCH, or FREEBUSY and reason_codes linked to unresolved sufficiency issues.
4. SEARCH requires a non-empty semantic constraint_delta. DETAIL_FETCH requires exactly one bounded detail_candidate_ref. NEXT_PAGE carries neither field.
5. detail_candidate_ref is an opaque bounded candidate reference, never an external resource ID.
6. Do not emit raw page tokens, raw continuations, provider-native query strings, MCP arguments, arbitrary tool IDs, or external resource IDs.
7. retrieval_order contains route_id values only. If current routes cannot provide required information, later sufficiency assessment owns route reconsideration.
