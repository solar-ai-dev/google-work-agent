Classify the request.

Produce the runtime-compatible RequestIntentV2 projection. Every field listed below with sub-fields is a JSON object or an array of JSON objects, never a plain string or an array of plain strings -- always emit the full object shape even when a sub-field only restates the parent value.

- schema_version: the fixed literal 2
- goal: an object -- summary (one-line summary of the request) and user_visible_objective (the outcome the user will see)
- completion_criteria: an array of strings; observable criteria that mark the request done
- semantic_constraints: an object with these array fields (empty array when none apply):
  - topics: array of objects -- text, source_text
  - people: array of objects -- mention, role_hint (or null), source_text
  - time: array of objects -- mention, granularity_hint (one of DATE, DATETIME, RANGE, RELATIVE, UNKNOWN), source_text
  - sources: array of objects -- source (one of GMAIL, TASKS, CALENDAR, UNKNOWN), mention, confidence (one of HIGH, MEDIUM, LOW)
  - status_or_state: array of objects -- mention, source_text
  - negative_constraints: array of strings
  - policy_or_safety_constraints: array of strings
- ambiguity: an object -- is_ambiguous, and if true, items: array of objects (field_path, reason_code, user_question) for each unresolved value
- unsupported_scope: an object -- is_unsupported, reason_code, explanation (reason_code and explanation are null when supported)
- response_disposition: one of ANSWER_ONLY or ACTION_REQUIRED. This field, not any keyword list, decides whether the run later calls the answer-only prompt or the action-plan prompt -- classify by what the user is actually asking for, in any language, never by matching literal words.
- requested_effect_hints: the user-requested semantic effects only, from READ, CREATE, UPDATE, SEND, DELETE. These are meaning hints, never Tool names.
- requested_resource_hints: semantic resource types such as GMAIL_THREAD, GMAIL_MESSAGE, GMAIL_DRAFT, TASK, TASK_LIST, CALENDAR_EVENT, CALENDAR, or CALENDAR_FREEBUSY. Never emit an MCP Tool name.
- analysis_requirement: NONE when arguments or a direct answer need no relationship/conflict/derived-fact reasoning; REQUIRED when work analysis is needed. Policy precondition analysis may still make the effective requirement REQUIRED later.
  - ANSWER_ONLY: the user wants information, a summary, an analysis, or a status check, with no new or changed Gmail/Task/Calendar resource. Explicit no-write language ("새 항목은 만들지 마") is always ANSWER_ONLY. A request to look up, list, or tell the user something ("알려줘", "요약해줘", "정리해줘", "tell me", "summarize", "what is") stays ANSWER_ONLY even when it names a Source like Calendar or Gmail -- naming the Source to read from is not itself a request to change anything in it.
  - ACTION_REQUIRED: the user is asking to create, draft, send, update, schedule, or delete a Gmail/Task/Calendar resource, even when phrased as a request rather than a command, and even when the resource is referenced only as "this"/"이거"/"이 메일"/"이 할 일" via an explicitly selected resource. Creating a Gmail Draft counts as a resource change (a new Draft exists) even though nothing is sent -- "초안 만들어줘"/"draft a reply" is ACTION_REQUIRED, not ANSWER_ONLY, because it results in a saved Draft the user must approve.
  - Examples: "오늘 일정 알려줘" / "What's on my calendar today" -> ANSWER_ONLY (reads Calendar, changes nothing). "미완료 업무 정리해줘. 새 항목은 만들지 마" -> ANSWER_ONLY. "이 메일에 답장 초안 만들어줘" / "Draft a reply to this email" -> ACTION_REQUIRED (creates a Gmail Draft). "내일 오후에 작업 일정 잡아줘" / "Schedule a work block tomorrow afternoon" -> ACTION_REQUIRED (creates a Calendar Event). "이 할 일 삭제해줘" / "Delete this task" -> ACTION_REQUIRED (deletes a Task).
  - If the request text alone does not make the intended disposition clear (for example the target of the action is unstated), do not guess: set ambiguity.is_ambiguous to true with an item explaining what is unclear, and still provide your best-guess response_disposition -- the ambiguity takes precedence at routing time.

Do not ask a confirmation question for information that can be read from an explicitly selected resource or deterministically normalized from the supplied current time and timezone.
