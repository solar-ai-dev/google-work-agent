# Human Policy Corrections v1.7

## Calendar
`overlap != conflict`. Classify `NESTED_RELATED`, `TRUE_BUSY_CONFLICT`, `TENTATIVE`, `FREE_OR_TRANSPARENT`, `UNKNOWN_RELATION`. Relation evidence is required.

## Ambiguity
Ambiguous target -> `request_understanding.clarify` (`CLARIFY`) -> `QUESTION_READY` -> user interrupt -> resume same run/thread. Do not auto-select.

## Unbounded retrieval
Whole-mailbox / all-source unbounded scan -> `BLOCKED` before Google calls. A later new bounded request may start a new safe path, but the unbounded request itself is not converted into a continuation query.

## Gmail send
R7 decision supersedes the prior pending state: `gmail_send` is a supported approval-gated SEND effect with SENT_LOOKUP verification and no automatic resend on UNKNOWN_RESULT.
