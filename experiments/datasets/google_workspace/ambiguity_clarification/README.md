# Ambiguity · Clarification Dataset v1.0

- Total: 48
- DEV: 36
- HOLDOUT: 12
- Family split leakage: forbidden
- Measures both Clarification Recall and Unnecessary Clarification Rate.
- Candidate evidence is supplied as read-only context; the LLM must not invent candidates or perform writes.
- `답장/회신/보내줘` = SEND intent; explicit `초안/작성만/Draft` = Draft.
- Low-information action verbs are resolved from prior context when unique, otherwise clarified.
