Recheck the revised plan against the original user goal, supplied evidence/analysis/policy summary, prior failure signature, and revision history.

Recheck guard:
- Review only; do not silently repair, rewrite, add, delete, retarget, or execute an Action.
- Verify that the previously localized defect is actually corrected and that the revision did not introduce a new Tool/effect/target/argument/evidence/dependency/scope defect.
- Return PASS only if the full plan now satisfies the review contract.
- If a different correctable plan defect is present, localize it and return the narrowest valid route.
- If the same semantic failure remains after its one allowed revision, do not request another same-failure revision; report REVIEW_REPEATED_SAME_FAILURE and stop according to the supplied contract.
- Missing current-context evidence routes to RETRIEVE_MORE; required user choice routes to CONFIRM; prohibited operation routes to BLOCK.

Return the full PlanReviewResultV1 and no prose.
