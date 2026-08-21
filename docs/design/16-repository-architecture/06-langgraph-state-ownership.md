# 06. LangGraph · State Ownership

> Parent: Repository Architecture Source v1.4  
> Behavioral semantics and versioned runtime capability IDs remain owned by 06 Agent · Workflow / 15 Prompt · Failure.

## Six semantic owners

```text
request_understanding
tool_routing
retrieval
work_analysis
planning
review
```

Canonical role display name is `Tool Routing`; package owner is `tool_routing`. Existing contract artifact `ToolRoutePlanV2` remains unchanged.

## Main graph

```text
adapters/langgraph/main/graph.py
adapters/langgraph/main/state.py
adapters/langgraph/main/routing/route_after_<stage>.py
adapters/langgraph/main/projections/<scope>_projection.py
```

## Role subgraph

```text
adapters/langgraph/subgraphs/<role>/graph.py
adapters/langgraph/subgraphs/<role>/state.py
adapters/langgraph/subgraphs/<role>/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<role>/projections/<scope>_projection.py
adapters/langgraph/subgraphs/<role>/nodes/<verb>_<object>_node.py
```

Catch-all final-production `routing.py` is prohibited. Each router is `route_after_<stage>.py → route_after_<stage>()`.

## Application semantic owner

Every semantic capability invoked by a LangGraph node has one Application owner operation:

```text
application/agents/<role>/<verb>_<object>.py
→ <verb>_<object>()
```

The LangGraph node is not a second semantic implementation.

## Thin-node rule

A LangGraph node owns only:

```text
typed input projection
→ Application semantic call
→ typed owner-field patch
→ optional WorkflowSignal
```

It does not own provider access, concrete persistence, Domain transition authority, or a second implementation of the semantic capability.

## Canonical repository capability namespace

The following repository labels mirror the currently versioned 06/15 semantic responsibilities. 16 does not independently rename those runtime IDs.

```text
request_understanding.identify_goal
request_understanding.detect_ambiguity
request_understanding.finalize_intent
request_understanding.validate_intent

tool_routing.determine_io_resources
tool_routing.bind_registry_candidates
tool_routing.select_tool_if_needed
tool_routing.finalize_route
tool_routing.validate_route

retrieval.plan_query
retrieval.build_query
retrieval.execute_read
retrieval.normalize_segments
retrieval.rag_retrieve_rerank
retrieval.select_evidence
retrieval.assess_sufficiency
retrieval.finalize_retrieval

work_analysis.extract_work_facts
work_analysis.resolve_entity_relations
work_analysis.resolve_temporal_dependencies
work_analysis.detect_duplicate_conflict_candidates
work_analysis.validate_relations
work_analysis.assess_information_gaps
work_analysis.assess_operational_risks
work_analysis.assemble_work_analysis
work_analysis.validate_work_analysis

planning.choose_answer_or_action_from_route
planning.outline_answer
planning.compose_answer
planning.draft_action_objective_per_output_route
planning.compose_arguments_per_output_route
planning.build_dependencies
planning.assemble_plan
planning.validate_plan

review.inspect_goal_and_evidence
review.inspect_action_scope_and_route
review.inspect_constraints_and_policy_summary
review.aggregate_review_findings
review.validate_review
review.recheck_affected_dimensions
```

`planning.build_dependencies` is deterministic. `planning.compose_dependencies` is not a Product Prompt/LLM authority.

## Main State authority

One semantic fact has one owner field. Do not create aliases such as `route_plan` beside `tool_route_plan` or `analysis_result` beside `work_analysis_result`.
