# CHANGELOG — 2026-08-19

## Canonical sync

- Conversation is a UI/persistence timeline, not implicit Agent semantic memory.
- New USER requests always start a new Run/Thread/RunInput even inside the same Conversation.
- Same-run Confirmation/Reauth/Recovery resumes the existing safe checkpoint.
- Team Conversation History/UI changes were incorporated into Functional/UI/Interface/Test contracts.
- Prompt Runtime Closure remains a non-active candidate: 27 Active Runtime Slots + 3 Retired Slots.
- Planning ACTION authoring is OutputToolRouteV1-at-a-time with deterministic tool/schema/dependency/expected ownership.
- Retrieval V2 remains the existing canonical implementation; no parallel reimplementation.
- Database migrations 0001–0005 remain immutable.
