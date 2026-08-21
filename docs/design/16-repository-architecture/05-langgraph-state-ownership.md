# LangGraph & State Ownership Contract

## LangGraph is an orchestration adapter

A node may only perform:

```text
typed state projection
→ application handler call
→ typed validation
→ owner-field patch
→ optional WorkflowSignal
```

A node must not:
- open SQLite,
- mutate repositories directly,
- call Google Provider APIs directly,
- call concrete MCP transport,
- implement Domain transition rules,
- own Approval/Claim/Recovery policy,
- persist Plans directly.

## Main State single writers

Canonical business fields have one owner:

```text
request_intent       → Request Understanding
tool_route_plan      → Tool Route
retrieval_result     → Retrieval
work_analysis_result → Work Analysis
planning_result      → Planning
plan_review          → Review
```

No downstream stage rewrites an upstream artifact.

## Owner-only patch

Preferred:

```python
return {
    "work_analysis_result": result,
    "workflow_signal": signal,
}
```

Forbidden business-state pattern:

```python
return {**state, ...}
```

## Internal control state

Do not proliferate unrelated hidden keys.

Use one typed control namespace, e.g.:

```python
control: MainGraphControlState
```

## Subgraph layout

```text
adapters/langgraph/subgraphs/<role>/
  graph.py
  state.py
  routing.py
  nodes/
```

Semantic Agent logic belongs under `application/agents/<role>/`, not inside the graph adapter.
