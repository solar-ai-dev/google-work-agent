Task: produce RequestIntentCandidateV2.
Decision rules:
1. goal: state the user's intended business outcome, not an implementation step.
2. completion_conditions: list observable conditions that would satisfy the request.
3. constraints: include only explicit user constraints or selected-resource scope. Treat selected_resources as hard scope anchors; do not broaden them.
4. requested_effect_hints/requested_resource_hints: reflect user semantics only; they are hints, not tool choices.
5. analysis_requirement=REQUIRED only when the request needs comparison, synthesis, deduplication, conflict/availability reasoning, prioritization, or cross-resource reasoning; otherwise NONE.
6. ambiguity.requires_confirmation=true only for information or preference the user must supply and that ordinary retrieval cannot resolve. Do not ask the user to reconfirm retrievable source facts.
7. Keep business_deadline distinct from scheduled_date. Language meaning “by/deadline” is not automatically a scheduled execution date.
8. Do not perform policy confirmation or scope-expansion logic in this node.
