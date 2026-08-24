# 06. LangGraph · State Ownership

**Normative detail of the current Repository Architecture Source.**

Main Graph routing is deterministic. Six native semantic owners are `request_understanding`, `tool_routing`, `retrieval`, `work_analysis`, `planning`, `review`.

Repository placement is fixed:

```
application/agents/<role>/<verb>_<object>.py
adapters/langgraph/main/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<role>/routing/route_after_<stage>.py
adapters/langgraph/subgraphs/<role>/nodes/<verb>_<object>_node.py
```

Catch-all final-production `routing.py` is prohibited. Router symbols are `route_after_<stage>()`.

A LangGraph node is a thin adapter only:

```
typed input projection
→ application semantic call
→ typed owner-field patch
→ optional WorkflowSignal
```

A node must not own business semantics, concrete persistence, Provider SDK access, or Domain transition authority.

Repository semantic owner/package is `Tool Routing` / `tool_routing`; existing contract artifact `ToolRoutePlanV2` remains unchanged.

Versioned Runtime Node identifiers and PromptRef IDs remain owned by 06 Workflow / 15 Prompt·Failure and are not silently renamed by Repository Architecture. Repository operation labels are a separate naming namespace: e.g. runtime `analysis.extract_facts` maps to repository `work_analysis.extract_work_facts`, and runtime `request.*` maps to repository owner `request_understanding.*`. Supporting deterministic Application operations may also have repository files without becoming independent LangGraph Nodes. Current examples are `retrieval.resolve_availability`, plus `work_analysis.validate_work_analysis` inside runtime `analysis.finalize`, `planning.validate_plan` inside runtime `planning.assemble`, and `review.validate_review` inside runtime `review.aggregate_findings`.

The current Workflow / Prompt·Failure contracts own the heavy-Agent atomic responsibility topology. Repository implementation therefore keeps these semantic calls in distinct operation files under their existing owner packages:

```
work_analysis/
  extract_work_facts
  resolve_entity_relations
  resolve_temporal_dependencies
  detect_duplicate_conflict_candidates
  validate_relations                 # deterministic
  assess_information_gaps
  assess_operational_risks
  assemble_work_analysis             # deterministic
  validate_work_analysis             # deterministic

planning/
  outline_answer
  compose_answer
  draft_action_objective_per_output_route
  compose_arguments_per_output_route
  build_dependencies                 # deterministic
  assemble_plan                      # deterministic
  validate_plan                      # deterministic

review/
  inspect_goal_and_evidence
  inspect_action_scope_and_route
  inspect_constraints_and_policy_summary
  aggregate_review_findings          # deterministic
  validate_review                    # deterministic
  recheck_affected_dimensions
```

The deterministic planning dependency repository implementation capability/file uses `build_dependencies`; `planning.compose_dependencies` is not a Product Prompt/LLM authority. Runtime Node/Prompt IDs remain 06/15 authority, while this page controls repository placement and file responsibility.

## Current Runtime Node → repository operation mapping

| Runtime identity/stage | Repository semantic operation |
| --- | --- |
| `request.identify_goal` | `request_understanding.identify_goal` |
| `request.detect_ambiguity` | `request_understanding.detect_ambiguity` |
| `request.finalize` | `request_understanding.finalize_intent` → `request_understanding.validate_intent` |
| Tool Route precondition stage | `tool_routing.resolve_policy_preconditions` |
| `retrieval.rag_retrieve` | `retrieval.rag_retrieve_rerank` |
| `analysis.finalize` | `work_analysis.assemble_work_analysis` → `work_analysis.validate_work_analysis` |
| Planning entry branch | `planning.choose_answer_or_action_from_route` |
| `planning.derive_dependencies` | `planning.build_dependencies` |
| Planning pre-argument binding | `planning.resolve_default_container` |
| `planning.assemble` | `planning.assemble_plan` → `planning.validate_plan` |
| `review.inspect_action_scope_route` | `review.inspect_action_scope_and_route` |
| `review.inspect_constraints_policy` | `review.inspect_constraints_and_policy_summary` |
| `review.aggregate_findings` | `review.aggregate_review_findings` → `review.validate_review` |

Arrow-separated operation pairs execute inside the same deterministic runtime node/stage; they do not create hidden LangGraph nodes.

## Node Registry · Resume Target Registry exact production authority

06 owns Runtime Node IDs and safe-resume semantics. Repository lookup/placement is singular:

```text
adapters/langgraph/registry/node_registry.py
→ NodeRegistry

adapters/langgraph/registry/resume_target_registry.py
→ ResumeTargetRegistry
```

`NodeRegistry` is built at graph compile time from the exact 35 current Agent runtime-node rows below plus the 06-owned profile binding `SemanticAgentOwnerIdV1 × GraphProfileIdV1 → CompiledAgentSubgraphIdV1`. It provides `get_required(graph_version, graph_profile, semantic_owner_id, node_id)` / `contains(...)` and returns the expected compiled-subgraph namespace for that node.

`ResumeTargetRegistry` is the **single safe-resume target authority** and issues/validates `RegisteredResumeTargetRefV2` in two closed forms:

```text
issue_agent_node(graph_profile, semantic_owner_id, node_id, graph_version)
→ AgentNodeResumeTargetV2
→ must match NodeRegistry + exact profile semantic→physical binding

issue_main_stage(graph_profile, stage_id, graph_version)
→ MainControlResumeTargetV2
→ stage_id must be one of RETRIEVAL_ENTRY | PLANNING_ENTRY | REVIEW_ENTRY | PREFLIGHT | READ_EXECUTION | VERIFICATION | RECOVERY | CANCEL_RESOLUTION

validate(ref)
→ fail closed on unknown/stale profile/version/owner/subgraph/node/stage
```

All 35 current Agent runtime nodes are safe **node-boundary** registry targets because they do not perform external Write or Domain mutation directly. Main control stages are **not** NodeRegistry entries; only the 06-owned resumable main-stage closed set is accepted directly by `ResumeTargetRegistry`. `READ_EXECUTION` is a Legacy READ-only non-mutating compatibility target and requires `Run=EXECUTING + READ Action=EXECUTING + ExecutionAttempt row=0`; approval-gated Write는 사용할 수 없다. `ACTION_EXECUTION` is explicitly not resumable: after Write dispatch start, Run may still be `WAITING_APPROVAL`, so current ExecutionAttempt/delivery fact must force reconciliation/Verification/Recovery before any resume.

Graph profile builders register node definitions and exact semantic-owner→compiled-subgraph bindings, then build one ResumeTargetRegistry bound to the compiled `graph_version`. Subgraph-local dicts, profile-specific duplicate registries, second Main-stage registries, checkpoint-adapter lookup tables, and free-string target validation are prohibited.

Tests:

```text
tests/architecture/langgraph/registry/test_node_registry.py
tests/architecture/langgraph/registry/test_resume_target_registry.py
```

## Exact 35 Runtime Node adapter manifest

This table is the closed repository realization of the 35 current Agent Runtime Node IDs in 06. The **typed state fields/output semantics themselves remain 06 authority**; node adapters may patch only the owner-local typed state/result declared there and may not invent foreign Main State fields.

| Runtime Node ID | Exact node adapter | Exact input projection | Called Application operation(s) | Exact router | Resume target | Test |
| --- | --- | --- | --- | --- | --- | --- |
| `request.identify_goal` | `adapters/langgraph/subgraphs/request_understanding/nodes/identify_goal_node.py` → `identify_goal_node()` | `adapters/langgraph/subgraphs/request_understanding/projections/identify_goal_projection.py` → `project_identify_goal_input()` | `request_understanding.identify_goal` | `adapters/langgraph/subgraphs/request_understanding/routing/route_after_identify_goal.py` → `route_after_identify_goal()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/request_understanding/test_identify_goal_node.py` |
| `request.detect_ambiguity` | `adapters/langgraph/subgraphs/request_understanding/nodes/detect_ambiguity_node.py` → `detect_ambiguity_node()` | `adapters/langgraph/subgraphs/request_understanding/projections/detect_ambiguity_projection.py` → `project_detect_ambiguity_input()` | `request_understanding.detect_ambiguity` | `adapters/langgraph/subgraphs/request_understanding/routing/route_after_detect_ambiguity.py` → `route_after_detect_ambiguity()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/request_understanding/test_detect_ambiguity_node.py` |
| `request.finalize` | `adapters/langgraph/subgraphs/request_understanding/nodes/finalize_intent_node.py` → `finalize_intent_node()` | `adapters/langgraph/subgraphs/request_understanding/projections/finalize_intent_projection.py` → `project_finalize_intent_input()` | `request_understanding.finalize_intent → request_understanding.validate_intent` | `adapters/langgraph/subgraphs/request_understanding/routing/route_after_finalize_intent.py` → `route_after_finalize_intent()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/request_understanding/test_finalize_intent_node.py` |
| `route.determine_resources` | `adapters/langgraph/subgraphs/tool_routing/nodes/determine_io_resources_node.py` → `determine_io_resources_node()` | `adapters/langgraph/subgraphs/tool_routing/projections/determine_io_resources_projection.py` → `project_determine_io_resources_input()` | `tool_routing.determine_io_resources` | `adapters/langgraph/subgraphs/tool_routing/routing/route_after_determine_io_resources.py` → `route_after_determine_io_resources()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/tool_routing/test_determine_io_resources_node.py` |
| `route.bind_candidates` | `adapters/langgraph/subgraphs/tool_routing/nodes/bind_registry_candidates_node.py` → `bind_registry_candidates_node()` | `adapters/langgraph/subgraphs/tool_routing/projections/bind_registry_candidates_projection.py` → `project_bind_registry_candidates_input()` | `tool_routing.bind_registry_candidates` | `adapters/langgraph/subgraphs/tool_routing/routing/route_after_bind_registry_candidates.py` → `route_after_bind_registry_candidates()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/tool_routing/test_bind_registry_candidates_node.py` |
| `route.select_tool` | `adapters/langgraph/subgraphs/tool_routing/nodes/select_tool_if_needed_node.py` → `select_tool_if_needed_node()` | `adapters/langgraph/subgraphs/tool_routing/projections/select_tool_if_needed_projection.py` → `project_select_tool_if_needed_input()` | `tool_routing.select_tool_if_needed` | `adapters/langgraph/subgraphs/tool_routing/routing/route_after_select_tool_if_needed.py` → `route_after_select_tool_if_needed()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/tool_routing/test_select_tool_if_needed_node.py` |
| `route.finalize` | `adapters/langgraph/subgraphs/tool_routing/nodes/finalize_route_node.py` → `finalize_route_node()` | `adapters/langgraph/subgraphs/tool_routing/projections/finalize_route_projection.py` → `project_finalize_route_input()` | `tool_routing.finalize_route` | `adapters/langgraph/subgraphs/tool_routing/routing/route_after_finalize_route.py` → `route_after_finalize_route()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/tool_routing/test_finalize_route_node.py` |
| `route.validate` | `adapters/langgraph/subgraphs/tool_routing/nodes/validate_route_node.py` → `validate_route_node()` | `adapters/langgraph/subgraphs/tool_routing/projections/validate_route_projection.py` → `project_validate_route_input()` | `tool_routing.validate_route` | `adapters/langgraph/subgraphs/tool_routing/routing/route_after_validate_route.py` → `route_after_validate_route()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/tool_routing/test_validate_route_node.py` |
| `retrieval.plan_query` | `adapters/langgraph/subgraphs/retrieval/nodes/plan_query_node.py` → `plan_query_node()` | `adapters/langgraph/subgraphs/retrieval/projections/plan_query_projection.py` → `project_plan_query_input()` | `retrieval.plan_query` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_plan_query.py` → `route_after_plan_query()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_plan_query_node.py` |
| `retrieval.build_query` | `adapters/langgraph/subgraphs/retrieval/nodes/build_query_node.py` → `build_query_node()` | `adapters/langgraph/subgraphs/retrieval/projections/build_query_projection.py` → `project_build_query_input()` | `retrieval.build_query` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_build_query.py` → `route_after_build_query()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_build_query_node.py` |
| `retrieval.execute_read` | `adapters/langgraph/subgraphs/retrieval/nodes/execute_read_node.py` → `execute_read_node()` | `adapters/langgraph/subgraphs/retrieval/projections/execute_read_projection.py` → `project_execute_read_input()` | `retrieval.execute_read` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_execute_read.py` → `route_after_execute_read()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_execute_read_node.py` |
| `retrieval.normalize_segments` | `adapters/langgraph/subgraphs/retrieval/nodes/normalize_segments_node.py` → `normalize_segments_node()` | `adapters/langgraph/subgraphs/retrieval/projections/normalize_segments_projection.py` → `project_normalize_segments_input()` | `retrieval.normalize_segments` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_normalize_segments.py` → `route_after_normalize_segments()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_normalize_segments_node.py` |
| `retrieval.rag_retrieve` | `adapters/langgraph/subgraphs/retrieval/nodes/rag_retrieve_rerank_node.py` → `rag_retrieve_rerank_node()` | `adapters/langgraph/subgraphs/retrieval/projections/rag_retrieve_rerank_projection.py` → `project_rag_retrieve_rerank_input()` | `retrieval.rag_retrieve_rerank` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_rag_retrieve_rerank.py` → `route_after_rag_retrieve_rerank()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_rag_retrieve_rerank_node.py` |
| `retrieval.select_evidence` | `adapters/langgraph/subgraphs/retrieval/nodes/select_evidence_node.py` → `select_evidence_node()` | `adapters/langgraph/subgraphs/retrieval/projections/select_evidence_projection.py` → `project_select_evidence_input()` | `retrieval.select_evidence` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_select_evidence.py` → `route_after_select_evidence()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_select_evidence_node.py` |
| `retrieval.assess_sufficiency` | `adapters/langgraph/subgraphs/retrieval/nodes/assess_sufficiency_node.py` → `assess_sufficiency_node()` | `adapters/langgraph/subgraphs/retrieval/projections/assess_sufficiency_projection.py` → `project_assess_sufficiency_input()` | `retrieval.assess_sufficiency` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_assess_sufficiency.py` → `route_after_assess_sufficiency()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_assess_sufficiency_node.py` |
| `retrieval.finalize` | `adapters/langgraph/subgraphs/retrieval/nodes/finalize_retrieval_node.py` → `finalize_retrieval_node()` | `adapters/langgraph/subgraphs/retrieval/projections/finalize_retrieval_projection.py` → `project_finalize_retrieval_input()` | `retrieval.finalize_retrieval` | `adapters/langgraph/subgraphs/retrieval/routing/route_after_finalize_retrieval.py` → `route_after_finalize_retrieval()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/retrieval/test_finalize_retrieval_node.py` |
| `analysis.extract_facts` | `adapters/langgraph/subgraphs/work_analysis/nodes/extract_work_facts_node.py` → `extract_work_facts_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/extract_work_facts_projection.py` → `project_extract_work_facts_input()` | `work_analysis.extract_work_facts` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_extract_work_facts.py` → `route_after_extract_work_facts()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_extract_work_facts_node.py` |
| `analysis.resolve_entity_relations` | `adapters/langgraph/subgraphs/work_analysis/nodes/resolve_entity_relations_node.py` → `resolve_entity_relations_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/resolve_entity_relations_projection.py` → `project_resolve_entity_relations_input()` | `work_analysis.resolve_entity_relations` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_resolve_entity_relations.py` → `route_after_resolve_entity_relations()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_resolve_entity_relations_node.py` |
| `analysis.resolve_temporal_dependencies` | `adapters/langgraph/subgraphs/work_analysis/nodes/resolve_temporal_dependencies_node.py` → `resolve_temporal_dependencies_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/resolve_temporal_dependencies_projection.py` → `project_resolve_temporal_dependencies_input()` | `work_analysis.resolve_temporal_dependencies` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_resolve_temporal_dependencies.py` → `route_after_resolve_temporal_dependencies()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_resolve_temporal_dependencies_node.py` |
| `analysis.detect_duplicate_conflict_candidates` | `adapters/langgraph/subgraphs/work_analysis/nodes/detect_duplicate_conflict_candidates_node.py` → `detect_duplicate_conflict_candidates_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/detect_duplicate_conflict_candidates_projection.py` → `project_detect_duplicate_conflict_candidates_input()` | `work_analysis.detect_duplicate_conflict_candidates` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_detect_duplicate_conflict_candidates.py` → `route_after_detect_duplicate_conflict_candidates()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_detect_duplicate_conflict_candidates_node.py` |
| `analysis.validate_relations` | `adapters/langgraph/subgraphs/work_analysis/nodes/validate_relations_node.py` → `validate_relations_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/validate_relations_projection.py` → `project_validate_relations_input()` | `work_analysis.validate_relations` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_validate_relations.py` → `route_after_validate_relations()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_validate_relations_node.py` |
| `analysis.assess_information_gaps` | `adapters/langgraph/subgraphs/work_analysis/nodes/assess_information_gaps_node.py` → `assess_information_gaps_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/assess_information_gaps_projection.py` → `project_assess_information_gaps_input()` | `work_analysis.assess_information_gaps` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_assess_information_gaps.py` → `route_after_assess_information_gaps()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_assess_information_gaps_node.py` |
| `analysis.assess_operational_risks` | `adapters/langgraph/subgraphs/work_analysis/nodes/assess_operational_risks_node.py` → `assess_operational_risks_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/assess_operational_risks_projection.py` → `project_assess_operational_risks_input()` | `work_analysis.assess_operational_risks` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_assess_operational_risks.py` → `route_after_assess_operational_risks()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_assess_operational_risks_node.py` |
| `analysis.finalize` | `adapters/langgraph/subgraphs/work_analysis/nodes/assemble_work_analysis_node.py` → `assemble_work_analysis_node()` | `adapters/langgraph/subgraphs/work_analysis/projections/assemble_work_analysis_projection.py` → `project_assemble_work_analysis_input()` | `work_analysis.assemble_work_analysis → work_analysis.validate_work_analysis` | `adapters/langgraph/subgraphs/work_analysis/routing/route_after_assemble_work_analysis.py` → `route_after_assemble_work_analysis()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/work_analysis/test_assemble_work_analysis_node.py` |
| `planning.outline_answer` | `adapters/langgraph/subgraphs/planning/nodes/outline_answer_node.py` → `outline_answer_node()` | `adapters/langgraph/subgraphs/planning/projections/outline_answer_projection.py` → `project_outline_answer_input()` | `planning.outline_answer` | `adapters/langgraph/subgraphs/planning/routing/route_after_outline_answer.py` → `route_after_outline_answer()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/planning/test_outline_answer_node.py` |
| `planning.compose_answer` | `adapters/langgraph/subgraphs/planning/nodes/compose_answer_node.py` → `compose_answer_node()` | `adapters/langgraph/subgraphs/planning/projections/compose_answer_projection.py` → `project_compose_answer_input()` | `planning.compose_answer` | `adapters/langgraph/subgraphs/planning/routing/route_after_compose_answer.py` → `route_after_compose_answer()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/planning/test_compose_answer_node.py` |
| `planning.draft_action_objective_per_output_route` | `adapters/langgraph/subgraphs/planning/nodes/draft_action_objective_per_output_route_node.py` → `draft_action_objective_per_output_route_node()` | `adapters/langgraph/subgraphs/planning/projections/draft_action_objective_per_output_route_projection.py` → `project_draft_action_objective_per_output_route_input()` | `planning.draft_action_objective_per_output_route` | `adapters/langgraph/subgraphs/planning/routing/route_after_draft_action_objective_per_output_route.py` → `route_after_draft_action_objective_per_output_route()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/planning/test_draft_action_objective_per_output_route_node.py` |
| `planning.compose_arguments_per_output_route` | `adapters/langgraph/subgraphs/planning/nodes/compose_arguments_per_output_route_node.py` → `compose_arguments_per_output_route_node()` | `adapters/langgraph/subgraphs/planning/projections/compose_arguments_per_output_route_projection.py` → `project_compose_arguments_per_output_route_input()` | `planning.compose_arguments_per_output_route` | `adapters/langgraph/subgraphs/planning/routing/route_after_compose_arguments_per_output_route.py` → `route_after_compose_arguments_per_output_route()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/planning/test_compose_arguments_per_output_route_node.py` |
| `planning.derive_dependencies` | `adapters/langgraph/subgraphs/planning/nodes/build_dependencies_node.py` → `build_dependencies_node()` | `adapters/langgraph/subgraphs/planning/projections/build_dependencies_projection.py` → `project_build_dependencies_input()` | `planning.build_dependencies` | `adapters/langgraph/subgraphs/planning/routing/route_after_build_dependencies.py` → `route_after_build_dependencies()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/planning/test_build_dependencies_node.py` |
| `planning.assemble` | `adapters/langgraph/subgraphs/planning/nodes/assemble_plan_node.py` → `assemble_plan_node()` | `adapters/langgraph/subgraphs/planning/projections/assemble_plan_projection.py` → `project_assemble_plan_input()` | `planning.assemble_plan → planning.validate_plan` | `adapters/langgraph/subgraphs/planning/routing/route_after_assemble_plan.py` → `route_after_assemble_plan()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/planning/test_assemble_plan_node.py` |
| `review.inspect_goal_and_evidence` | `adapters/langgraph/subgraphs/review/nodes/inspect_goal_and_evidence_node.py` → `inspect_goal_and_evidence_node()` | `adapters/langgraph/subgraphs/review/projections/inspect_goal_and_evidence_projection.py` → `project_inspect_goal_and_evidence_input()` | `review.inspect_goal_and_evidence` | `adapters/langgraph/subgraphs/review/routing/route_after_inspect_goal_and_evidence.py` → `route_after_inspect_goal_and_evidence()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/review/test_inspect_goal_and_evidence_node.py` |
| `review.inspect_action_scope_route` | `adapters/langgraph/subgraphs/review/nodes/inspect_action_scope_and_route_node.py` → `inspect_action_scope_and_route_node()` | `adapters/langgraph/subgraphs/review/projections/inspect_action_scope_and_route_projection.py` → `project_inspect_action_scope_and_route_input()` | `review.inspect_action_scope_and_route` | `adapters/langgraph/subgraphs/review/routing/route_after_inspect_action_scope_and_route.py` → `route_after_inspect_action_scope_and_route()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/review/test_inspect_action_scope_and_route_node.py` |
| `review.inspect_constraints_policy` | `adapters/langgraph/subgraphs/review/nodes/inspect_constraints_and_policy_summary_node.py` → `inspect_constraints_and_policy_summary_node()` | `adapters/langgraph/subgraphs/review/projections/inspect_constraints_and_policy_summary_projection.py` → `project_inspect_constraints_and_policy_summary_input()` | `review.inspect_constraints_and_policy_summary` | `adapters/langgraph/subgraphs/review/routing/route_after_inspect_constraints_and_policy_summary.py` → `route_after_inspect_constraints_and_policy_summary()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/review/test_inspect_constraints_and_policy_summary_node.py` |
| `review.aggregate_findings` | `adapters/langgraph/subgraphs/review/nodes/aggregate_review_findings_node.py` → `aggregate_review_findings_node()` | `adapters/langgraph/subgraphs/review/projections/aggregate_review_findings_projection.py` → `project_aggregate_review_findings_input()` | `review.aggregate_review_findings → review.validate_review` | `adapters/langgraph/subgraphs/review/routing/route_after_aggregate_review_findings.py` → `route_after_aggregate_review_findings()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/review/test_aggregate_review_findings_node.py` |
| `review.recheck` | `adapters/langgraph/subgraphs/review/nodes/recheck_affected_dimensions_node.py` → `recheck_affected_dimensions_node()` | `adapters/langgraph/subgraphs/review/projections/recheck_affected_dimensions_projection.py` → `project_recheck_affected_dimensions_input()` | `review.recheck_affected_dimensions` | `adapters/langgraph/subgraphs/review/routing/route_after_recheck_affected_dimensions.py` → `route_after_recheck_affected_dimensions()` | YES · node-boundary only | `tests/architecture/langgraph/subgraphs/review/test_recheck_affected_dimensions_node.py` |

Supporting deterministic operations `tool_routing.resolve_policy_preconditions`, `retrieval.resolve_availability`, `planning.resolve_default_container`, `work_analysis.validate_work_analysis`, `planning.validate_plan`, `review.validate_review` remain operation-per-file Application capabilities but **do not create extra Runtime Node/Router/ResumeTarget entries** unless 06 explicitly versions the topology.

## Main control-stage terminal boundary

`RESPONSE_SYNTHESIS → TERMINAL_COMMIT → FINALIZE` is the only current terminal-output control chain. `RESPONSE_SYNTHESIS` creates `TerminalAssistantMessageInputV1/TerminalCommitIntentV1`; `TERMINAL_COMMIT` invokes exactly one existing terminal lifecycle handler; `FINALIZE` emits post-commit Trace/SSE only. These control nodes do not become semantic Agent owners.
