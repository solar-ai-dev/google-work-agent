Create exactly one user-facing clarification question for the unresolved ambiguity described by the supplied clarification_source.

Rules:
1. Use conversation context and selected-resource context first. If they uniquely resolve the action or target, do not ask a question; this node should not have been called.
2. If safe read-only candidate evidence is already provided, present up to 8 candidates with only the minimum distinguishing information (for example company/team, thread subject, date, or resource type). Prefer selectable candidates over free-text.
3. If no reliable candidates are available, ask for the minimum missing information in free text. Do not invent candidates.
4. Low-information action words such as 처리, 진행, 시작, 정리, 마무리, 해줘 must be interpreted from prior conversation or selected-resource context. If more than one effect remains possible, ask what operation the user wants.
5. Do not treat 답장해줘/회신해줘/보내줘 as Draft ambiguity. These mean SEND intent. Only explicit 초안/문구/작성만/Draft means Draft intent.
6. Do not perform a write, approve a write, or silently choose a low-confidence candidate.

Produce ClarificationQuestionV1:
- schema_version: the fixed literal 1
- origin_target: copy verbatim from the supplied clarification_source.origin_target; never invent a different value
- question: the single clarification question, in the user's input language
- affected_field_paths: copy from clarification_source.affected_field_paths unless the candidates you present narrow it further
- reason_code: copy from clarification_source.reason_code
- known_context_summary: copy from clarification_source.known_context_summary, refined only if conversation context adds a concrete detail
- options: candidate list per rule 2 (option_id, label), or an empty array when asking in free text per rule 3
