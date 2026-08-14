Task: produce RetrievalQueryPlanV1.
Decision rules:
1. Use only supplied route_id values; every required input route must remain represented.
2. required_information describes business facts needed to satisfy the request, not provider syntax.
3. intent_constraints are semantic constraints only. Do not emit raw provider query strings, page tokens, transport arguments, or hand-computed RFC3339 timestamps.
4. operation_preference: SEARCH for matching resources, DETAIL_FETCH for known-resource detail, LIST for bounded listing, FREEBUSY for availability.
5. retrieval_order contains route_id values only.
6. Do not add a new route. If current routes cannot provide required information, later sufficiency assessment owns route reconsideration.
