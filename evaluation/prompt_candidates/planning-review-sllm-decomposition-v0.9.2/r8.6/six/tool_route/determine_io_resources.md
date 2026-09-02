Task: produce RouteResourceCandidateV1.
Decision rules:
1. Choose input/output resource types only from EMAIL, TASK, CALENDAR and only when supported by eligible_route_capabilities.
2. Output effects are CREATE, UPDATE, SEND, or DELETE only. READ belongs to input resource needs, never to output effects.
3. Preserve the request's explicit source scope. Do not add duplicate-check, conflict-check, or other policy-precondition reads; deterministic PolicyPreconditionResolver owns those additions and any resulting confirmation.
4. ROUTE_READY: the semantic route is resolvable.
5. NO_TOOL_NEEDED: the request can be answered without connector data or output action.
6. NEEDS_CONFIRMATION: use only when the supplied RequestIntent still contains a user-owned routing ambiguity that cannot be resolved from eligible capabilities.
7. BLOCKED: use only when the fixed requested resource/effect cannot be satisfied by any supplied eligible capability and clarification cannot change that fact. Do not infer policy blocks from source text.
8. Keep output_resource_types and output_effects positionally aligned when both are non-empty.
