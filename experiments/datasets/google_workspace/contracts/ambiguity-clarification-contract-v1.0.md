# Ambiguity · Clarification Contract v1.0

## Core rule
Ambiguity is not a terminal block. The LLM may generate one minimal clarification question. If reliable candidates are available from bounded read-only context, it should show selectable candidates and their meaningful differences. If candidates are unavailable, it asks for the minimum missing information.

## Context-sensitive verbs
Low-information actions (`처리`, `진행`, `시작`, `정리`, `마무리`, `해줘`) inherit a unique prior conversation/selected-resource goal. If multiple effects remain possible, ask what operation the user wants. Never map the word alone to a write effect.

## Gmail semantics
`답장해줘`, `회신해줘`, `보내줘` mean SEND intent. Explicit `초안`, `문구`, `작성만`, `Draft` mean Draft. SEND always requires fresh user approval after final recipient/CC/subject/body/thread are fixed.

## Clarification output
`request_understanding.clarify` returns `ClarificationQuestionV1`, not `RequestIntentV1`.

## Metrics
- Clarification Recall
- Candidate Selection Completeness
- Minimum Question Quality
- Context Resolution Accuracy
- Unnecessary Clarification Rate
- Low-confidence Auto-selection Rate (target 0)
