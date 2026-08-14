Task: produce PlanReviewResultV2.
Check, in order:
1. Does the proposed result satisfy the user goal and completion conditions?
2. Is every material claim/action argument supported by evidence or explicit user input?
3. Are there unnecessary actions, missing required actions, contradictions, or invalid dependencies?
4. Does the result stay consistent with the fixed output plan without reselecting tools/effects?
5. Does supplied policy_summary explicitly require confirmation or prohibit the proposal? Do not invent policy beyond the summary.
Disposition rules:
- PASS: no material defect remains.
- REVISE: a local planning defect can be fixed from existing input/evidence.
- RETRIEVE_MORE: missing evidence is obtainable through the current input routes.
- ROUTE_RECONSIDERATION: the fixed route cannot satisfy the request.
- CONFIRM: a user-owned decision is required.
- BLOCK: supplied policy_summary explicitly establishes a prohibition.
