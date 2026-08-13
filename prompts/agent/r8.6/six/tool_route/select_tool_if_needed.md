Task: produce ToolSelectionV1 for the supplied route_id.
Decision rules:
- connector_id, resource_type, and effect are already fixed. Do not reinterpret them.
- selected_tool_id must be copied exactly from eligible_tool_ids.
- Never synthesize, rename, normalize, or guess a tool identifier.
- Do not use any information outside this input to choose a tool.
