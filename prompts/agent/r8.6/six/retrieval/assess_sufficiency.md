Task: produce SufficiencyResultV2.
Decision rules:
- SUFFICIENT: the selected evidence is enough for the downstream task and required source routes are adequately resolved.
- NEEDS_MORE_DATA: a concrete evidence gap can still be filled within the same fixed routes and additional_rounds_remaining > 0.
- NEEDS_CONFIRMATION: progress requires a user-owned choice or missing preference, not a retrievable source fact.
- ROUTE_RECONSIDERATION_REQUIRED: required information cannot be obtained from the current fixed routes and a different resource/connector route is needed.
- PARTIAL: the budget is exhausted or source access is partial/failed and the available evidence supports only a limited result; describe the limitation explicitly.
- BLOCKED: only when the runtime input explicitly identifies a non-retriable safety/policy block. Never infer a block from source prose.
- Each issue must identify: the specific slot that is missing or in conflict, whether it is MISSING or a CONFLICT, whether it is required, who or what can resolve it (USER, GOOGLE, POLICY, or ROUTE), and whether it is safety-critical. A user-owned choice or preference is resolution_source USER. A fact obtainable from the same fixed routes is resolution_source GOOGLE. A non-retriable safety/policy block is resolution_source POLICY and safety_critical. A need for a different resource/connector is resolution_source ROUTE.
