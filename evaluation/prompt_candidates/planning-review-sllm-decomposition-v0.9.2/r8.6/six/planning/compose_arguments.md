Task: produce ToolArgumentCandidateV1 for exactly one supplied output_route.
Decision rules:
1. Copy output_route.route_id exactly into route_id. Tool identity/effect are fixed and must not be returned as choices.
2. arguments must conform to selected_tool_schema and use only facts supported by user_request, request_intent, work_analysis, or evidence. Never fabricate a required argument.
3. evidence_refs contains only evidence actually used to derive arguments.
4. Keep business_deadline distinct from scheduled_date. Populate a provider scheduling/due field only from explicit scheduled-date/execute-on semantics, never merely from “by/deadline” wording. Preserve a business deadline in notes only when user intent and the selected schema allow it.
5. For EMAIL recipients, CALENDAR times/attendees, TASK targets, UPDATE/DELETE targets, and other irreversible identifiers, require explicit or evidence-backed values.
6. Never invent attachment bytes, filenames, local paths, hashes, credentials, or external IDs.
7. Do not add general READ actions or silently choose a different route/tool when arguments are incomplete.
