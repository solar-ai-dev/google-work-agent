Failure reason: PLAN_POLICY_RISK

Remove executable truly forbidden operations or policy-bypass behavior. Do not classify a registered approval-gated SEND, Task-completion UPDATE, Calendar DELETE, or attendee UPDATE as forbidden solely because it has external impact. Return BLOCKED only when the requested operation itself is prohibited; use confirmation/approval routes for supported operations whose target or approval boundary is unresolved.
