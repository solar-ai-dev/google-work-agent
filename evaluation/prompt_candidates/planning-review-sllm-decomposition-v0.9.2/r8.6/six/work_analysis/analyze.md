Task: produce WorkAnalysisCandidateV2.
Decision rules:
1. Every work fact and relation candidate must be grounded in supplied evidence; include evidence references in the object content when the schema permits and list all used refs in top-level evidence_refs.
2. relation_candidates are hypotheses for deterministic validation. Do not declare DUPLICATES or CONFLICTS_WITH as final truth from semantic similarity alone.
3. Use availability_results as deterministic interval facts; do not recompute or override them.
4. policy_confirmation_receipt_refs are opaque runtime facts. Never create, alter, or infer a receipt.
5. COMPLETE: analysis is sufficient. NEEDS_MORE_DATA: same-route evidence is missing. ROUTE_RECONSIDERATION_REQUIRED: another route is needed. NEEDS_CONFIRMATION: a user choice is required. BLOCKED: only when supplied runtime facts explicitly establish a block.
6. Do not create actions or tool arguments.
