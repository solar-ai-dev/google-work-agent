# 01. Spec → Code Deterministic Mapping

**Normative detail of the current Repository Architecture Source.**

Every implementation task starts from semantic specification, never an existing filename.

```
SPEC TERM
→ CANONICAL TERM
→ SEMANTIC OWNER
→ LAYER
→ OPERATION
→ PATH
→ FILE
→ SYMBOL
→ TEST PATH
```

Examples:

```
BlockRun
→ run
→ Application
→ block
→ application/use_cases/run/block_run.py
→ BlockRunCommand / BlockRunResult / BlockRunHandler
→ tests/unit/application/use_cases/run/test_block_run.py
```

```
Work Analysis / validate relations / node
→ work_analysis
→ LangGraph adapter
→ adapters/langgraph/subgraphs/work_analysis/nodes/validate_relations_node.py
→ validate_relations_node()
```

```
Google Gmail Draft CREATE
→ google / gmail / drafts / create
→ adapters/connectors/google/gmail/drafts/create_draft.py
→ CreateDraftOperation
```

Before creating a file, semantically search every writer/caller/effect implementation. If a second live authority would result, stop with `SEMANTIC_AUTHORITY_COLLISION`.

## Canonical Required-Operation Manifest Contract

This mapping page is the repository-side source consumed by structural validation for required Application and Agent operations. The manifest is defined from canonical semantic contracts; implementation discovery must never generate or widen the required set.

For each Application capability mapping, record exactly:

```
SPEC TERM
CANONICAL TERM
SEMANTIC OWNER
LAYER = Application
OPERATION
PATH
FILE
SYMBOL
TEST PATH
```

For each Agent capability mapping, preserve the corresponding current Workflow/Prompt semantic responsibility identity and the same repository path/file/symbol/test mapping.

Closure validation compares the manifest as a closed set against production authority and test ownership. One missing mapping, one duplicate live implementation, or one unaccounted extra production authority fails the structural gate.

The canonical **core lifecycle/domain-facing Application owner set** requiring the Domain/Application manifest coverage is exact for the current snapshot:

```
conversation
message
run
plan
action
approval
claim
execution_attempt
verification
recovery
resource_ref
component_circuit
```

The canonical **Local API / system-boundary Application owner set** is exact for the current snapshot:

```
runtime_status
runtime_mode
connection
llm_credential
setting
backup
diagnostic_bundle
shutdown
attachment
resource
sse_event
trace_event
component_circuit
```

The canonical **current Application closed owner set** is the exact union of those two scoped sets; closed-set validators compare against this union and no other unqualified owner list:

```
conversation
message
run
plan
action
approval
claim
execution_attempt
verification
recovery
resource_ref
component_circuit
runtime_status
runtime_mode
connection
llm_credential
setting
backup
diagnostic_bundle
shutdown
attachment
resource
sse_event
trace_event
```

The canonical Agent owner set requiring manifest coverage is:

```
request_understanding
tool_routing
retrieval
work_analysis
planning
review
```

The exact operation rows are determined by the current concern-owning behavioral/state-transition contracts and this repository mapping. Current code presence or absence is never used to decide whether an operation is required.

## Canonical Capability Manifest

This section closes the current deterministic semantic-owner mapping. Behavioral semantics come from the current concern owners; this page only maps them through Repository Architecture. Current implementation paths are not authority.

### Ownership decision rule

```
behavioral concern owner
→ canonical command / atomic responsibility
→ primary semantic noun whose lifecycle/result is changed or authored
→ Repository Architecture singular owner package
→ operation-per-file
→ mirrored unit-test path
```

For compound commands, creation of a subordinate durable artifact does not move the command to that artifact's package when the authoritative command primarily changes another semantic owner's lifecycle. Therefore `ApproveAction` is owned by `action`: its authoritative transition is `Action PROPOSED|MODIFIED → APPROVED`; creation of the immutable Approval snapshot is a required durable effect. Approval-owned externally invokable lifecycle operations remain under `approval` (currently `ExpireApproval`). `RevokeApproval` is an internal Approval-row lifecycle effect performed within Action commands such as `ModifyAction`, `RejectAction`, or `CancelPendingAction`; it is not a separate Application use case.

### Application capability mapping

| Spec term | Canonical owner | Layer | Canonical operation(s) | Repository mapping | Test owner |
| --- | --- | --- | --- | --- | --- |
| Conversation | `conversation` | Application | `create_conversation`, `list_conversations`, `get_conversation_history` | `application/use_cases/conversation/<verb>_<object>.py` → `<Verb><Object>Command|Query / Result / Handler` | `tests/unit/application/use_cases/conversation/test_<verb>_<object>.py`  • 12 API/E2E contract |
| Message | `message` | Application/Repository projection | `list_conversation_messages` only as standalone Application Query; USER Message is required durable effect of `run.start_run`, final ASSISTANT Message is required durable effect of terminal Run/Recovery handler | `application/use_cases/message/list_conversation_messages.py`; writes use `MessageRepository` inside owning lifecycle UoW and do not create duplicate standalone writer authority | `tests/unit/application/use_cases/message/test_list_conversation_messages.py` + lifecycle UoW tests • 12 API/E2E |
| Run | `run` | Application | `start_run`, `get_run_snapshot`, `project_context_preview`, `adjust_context`, `project_error_actions`, `confirm_run`, `schedule_run_execution`, `redrive_workflow_handoffs`, `reconcile_retrieval_cache_restart`, `continue_cancel_resolution`, `project_external_llm_transfer_scope`, `start_analysis`, `begin_retrieval`, `begin_planning`, `request_confirmation`, `resume_confirmation`, `resume_safe_checkpoint`, `complete_answer_only_run`, `complete_read_only_run`, `build_terminal_message`, `begin_verification`, `complete_write_run`, `request_cancel`, `finalize_cancel`, `require_reauth`, `resume_after_reauth`, `block_run`, `guard_run_budget` | `application/use_cases/run/<verb>_<object>.py` | `tests/unit/application/use_cases/run/test_<verb>_<object>.py`  • 12 WF/E2E + State Transition Test Matrix |
| Plan | `plan` | Application | `publish_plan`, `publish_read_only_plan`, `record_review_result` | `application/use_cases/plan/publish_plan.py`, `application/use_cases/plan/publish_read_only_plan.py`, `application/use_cases/plan/record_review_result.py` | mirrored unit tests + 12 DOM/WF/E2E |
| Action | `action` | Application | `validate_action_arguments`, `evaluate_action_policy`, `approve_action`, `modify_action`, `reject_action`, `cancel_pending_action`, `prepare_write_retry`, `refresh_expired_action`, `claim_read_action`, `complete_read_action`, `finalize_read_action`, `fail_read_action` | `application/use_cases/action/<verb>_<object>.py`; specifically `application/use_cases/action/approve_action.py` → `ApproveActionCommand / ApproveActionResult / ApproveActionHandler` | `tests/unit/application/use_cases/action/test_<verb>_<object>.py`  • 12 DOM/E2E + State Transition Test Matrix |
| Approval | `approval` | Application | `expire_approval` | `application/use_cases/approval/expire_approval.py` | mirrored unit tests + 12 DOM/SEC/E2E |
| Claim | `claim` | Application | `claim_execution`, `build_claim_context` | `application/use_cases/claim/claim_execution.py` → `ClaimExecutionCommand / ClaimExecutionResult / ClaimExecutionHandler`; Claim guard includes owning Plan=current published `WAITING_APPROVAL` + legal parent Run authority, so `SUPERSEDED` child cannot Claim; `application/use_cases/claim/build_claim_context.py` → `BuildClaimContextQueryV1 / ClaimContextV2 / BuildClaimContextHandler` | `tests/unit/application/use_cases/claim/test_claim_execution.py` + `test_build_claim_context.py`  • 12 DOM/MCP/SEC |
| Execution Attempt | `execution_attempt` | Application | `begin_execution_attempt`, `abort_claimed_execution`, `reconcile_inflight_executions`, `dispatch_connector_write`, `classify_dispatch_result`, `store_success`, `mark_failed`, `mark_unknown_result`, `recover_existing_result`, `resolve_as_failed` | `application/use_cases/execution_attempt/<verb>_<object>.py` | mirrored unit tests + 12 DOM/MCP/E2E + State Transition Test Matrix |
| Verification | `verification` | Application | `verify_effect`, `store_verification` | `application/use_cases/verification/verify_effect.py` → `VerifyEffectQueryV1 / VerificationResultV1 / VerifyEffectHandler`; `application/use_cases/verification/store_verification.py` → `StoreVerificationCommand / StoreVerificationResult / StoreVerificationHandler` | `tests/unit/application/use_cases/verification/test_store_verification.py`  • 12 DOM/MCP/E2E |
| Recovery | `recovery` | Application | `lookup_unknown_result`, `project_recovery_options`, `require_recovery`, `resolve_recovery` | `application/use_cases/recovery/lookup_unknown_result.py` → `LookupUnknownResultQueryV1 / UnknownResultLookupResultV1 / LookupUnknownResultHandler`; `application/use_cases/recovery/project_recovery_options.py` → `ProjectRecoveryOptionsQueryV1 / ProjectRecoveryOptionsResultV1 / ProjectRecoveryOptionsHandler`; `application/use_cases/recovery/require_recovery.py`, `application/use_cases/recovery/resolve_recovery.py` | mirrored unit tests + `tests/unit/application/use_cases/recovery/test_project_recovery_options.py` + 12 REL/UI/E2E + State Transition Test Matrix |
| Resource Ref | `resource_ref` | Application | `resolve_resource_ref`, `persist_resource_ref` | `application/use_cases/resource_ref/resolve_resource_ref.py`, `application/use_cases/resource_ref/persist_resource_ref.py` | mirrored unit tests + 12 RET/CON/DB contract |
| Component Circuit | `component_circuit` | Application | `check_component_circuit`, `record_component_call_result` | `application/use_cases/component_circuit/<verb>_<object>.py` | `tests/unit/application/use_cases/component_circuit/test_<verb>_<object>.py` + 10/11/12 operational contract |

`application/tool_registry/` is a structural Application package, **not** an Application semantic owner. `SignedToolRegistry` therefore does not participate in the Application semantic-owner closed set or `application/use_cases/<owner>/...` grammar. Its single production authority, registration source, consumers, and test owner are closed separately by the **Runtime Registry closed mapping** below.

Execution/Verification external-I/O mapping is exact:

- `application/use_cases/action/validate_action_arguments.py` → `ValidateActionArgumentsQueryV1`, `ActionArgumentsSchemaValidationResultV1`, `ValidateActionArgumentsHandler`; Tool schema only, no policy/mutation.
- `application/use_cases/action/evaluate_action_policy.py` → `EvaluateActionPolicyQueryV1`, `ActionPolicyEvaluationResultV1`, `EvaluateActionPolicyHandler`; 01-B deterministic policy only, no Domain mutation/external I/O.
- `application/use_cases/claim/build_claim_context.py` → `BuildClaimContextQueryV1`, `ClaimContextV2`, `BuildClaimContextHandler`; committed Claim/Attempt와 final dispatch args integrity만 소유, no DB mutation/no external I/O.
- `application/use_cases/execution_attempt/begin_execution_attempt.py` → `BeginExecutionAttemptCommand`, `BeginExecutionAttemptResult`, `BeginExecutionAttemptHandler`; Attempt CLAIMED→EXECUTING + Audit only, external I/O 0.
- `application/use_cases/execution_attempt/abort_claimed_execution.py` → `AbortClaimedExecutionCommandV1`, `AbortClaimedExecutionResultV1`, `AbortClaimedExecutionHandler`; pre-dispatch Attempt CLAIMED→FAILED + Action EXECUTING→CANCELLED|FAILED in one UoW, external I/O 0; test `tests/unit/application/use_cases/execution_attempt/test_abort_claimed_execution.py`.
- `application/use_cases/execution_attempt/reconcile_inflight_executions.py` → `ExecutionReconciliationCandidateV1`, `ReconcileInflightExecutionsCommandV1`, `ReconcileInflightExecutionsResultV1`, `ReconcileInflightExecutionsHandler`; **state-changing startup-only batch Application use case**. Input is bounded `limit`, not an `execution_attempt_id`. Handler owns `ExecutionAttemptRepository.list_reconciliation_candidates(limit) -> list[ExecutionReconciliationCandidateV1]` and processes durable phases `POST_BEGIN_ORPHAN | UNKNOWN_RESULT_UNRESOLVED | EXECUTED_AWAITING_VERIFICATION | FAILED_AWAITING_CONTINUATION`. It applies/replays existing Domain commands with deterministic `system:execution-attempt-reconcile:<execution_attempt_id>[:phase]` identities, stages/reuses `...:verification` WorkflowHandoff when Verification is due, and returns `processed_count + progressed_count + has_more`. `api/app.py` may repeat the injected Handler based only on that Result; it never enumerates Repository rows directly. MCP/LLM readiness precedes this startup drain; live loop invocation=0; original Connector Write=0. Test `tests/unit/application/use_cases/execution_attempt/test_reconcile_inflight_executions.py` + startup/crash-phase integration.

- `application/use_cases/execution_attempt/classify_dispatch_result.py` → `ClassifyDispatchResultQueryV1`, `DispatchPersistenceDecisionV1`, `ClassifyDispatchResultHandler`; pure delivery-certainty classification only, external I/O/DB mutation 0.
- `application/use_cases/execution_attempt/dispatch_connector_write.py` → `DispatchConnectorWriteCommandV1`, `DispatchConnectorWriteResultV1`, `DispatchConnectorWriteHandler`; requires applied `BeginExecutionAttempt` for the same Attempt + current Attempt=`EXECUTING` + current ClaimContext binding; the Begin command owns the no-cancel pre-dispatch guard. Only then external `ConnectorWritePort`; failed precondition means external call 0; no DB mutation. Cancel applied after Begin is handled as in-flight result resolution, not a second dispatch gate.
- `application/use_cases/verification/verify_effect.py` → `VerifyEffectQueryV1`, `VerificationResultV1`, `VerifyEffectHandler`; external `ConnectorReadPort` only, no lifecycle mutation.
- `application/use_cases/recovery/lookup_unknown_result.py` → `LookupUnknownResultQueryV1`, `UnknownResultLookupResultV1`, `LookupUnknownResultHandler`; external lookup only, no Write.
- persistence/state mutation remains in `execution_attempt.store_*`, `verification.store_verification`, and `recovery.resolve_recovery` files.


### Run lifecycle closure

The following operations are explicitly Run lifecycle operations and remain under `run`, not under Agent roles or generic runtime/service modules:

```
RequestConfirmation  → run/request_confirmation
ResumeConfirmation   → run/resume_confirmation
RequireReauth        → run/require_reauth
ResumeAfterReauth    → run/resume_after_reauth
RequestCancel        → run/request_cancel
FinalizeCancel       → run/finalize_cancel
```

Recovery is a separate canonical semantic owner because the current Repository Architecture explicitly names `recovery` as a lifecycle owner and the Domain/Workflow contracts define a distinct `RECOVERY_REQUIRED` lifecycle with registered recovery resolution semantics:

```
RequireRecovery      → recovery/require_recovery
ResolveRecovery      → recovery/resolve_recovery
```

The Application handler may coordinate the corresponding Run state mutation, Command Receipt, persistence and workflow resume/suspend, but the repository capability owner is `recovery`.

### Agent capability mapping

Agent repository operations are derived from the current Workflow/Prompt atomic responsibilities **plus concern-owned deterministic supporting operations** required by the same owner. LLM responsibilities and deterministic operations remain separate files even when they share one owner. A supporting deterministic operation does not become a LangGraph Node merely because it has its own repository file. Current example: `retrieval.resolve_availability` is required by 05 Retrieval/12 Test, but 06 does not define it as an independent Runtime Node or Supervisor Edge.

```
request_understanding/
  identify_goal
  detect_ambiguity
  finalize_intent
  validate_intent

tool_routing/
  determine_io_resources
  resolve_policy_preconditions
  bind_registry_candidates
  select_tool_if_needed
  finalize_route
  validate_route

retrieval/
  plan_query
  build_query
  execute_read
  normalize_segments
  resolve_availability
  rag_retrieve_rerank
  select_evidence
  assess_sufficiency
  finalize_retrieval

work_analysis/
  extract_work_facts
  resolve_entity_relations
  resolve_temporal_dependencies
  detect_duplicate_conflict_candidates
  validate_relations
  assess_information_gaps
  assess_operational_risks
  assemble_work_analysis
  validate_work_analysis

planning/
  choose_answer_or_action_from_route
  resolve_default_container
  outline_answer
  compose_answer
  draft_action_objective_per_output_route
  compose_arguments_per_output_route
  build_dependencies
  assemble_plan
  validate_plan

review/
  inspect_goal_and_evidence
  inspect_action_scope_and_route
  inspect_constraints_and_policy_summary
  aggregate_review_findings
  validate_review
  recheck_affected_dimensions
```

Repository grammar for every item above:

```
application/agents/<role>/<verb>_<object>.py
→ <verb>_<object>()

tests/unit/application/agents/<role>/test_<verb>_<object>.py
```

For responsibilities that **06 explicitly exposes as LangGraph Nodes**, LangGraph is adapter-only:

```
adapters/langgraph/subgraphs/<role>/nodes/<verb>_<object>_node.py
→ typed projection
→ application semantic operation
→ typed owner-field patch
→ optional WorkflowSignal
```

Supporting deterministic operations that 06 keeps inside an existing node/stage keep their canonical Application operation file/test but do **not** require a second LangGraph Node, Router, Edge, or resume target. Current examples are `retrieval.resolve_availability`, `work_analysis.validate_work_analysis` inside runtime `analysis.finalize`, `planning.validate_plan` inside runtime `planning.assemble`, and `review.validate_review` inside runtime `review.aggregate_findings`.

### Runtime Node ID → Application operation closed mapping

06 owns Runtime Node IDs; this page owns their repository operation realization. **Every current Runtime Node ID is listed here**. A row may call multiple deterministic operations only when 06 explicitly says they execute inside one runtime node.

| Runtime Node ID / stage | Canonical Application operation(s) | Repository file(s) |
| --- | --- | --- |
| `request.identify_goal` | `request_understanding.identify_goal` | `application/agents/request_understanding/identify_goal.py` |
| `request.detect_ambiguity` | `request_understanding.detect_ambiguity` | `application/agents/request_understanding/detect_ambiguity.py` |
| `request.finalize` | `request_understanding.finalize_intent` → `request_understanding.validate_intent` | `finalize_intent.py` → `validate_intent.py` |
| `route.determine_resources` | `tool_routing.determine_io_resources` | `application/agents/tool_routing/determine_io_resources.py` |
| Tool Route precondition stage | `tool_routing.resolve_policy_preconditions` | `application/agents/tool_routing/resolve_policy_preconditions.py` |
| `route.bind_candidates` | `tool_routing.bind_registry_candidates` | `application/agents/tool_routing/bind_registry_candidates.py` |
| `route.select_tool` | `tool_routing.select_tool_if_needed` | `application/agents/tool_routing/select_tool_if_needed.py` |
| `route.finalize` | `tool_routing.finalize_route` | `application/agents/tool_routing/finalize_route.py` |
| `route.validate` | `tool_routing.validate_route` | `application/agents/tool_routing/validate_route.py` |
| `retrieval.plan_query` | `retrieval.plan_query` | `application/agents/retrieval/plan_query.py` |
| `retrieval.build_query` | `retrieval.build_query` | `application/agents/retrieval/build_query.py` |
| `retrieval.execute_read` | `retrieval.execute_read` | `application/agents/retrieval/execute_read.py` |
| `retrieval.normalize_segments` | `retrieval.normalize_segments` | `application/agents/retrieval/normalize_segments.py` |
| Retrieval availability stage | `retrieval.resolve_availability` | `application/agents/retrieval/resolve_availability.py` |
| `retrieval.rag_retrieve` | `retrieval.rag_retrieve_rerank` | `application/agents/retrieval/rag_retrieve_rerank.py` |
| `retrieval.select_evidence` | `retrieval.select_evidence` | `application/agents/retrieval/select_evidence.py` |
| `retrieval.assess_sufficiency` | `retrieval.assess_sufficiency` | `application/agents/retrieval/assess_sufficiency.py` |
| `retrieval.finalize` | `retrieval.finalize_retrieval` | `application/agents/retrieval/finalize_retrieval.py` |
| `analysis.extract_facts` | `work_analysis.extract_work_facts` | `application/agents/work_analysis/extract_work_facts.py` |
| `analysis.resolve_entity_relations` | `work_analysis.resolve_entity_relations` | `application/agents/work_analysis/resolve_entity_relations.py` |
| `analysis.resolve_temporal_dependencies` | `work_analysis.resolve_temporal_dependencies` | `application/agents/work_analysis/resolve_temporal_dependencies.py` |
| `analysis.detect_duplicate_conflict_candidates` | `work_analysis.detect_duplicate_conflict_candidates` | `application/agents/work_analysis/detect_duplicate_conflict_candidates.py` |
| `analysis.validate_relations` | `work_analysis.validate_relations` | `application/agents/work_analysis/validate_relations.py` |
| `analysis.assess_information_gaps` | `work_analysis.assess_information_gaps` | `application/agents/work_analysis/assess_information_gaps.py` |
| `analysis.assess_operational_risks` | `work_analysis.assess_operational_risks` | `application/agents/work_analysis/assess_operational_risks.py` |
| `analysis.finalize` | `work_analysis.assemble_work_analysis` → `work_analysis.validate_work_analysis` | `application/agents/work_analysis/assemble_work_analysis.py` → `application/agents/work_analysis/validate_work_analysis.py` |
| Planning entry stage | `planning.choose_answer_or_action_from_route` | `application/agents/planning/choose_answer_or_action_from_route.py` |
| `planning.outline_answer` | `planning.outline_answer` | `application/agents/planning/outline_answer.py` |
| `planning.compose_answer` | `planning.compose_answer` | `application/agents/planning/compose_answer.py` |
| `planning.draft_action_objective_per_output_route` | same canonical operation | `application/agents/planning/draft_action_objective_per_output_route.py` |
| Planning pre-bind stage | `planning.resolve_default_container` | `application/agents/planning/resolve_default_container.py` |
| `planning.compose_arguments_per_output_route` | same canonical operation | `application/agents/planning/compose_arguments_per_output_route.py` |
| `planning.derive_dependencies` | `planning.build_dependencies` | `application/agents/planning/build_dependencies.py` |
| `planning.assemble` | `planning.assemble_plan` → `planning.validate_plan` | `application/agents/planning/assemble_plan.py` → `application/agents/planning/validate_plan.py` |
| `review.inspect_goal_and_evidence` | same canonical operation | `application/agents/review/inspect_goal_and_evidence.py` |
| `review.inspect_action_scope_route` | `review.inspect_action_scope_and_route` | `application/agents/review/inspect_action_scope_and_route.py` |
| `review.inspect_constraints_policy` | `review.inspect_constraints_and_policy_summary` | `application/agents/review/inspect_constraints_and_policy_summary.py` |
| `review.aggregate_findings` | `review.aggregate_review_findings` → `review.validate_review` | `application/agents/review/aggregate_review_findings.py` → `application/agents/review/validate_review.py` |
| `review.recheck` | `review.recheck_affected_dimensions` | `application/agents/review/recheck_affected_dimensions.py` |

All paths in this table are exact canonical production paths.

### Authority and contradiction closure

- Source semantic authority: 01-A Functional / 01-B Policy / 04 Domain + Domain State Transition Contract / 05 Retrieval / 06 Workflow / 07 Interface / 15 Prompt·Failure, by concern.
- Repository naming and placement authority: the current Repository Architecture and its normative subordinate pages.
- Current implementation path is not used as evidence.
- `action/approve_action` is canonical. `approval/approve_action` is non-canonical because Approval creation is a subordinate durable effect of the Action lifecycle command; it would split one command authority across two semantic owner packages.
- `planning.compose_dependencies` is not canonical. Dependency construction is deterministic `planning.build_dependencies`.
- Run confirmation and reauthentication operations do not belong to a generic `runtime`/`service` owner.
- Recovery lifecycle does not collapse into `run` or generic execution modules; it uses the explicit `recovery` owner.

Within this ZIP snapshot, the resolvable concern-owning Project Sources do not assign the same mapped capability to two different semantic owners after applying the Source Guide concern dispatch and Repository Architecture rules. The current frozen snapshot includes all 21 canonical design sources; implementation artifacts such as migrations are verified against those sources and are not missing semantic owners.

## Local API Application Mapping Closure

The Local API Application gap is closed here from the current 07 Interface / 08 Sequence / 09 Security / 10 Infrastructure semantics. These rows map existing behavior to repository ownership; they do not redefine those behavioral contracts.

### Explicit non-Application transport/infrastructure endpoints

These endpoints are closed without turning them into business Application use cases:

| Endpoint | Route file | Exact owner file | Single responsibility |
| --- | --- | --- | --- |
| `GET /health/live`, `GET /health/ready` | `api/routes/health.py` | `launcher/readiness.py` | expose process liveness/readiness projection only |
| `POST /api/v1/session/bootstrap` | `api/routes/session.py` | `api/security/bootstrap_session.py` | consume one-time Bootstrap Secret, compare `frontend_api_contract_version` with server `api_contract_version`, and establish command/SSE-admitted Local Session only when compatible |

`launcher/bootstrap_secret.py` creates/rotates the one-time Bootstrap Secret and Service Instance binding at process start. `api/dependencies/local_session.py` validates an already-established Local Session for protected routes; it never establishes one. `api/security/bootstrap_session.py` consumes the bootstrap secret, issues the `HttpOnly` Local Session cookie, and records the in-memory session identity defined by 09/10. None of these files may mutate Domain workflow state or become a shortcut to business semantics.

All protected product operations below follow:

```
FastAPI Route
→ Application Handler
→ Domain and/or abstract Port
→ Adapter
```

### Core Local API route → file → Application mapping

API route files own HTTP transport only. Schema modules own versioned wire serialization only. Application handlers own orchestration.

| Endpoint | Route file | Schema module | Application operation |
| --- | --- | --- | --- |
| `GET /api/v1/conversations` | `api/routes/conversations.py` | `api/schemas/conversations/list_conversations.py` | `conversation.list_conversations` |
| `POST /api/v1/conversations` | `api/routes/conversations.py` | `api/schemas/conversations/create_conversation.py` | `conversation.create_conversation` |
| `GET /api/v1/conversations/{conversation_id}/history` | `api/routes/conversations.py` | `api/schemas/conversations/get_conversation_history.py` | `conversation.get_conversation_history` |
| `POST /api/v1/runs` | `api/routes/runs.py` | `api/schemas/runs/start_run.py` | `run.start_run` (resolve handles → preallocate server Run/Message/Workflow IDs → same-UoW Run/User Message/WorkflowBinding/START Handoff → post-commit `run.schedule_run_execution(handoff_id)`) |
| `GET /api/v1/runs/{run_id}` | `api/routes/runs.py` | `api/schemas/runs/get_run_snapshot.py` | `run.get_run_snapshot` |
| `POST /api/v1/runs/{run_id}/context-adjustments` | `api/routes/runs.py` | `api/schemas/runs/adjust_context.py` | `run.adjust_context` |
| `POST /api/v1/runs/{run_id}/confirm` | `api/routes/runs.py` | `api/schemas/runs/confirm_run.py` | `run.confirm_run` → validation/projection → `run.resume_confirmation` + same-UoW `WorkflowHandoffV1(PENDING)` → post-commit `run.schedule_run_execution(handoff_id)` |
| `POST /api/v1/runs/{run_id}/cancel` | `api/routes/runs.py` | `api/schemas/runs/cancel_run.py` | `run.request_cancel` |
| `POST /api/v1/runs/{run_id}/resume` | `api/routes/runs.py` | `api/schemas/runs/resume_run.py` | discriminated dispatch to `run.resume_after_reauth | run.resume_safe_checkpoint | recovery.resolve_recovery(RECHECK)` |
| `POST /api/v1/runs/{run_id}/resolve-recovery` | `api/routes/runs.py` | `api/schemas/runs/resolve_recovery.py` | `recovery.resolve_recovery` |
| `GET /api/v1/runs/{run_id}/events` | `api/routes/runs.py` | `api/schemas/runs/list_run_events.py` | `sse_event.list_run_events` |
| `POST /api/v1/actions/{action_id}/approve` | `api/routes/actions.py` | `api/schemas/actions/approve_action.py` | `action.approve_action` |
| `POST /api/v1/actions/{action_id}/modify` | `api/routes/actions.py` | `api/schemas/actions/modify_action.py` | `action.modify_action` |
| `POST /api/v1/actions/{action_id}/reject` | `api/routes/actions.py` | `api/schemas/actions/reject_action.py` | `action.reject_action` |
| `POST /api/v1/actions/{action_id}/prepare-retry` | `api/routes/actions.py` | `api/schemas/actions/prepare_retry.py` | `action.prepare_write_retry` |

Route modules never import Domain transitions, SQLite repositories, concrete adapters, Provider SDKs, or LangGraph routing.

Recovery shared wire identity is closed separately to prevent Snapshot/SSE/command schemas from duplicating reason→resolution logic:

```text
api/schemas/runs/recovery.py
→ RecoveryResolutionKindV1
→ RunRecoveryTargetV1 / ActionRecoveryTargetV1 / RecoveryTargetV1
→ RecoveryUiProjectionV1
```

`api/schemas/runs/get_run_snapshot.py`, `api/schemas/runs/list_run_events.py`, and `api/schemas/runs/resolve_recovery.py` import these types. The only derivation authority is `application/use_cases/recovery/project_recovery_options.py → ProjectRecoveryOptionsHandler`; it reads persisted `RecoveryContextV1` + State Contract matrix and returns `ProjectRecoveryOptionsResultV1`. API schemas serialize that result; API routes/Frontend do not maintain a second reason→resolution table.

### Run query / safe resume additions

```
GET /api/v1/runs/{run_id}
→ run.get_run_snapshot
→ application/use_cases/run/get_run_snapshot.py
→ GetRunSnapshotQuery / GetRunSnapshotResult / GetRunSnapshotHandler
→ includes ContextPreviewResponseV1 from run.project_context_preview; adjustment controls are server-projected and default read-only
→ tests/unit/application/use_cases/run/test_get_run_snapshot.py

internal snapshot projection
→ run.project_context_preview
→ application/use_cases/run/project_context_preview.py
→ ProjectContextPreviewQueryV1 / ProjectContextPreviewResultV1 / ProjectContextPreviewHandler
→ reads current selected Evidence/ResourceRef only; Domain/Workflow mutation 0
→ tests/unit/application/use_cases/run/test_project_context_preview.py

POST /api/v1/runs/{run_id}/context-adjustments
→ run.adjust_context
→ application/use_cases/run/adjust_context.py
→ AdjustContextCommandV1 / AdjustContextResultV1 / AdjustContextHandler
→ validates expected Run/Retrieval revision + current Preview membership + WAITING_APPROVAL/no-approval/no-in-flight guard
→ invokes existing run.begin_planning with USER_CONTEXT_ADJUSTMENT branch; same UoW revokes old Plan ACTIVE Approvals, then current Plan SUPERSEDED; old child authority becomes history-only
→ normalizes ContextAdjustmentV1 and stages durable handoff `MAIN_CONTROL:RETRIEVAL_ENTRY`; EXCLUDE and RETRIEVE_MORE are discriminated by typed control payload; no new lifecycle command
→ tests/unit/application/use_cases/run/test_adjust_context.py

internal external-LLM disclosure projection
→ run.project_external_llm_transfer_scope
→ application/use_cases/run/project_external_llm_transfer_scope.py
→ ProjectExternalLlmTransferScopeQueryV1 / ExternalLlmTransferScopeV1 / ProjectExternalLlmTransferScopeHandler
→ exact current inference input projection source/data-class categories; publish scope hash/revision via CheckpointPort before external provider call; raw source text/secret 0
→ tests/unit/application/use_cases/run/test_project_external_llm_transfer_scope.py

internal error-action projection
→ run.project_error_actions
→ application/use_cases/run/project_error_actions.py
→ ProjectErrorActionsQueryV1 / ProjectErrorActionsResultV1 / ProjectErrorActionsHandler
→ durable Run/Action/latest delivery fact + State Contract startup gate → ErrorUiProjectionV1
→ `UNKNOWN_RESULT` never emits PREPARE_RETRY; navigation actions own no Domain mutation
→ tests/unit/application/use_cases/run/test_project_error_actions.py

POST /api/v1/runs/{run_id}/resume + SAFE_CHECKPOINT_RESUME
→ run.resume_safe_checkpoint
→ application/use_cases/run/resume_safe_checkpoint.py
→ ResumeSafeCheckpointCommand / ResumeSafeCheckpointResult / ResumeSafeCheckpointHandler
→ tests/unit/application/use_cases/run/test_resume_safe_checkpoint.py
```

`SAFE_CHECKPOINT_RESUME` validates the same `run_id + langgraph_thread_id + checkpoint`, Domain/Checkpoint consistency, registered resume target, active graph version, **and the State Contract startup source-state matrix** through the Application use-case boundary. It does not invent a Domain transition. `ResumeSafeCheckpointHandler` must return `RESUME_NOT_ALLOWED` with Graph invocation 0 for every matrix-FORBIDDEN status; callers may not bypass this by invoking LangGraph directly. The same HTTP route dispatches `REAUTH_COMPLETED` to `run.resume_after_reauth` and `RECOVERY_RECHECK` to `recovery.resolve_recovery`; the route itself is not a fourth workflow authority.

### Local API boundary capability manifest

| Spec/API capability | Owner | Operation | Repository mapping | Symbol | Test mapping |
| --- | --- | --- | --- | --- | --- |
| `GET /api/v1/runtime` protected Runtime Detail | `runtime_status` | `get_runtime_status` | `application/use_cases/runtime_status/get_runtime_status.py` | `GetRuntimeStatusQuery / GetRuntimeStatusResult / GetRuntimeStatusHandler` | `tests/unit/application/use_cases/runtime_status/test_get_runtime_status.py` |
| `POST /api/v1/runtime/mode` | `runtime_mode` | `update_runtime_mode` | `application/use_cases/runtime_mode/update_runtime_mode.py` | `UpdateRuntimeModeCommand / UpdateRuntimeModeResult / UpdateRuntimeModeHandler` | `tests/unit/application/use_cases/runtime_mode/test_update_runtime_mode.py` |
| `POST /api/v1/connections/google/start` | `connection` | `start_authorization` | `application/use_cases/connection/start_authorization.py` | `StartAuthorizationCommand / StartAuthorizationResult / StartAuthorizationHandler` | `tests/unit/application/use_cases/connection/test_start_authorization.py` |
| `GET /api/v1/connections/google/status` | `connection` | `get_connection_status` | `application/use_cases/connection/get_connection_status.py` | `GetConnectionStatusQuery / GetConnectionStatusResult / GetConnectionStatusHandler` | `tests/unit/application/use_cases/connection/test_get_connection_status.py` |
| `POST /api/v1/connections/google/disconnect` | `connection` | `revoke_connection` | `application/use_cases/connection/revoke_connection.py` | `RevokeConnectionCommand / RevokeConnectionResult / RevokeConnectionHandler` | `tests/unit/application/use_cases/connection/test_revoke_connection.py` |
| `PUT /api/v1/credentials/llm/{provider}` | `llm_credential` | `store_llm_credential` | `application/use_cases/llm_credential/store_llm_credential.py` | `StoreLlmCredentialCommand / StoreLlmCredentialResult / StoreLlmCredentialHandler` | `tests/unit/application/use_cases/llm_credential/test_store_llm_credential.py` |
| `DELETE /api/v1/credentials/llm/{provider}` | `llm_credential` | `delete_llm_credential` | `application/use_cases/llm_credential/delete_llm_credential.py` | `DeleteLlmCredentialCommand / DeleteLlmCredentialResult / DeleteLlmCredentialHandler` | `tests/unit/application/use_cases/llm_credential/test_delete_llm_credential.py` |
| `GET /api/v1/credentials/llm/{provider}` | `llm_credential` | `get_llm_credential_status` | `application/use_cases/llm_credential/get_llm_credential_status.py` | `GetLlmCredentialStatusQuery / LlmCredentialStatusV1 / GetLlmCredentialStatusHandler` | `tests/unit/application/use_cases/llm_credential/test_get_llm_credential_status.py` |
| `GET /api/v1/settings` | `setting` | `get_settings` | `application/use_cases/setting/get_settings.py` | `GetSettingsQuery / GetSettingsResult / GetSettingsHandler` | `tests/unit/application/use_cases/setting/test_get_settings.py` |
| `PUT /api/v1/settings` | `setting` | `update_settings` | `application/use_cases/setting/update_settings.py` | `UpdateSettingsCommand / UpdateSettingsResult / UpdateSettingsHandler` | `tests/unit/application/use_cases/setting/test_update_settings.py` |
| `GET /api/v1/backups` | `backup` | `list_backups` | `application/use_cases/backup/list_backups.py` | `ListBackupsQuery / BackupListResponseV1 / ListBackupsHandler` | `tests/unit/application/use_cases/backup/test_list_backups.py` |
| `POST /api/v1/backups` | `backup` | `create_backup` | `application/use_cases/backup/create_backup.py` | `CreateBackupCommand / CreateBackupResult / CreateBackupHandler` | `tests/unit/application/use_cases/backup/test_create_backup.py` |
| `POST /api/v1/restore` | `backup` | `restore_backup` | `application/use_cases/backup/restore_backup.py` | `RestoreBackupCommand / RestoreBackupResult / RestoreBackupHandler` | `tests/unit/application/use_cases/backup/test_restore_backup.py` |
| `POST /api/v1/diagnostics/bundles` | `diagnostic_bundle` | `create_diagnostic_bundle` | `application/use_cases/diagnostic_bundle/create_diagnostic_bundle.py` | `CreateDiagnosticBundleCommand / CreateDiagnosticBundleResult / CreateDiagnosticBundleHandler` | `tests/unit/application/use_cases/diagnostic_bundle/test_create_diagnostic_bundle.py` |
| `POST /api/v1/control/shutdown` | `shutdown` | `request_shutdown` | `application/use_cases/shutdown/request_shutdown.py` | `RequestShutdownCommand / RequestShutdownResult / RequestShutdownHandler` | `tests/unit/application/use_cases/shutdown/test_request_shutdown.py` |
| `GET /api/v1/gmail/messages/{message_id}/attachments/{attachment_id}` | `attachment` | `get_attachment` | `application/use_cases/attachment/get_attachment.py` | `GetAttachmentQuery / GetAttachmentResult / GetAttachmentHandler` | `tests/unit/application/use_cases/attachment/test_get_attachment.py` |
| `POST /api/v1/attachments/stage` | `attachment` | `create_staged_attachment` | `application/use_cases/attachment/create_staged_attachment.py` | `CreateStagedAttachmentCommand / CreateStagedAttachmentResult / CreateStagedAttachmentHandler` | `tests/unit/application/use_cases/attachment/test_create_staged_attachment.py` |
| `GET /api/v1/resources/task-lists` | `resource` | `list_task_lists` | `application/use_cases/resource/list_task_lists.py` | `ListTaskListsQuery / TaskListContainerListResponseV1 / ListTaskListsHandler` | `tests/unit/application/use_cases/resource/test_list_task_lists.py` |
| `GET /api/v1/resources/calendars` | `resource` | `list_calendars` | `application/use_cases/resource/list_calendars.py` | `ListCalendarsQuery / CalendarContainerListResponseV1 / ListCalendarsHandler` | `tests/unit/application/use_cases/resource/test_list_calendars.py` |
| `GET /api/v1/resources/{source}` (`gmail|tasks|calendar`) | `resource` | `list_resources` | `application/use_cases/resource/list_resources.py` | `ListResourcesQuery / ListResourcesResult / ListResourcesHandler` | `tests/unit/application/use_cases/resource/test_list_resources.py` |
| `GET /api/v1/resources/gmail/count` | `resource` | `get_resource_count` | `application/use_cases/resource/get_resource_count.py` | `GetResourceCountQuery / GetResourceCountResult / GetResourceCountHandler` | `tests/unit/application/use_cases/resource/test_get_resource_count.py` |
| `GET /api/v1/resources/gmail/{resource_id}` UI detail | `resource` | `get_resource_detail` | `application/use_cases/resource/get_resource_detail.py` | `GetResourceDetailQuery / GetResourceDetailResult / GetResourceDetailHandler` | `tests/unit/application/use_cases/resource/test_get_resource_detail.py` |
| `GET /api/v1/resources/tasks/{resource_id}` UI detail | `resource` | `get_task_resource_detail` | `application/use_cases/resource/get_task_resource_detail.py` | `GetTaskResourceDetailQuery / GetTaskResourceDetailResult / GetTaskResourceDetailHandler` | `tests/unit/application/use_cases/resource/test_get_task_resource_detail.py` |
| `GET /api/v1/resources/calendar/{resource_id}` UI detail | `resource` | `get_calendar_resource_detail` | `application/use_cases/resource/get_calendar_resource_detail.py` | `GetCalendarResourceDetailQuery / GetCalendarResourceDetailResult / GetCalendarResourceDetailHandler` | `tests/unit/application/use_cases/resource/test_get_calendar_resource_detail.py` |
| `GET /api/v1/runs/{run_id}/events` | `sse_event` | `list_run_events` | `application/use_cases/sse_event/list_run_events.py` | `ListRunEventsQuery / ListRunEventsResult / ListRunEventsHandler` | `tests/unit/application/use_cases/sse_event/test_list_run_events.py` |
| internal SSE projection | `sse_event` | `project_run_event` | `application/use_cases/sse_event/project_run_event.py` | `ProjectRunEventCommand / RunSseEventV1 / ProjectRunEventHandler` | `tests/unit/application/use_cases/sse_event/test_project_run_event.py` |
| diagnostic Trace append | `trace_event` | `emit_trace_event` | `application/use_cases/trace_event/emit_trace_event.py` | `EmitTraceEventCommand / EmitTraceEventResult / EmitTraceEventHandler` | `tests/unit/application/use_cases/trace_event/test_emit_trace_event.py` |

`runtime_mode.update_runtime_mode`는 `OperationalCommandReplayPort` adjudication 뒤 `RuntimeModePort`만 mutate한다. P0 concrete binding은 `ports/system/runtime_mode_port.py → RuntimeModePort` / `adapters/system/process_runtime_mode.py → ProcessRuntimeModeAdapter`이며 composition이 persisted `SettingsViewV1.preferred_llm_mode`를 startup initial value로 주입한다. `tests/unit/adapters/system/test_process_runtime_mode.py`가 reconcile/restart semantics를 검증한다. `runtime_status.get_runtime_status`는 같은 Port의 current requested mode를 읽어 bounded `RuntimeModeStatusV1`을 구성한다. Settings, Application module global, `StructuredInferenceRuntimeRouter` private mutable field는 second authority가 아니다.

`setting.get_settings/update_settings`는 10 §10.3의 exact non-secret field set을 `07 SettingsViewV1/SettingsPatchV1`로만 노출한다. Calendar policy fields(`timezone`, `working_day_start_local`, `working_day_end_local`, `include_weekends`, `calendar_buffer_minutes`)와 persisted defaults(`preferred_llm_mode`, `external_llm_consent`, `retention_days`, `theme`, `panel_preferences`)를 별도 owner/schema로 복제하지 않는다. P0 `retention_days` validation은 01-B의 **1..30**을 그대로 소비하며 Repository/Application이 별도 상한을 발명하지 않는다. P0 Local API에는 log-delete/full-app-reset endpoint가 없다; complete delete는 09/14 Uninstall boundary다.

Resource selection identity support is not a new Registry/Port: `application/use_cases/resource/issue_selection_handle.py → IssueSelectionHandle` is called by `list_resources`; `application/use_cases/resource/resolve_selection_handle.py → ResolveSelectionHandle` is called by `run.start_run` and Task/Calendar detail queries. Both consume the 07 `ResourceSelectionHandlePayloadV1` authenticated envelope contract. No `LocalResourceIndex`, generic Resource Registry, or Adapter-side identity lookup may be introduced.

`GET /api/v1/resources/tasks/{resource_id}`와 `GET /api/v1/resources/calendar/{resource_id}`의 request schema는 각각 path `resource_id` + required opaque `selection_handle` query parameter를 사용한다. Route는 handle을 직접 해석하지 않고 `resource.resolve_selection_handle`을 호출하며 path/source/parent binding mismatch는 Connector call 전에 fail closed한다.

### Provider-neutral Application rule

The P0 wire route may contain `google`, but Application ownership is connector-neutral. `POST /api/v1/connections/google/start` fixes the P0 `connector_id=google_workspace` and calls `connection.start_authorization`; it does not create a provider-specific `application/use_cases/google/**` authority. Loopback callback completion remains inside the Connector MCP Credential Provider. Core/UI observes completion only through existing `connection.get_connection_status` / `GET /api/v1/connections/google/status`; no reverse MCP→Application completion event package or FastAPI callback route is canonical. Resource browse/detail and attachment read similarly cross the connector boundary through abstract Connector Ports.


### SSE replay buffer exact mapping

| Responsibility | Canonical file | Symbol | Single responsibility |
| --- | --- | --- | --- |
| SSE replay buffer port | `ports/system/sse_event_buffer_port.py` | `SseEventBufferPort` | bounded append/list-after/clear only |
| P0 memory buffer adapter | `adapters/system/memory/sse_event_buffer.py` | `InMemorySseEventBuffer` | process-local bounded replay realization only |
| SSE event projection | `application/use_cases/sse_event/project_run_event.py` | `ProjectRunEventHandler` | typed fact → `RunSseEventV1` + buffer append only |
| SSE replay query | `application/use_cases/sse_event/list_run_events.py` | `ListRunEventsHandler` | buffer read/cursor-expired result only |

### Trace / Audit / UnitOfWork exact mapping

| Responsibility | Canonical file | Symbol | Single responsibility |
| --- | --- | --- | --- |
| transaction boundary | `ports/persistence/unit_of_work.py` | `UnitOfWork` | abstract begin/commit/rollback boundary only |
| SQLite transaction boundary | `adapters/persistence/sqlite/unit_of_work.py` | `SqliteUnitOfWork` | SQLite transaction realization only |
| Trace persistence port | `ports/persistence/trace_event_repository.py` | `TraceEventRepository` | persist/query/purge 11-owned TraceEvent only |
| Trace SQLite adapter | `adapters/persistence/sqlite/repositories/trace_event_repository.py` | `SqliteTraceEventRepository` | SQLite TraceEvent persistence only |
| Audit persistence port | `ports/persistence/audit_event_repository.py` | `AuditEventRepository` | persist/query/purge 11-owned AuditEvent only |
| Audit SQLite adapter | `adapters/persistence/sqlite/repositories/audit_event_repository.py` | `SqliteAuditEventRepository` | SQLite AuditEvent persistence only |

Required lifecycle Audit is not a post-commit best-effort callback. The owning lifecycle handler stages AuditEvent with CommandReceipt and Domain mutations and commits them in one short `UnitOfWork`. Trace is diagnostic and may be independently committed.

`run.start_run` has one additional transaction participant required by the 04/07 crash-gap contract: `SqliteUnitOfWork` binds the Run/Message repositories, the SQLite `CheckpointPort.create_workflow_binding(...)` realization, and `WorkflowHandoffRepository.stage_pending(...)` to the **same connection/transaction**. WorkflowBinding or START handoff must not commit independently of the Run. After that UoW commits, `run.schedule_run_execution(handoff_id)` is the only execution submission path.

### Closure rule

The combined Domain/Application manifest plus this Local API boundary manifest must equal the **current Application closed owner set** declared above exactly. Structural Application packages such as `application/tool_registry/`, `application/prompt_runtime/`, and `application/maintenance/` are excluded from that semantic-owner comparison and are closed by their dedicated structural manifests. The scoped core list and scoped boundary list are subsets only; neither is an alternative unqualified closed set. No repository-mapping design blocker remains in this mapping. A missing implementation later is an implementation gap; it is not permission for `FastAPI Route → SQL`, `FastAPI Route → Domain transition`, or `FastAPI Route → concrete Adapter/Port implementation`.

## Closed deterministic mapping additions

| Concern | Semantic operation | Canonical path | Symbol | Test path |
| --- | --- | --- | --- | --- |
| Plan review persistence | `plan.record_review_result` | `application/use_cases/plan/record_review_result.py` | `RecordReviewResultCommandV1`, `RecordReviewResultResultV1`, `RecordReviewResultHandler` | `tests/unit/application/use_cases/plan/test_record_review_result.py` + 12 integration |
| Tool Routing | `tool_routing.resolve_policy_preconditions` | `application/agents/tool_routing/resolve_policy_preconditions.py` | `resolve_policy_preconditions()` | `tests/unit/application/agents/tool_routing/test_resolve_policy_preconditions.py` |
| Planning | `planning.resolve_default_container` | `application/agents/planning/resolve_default_container.py` | `resolve_default_container()` | `tests/unit/application/agents/planning/test_resolve_default_container.py` |
| Run budget | `run.guard_run_budget` | `application/use_cases/run/guard_run_budget.py` | `GuardRunBudgetQueryV1`, `GuardRunBudgetResultV1`, `GuardRunBudgetHandler` | `tests/unit/application/use_cases/run/test_guard_run_budget.py` |
| Confirmation controller | `run.confirm_run` | `application/use_cases/run/confirm_run.py` | `ConfirmationResponseV1` → `CommandResponseV1`, `ConfirmRunHandler` | `tests/unit/application/use_cases/run/test_confirm_run.py` |
| Background Run handoff | `run.schedule_run_execution` | `application/use_cases/run/schedule_run_execution.py` | `handoff_id + submission_kind → effective binding/Run authority fence → claim/reuse WorkflowExecutionAdmissionV1 → WorkflowExecutionSubmissionV2 → RunExecutionAcceptedV1`; same-admission replay=ACCEPTED, stale non-ACCEPTED admission=authority-aware retirement, `ScheduleRunExecutionHandler` | `tests/unit/application/use_cases/run/test_schedule_run_execution.py` |
| Handoff reconciliation | `run.redrive_workflow_handoffs` | `application/use_cases/run/redrive_workflow_handoffs.py` | `CONSUMED active-continuation/domain fence → BLOCKED_BINDING Recovery → PENDING/DISPATCHED dispatch-head → generic SAFE`, `RedriveWorkflowHandoffsHandler`; startup + live loop share this owner | `tests/unit/application/use_cases/run/test_redrive_workflow_handoffs.py` + startup/live integration |
| Retrieval cache restart reconciliation | `run.reconcile_retrieval_cache_restart` | `application/use_cases/run/reconcile_retrieval_cache_restart.py` | `ReconcileRetrievalCacheRestartCommandV1 / ResultV1 / Handler`; `GraphCheckpointEnvelopeV1.retrieval_cache_requirements` → `RunRetrievalCachePort` resolve → deterministic system trigger dedupe → `WorkflowHandoffStageV1(RETRIEVAL_CACHE_RESTART, RETRIEVAL_ENTRY)` short-UoW stage → existing scheduler | `tests/unit/application/use_cases/run/test_reconcile_retrieval_cache_restart.py` + restart/confirmation/reauth integration |
| Component circuit | `component_circuit.check_component_circuit` | `application/use_cases/component_circuit/check_component_circuit.py` | `CheckComponentCircuitQueryV1`, `CheckComponentCircuitResultV1`, `CheckComponentCircuitHandler` | `tests/unit/application/use_cases/component_circuit/test_check_component_circuit.py` |
| Component circuit | `component_circuit.record_component_call_result` | `application/use_cases/component_circuit/record_component_call_result.py` | `RecordComponentCallResultCommandV1`, `RecordComponentCallResultResultV1`, `RecordComponentCallResultHandler` | `tests/unit/application/use_cases/component_circuit/test_record_component_call_result.py` |

`record_review_result`는 lifecycle command가 아니라 current Review artifact를 current Plan/Action revision에 조건부로 기록하는 Application persistence operation이다. `resolve_policy_preconditions`와 `resolve_default_container`는 deterministic supporting operation이며 독립 LangGraph Node/Router/resume target이 아니다. `guard_run_budget`와 component-circuit operations는 NFR/operational boundary를 집행하지만 Domain lifecycle state를 새로 만들지 않는다.


### Runtime Registry closed mapping

The current production Registry set is closed to the following **six distinct authorities**; none is a Port and none may be merged into a generic service locator:

| Registry | Canonical path | Symbol | Registration source | Lookup consumer | Test |
| --- | --- | --- | --- | --- | --- |
| Connector Runtime Registry | `adapters/connectors/runtime/connector_runtime_registry.py` | `ConnectorRuntimeRegistry` | `load_installed_connector_manifest()` from `adapters/connectors/runtime/installed_connector_manifest.json`, verified against 10 Release Manifest | `StdioMCPClientAdapter` / Core connector adapters | `tests/unit/adapters/connectors/runtime/test_connector_runtime_registry.py` |
| Signed Tool Registry | `application/tool_registry/signed_tool_registry.py` | `SignedToolRegistry` | `load_signed_tool_registry()` from release-hash-verified `signed-tool-registry-v1.json`; implementation mirror must exact-match 07 current rows | Tool Routing + Application Connector use cases + composition descriptor projection; Connector adapters do not import it | `tests/unit/application/tool_registry/test_signed_tool_registry.py` |
| Node Registry | `adapters/langgraph/registry/node_registry.py` | `NodeRegistry` | compiled current 35-node graph manifest + 06 exact semantic-owner/profile→compiled-subgraph binding | graph builder / ResumeTargetRegistry | `tests/architecture/langgraph/registry/test_node_registry.py` |
| Resume Target Registry | `adapters/langgraph/registry/resume_target_registry.py` | `ResumeTargetRegistry` | NodeRegistry + 06 `MainResumeStageIdV1(RETRIEVAL_ENTRY|PLANNING_ENTRY|REVIEW_ENTRY|PREFLIGHT|READ_EXECUTION|VERIFICATION|RECOVERY|CANCEL_RESOLUTION)` + compiled profile/graph_version + State Contract child-execution predicates | Confirmation/Reauth/Recovery + ContextAdjustment/Modify/Retry/Cancel external-control resume controllers | `tests/architecture/langgraph/registry/test_resume_target_registry.py` |
| Prompt Registry | `application/prompt_runtime/prompt_registry.py` | `PromptRegistry` | 15-owned Prompt manifest + sources | Agent semantic callers / prompt assembler | `tests/unit/application/prompt_runtime/test_prompt_registry.py` |
| Graph Profile Registry | `adapters/langgraph/profiles/profile_registry.py` | `get_graph_profile_builder()` | three 06-owned profile builders | composition/background executor | `tests/architecture/langgraph/test_graph_profile_registry.py` |

Installed Connector and Tool Registry realization is exact and non-competing:

| Artifact / contract | Repository/build path | Runtime/install path | Loader / consumer | Test |
| --- | --- | --- | --- | --- |
| Installed Connector manifest | `adapters/connectors/runtime/installed_connector_manifest.json` → `InstalledConnectorManifestV1` | `%INSTALL_ROOT%/manifests/installed-connectors-v1.json` | `adapters/connectors/runtime/load_installed_connector_manifest.py → load_installed_connector_manifest()` → `api/composition.py` | `tests/architecture/connectors/test_installed_connector_manifest.py` |
| Tool Registry implementation mirror | `application/tool_registry/tool_registry_manifest.json` → `SignedToolRegistryManifestV1` | `%INSTALL_ROOT%/manifests/signed-tool-registry-v1.json` | `application/tool_registry/load_signed_tool_registry.py → load_signed_tool_registry()` → `SignedToolRegistry` | `tests/architecture/connectors/test_signed_tool_manifest_parity.py` |
| Validated Tool binding contract | `ports/connector/contracts/validated_connector_tool_binding.py` | n/a | `SignedToolRegistry.bind_required()` → Connector Application Port | `tests/unit/ports/connector/contracts/test_validated_connector_tool_binding.py` |
| Connector MCP descriptor projection | generated from the exact connector subset of the implementation Tool manifest during release packaging | `%INSTALL_ROOT%/manifests/connectors/<connector_id>/tool-descriptor-projection-v1.json` | `<connector>/mcp_server/project_registry.py` | `tests/architecture/connectors/test_mcp_tool_projection_manifest.py` |


Installed artifacts are `%INSTALL_ROOT%/manifests/installed-connectors-v1.json`, `%INSTALL_ROOT%/manifests/signed-tool-registry-v1.json`, and `%INSTALL_ROOT%/manifests/connectors/<connector_id>/tool-descriptor-projection-v1.json`; 10 Release Manifest sha256/signature chain authenticates them. Architecture tests compare the implementation Tool manifest entry set/fields against 07 exactly and compare every Connector manifest row to 16 connector package mapping.

`ConnectorRuntimeRegistry` is process binding only; `SignedToolRegistry` is Tool semantic metadata only. `NodeRegistry` is node existence only; `ResumeTargetRegistry` is safe resume reference issue/validation only. `PromptRegistry` never selects LLM provider, and Graph Profile Registry never owns semantic workflow behavior.

### Prompt Registry exact production mapping

15 owns PromptRef/slot/source/assembly semantics. Repository realization is exactly:

```text
application/prompt_runtime/prompt_registry.py
→ PromptRegistry

application/prompt_runtime/assemble_prompt.py
→ assemble_prompt()

application/prompt_runtime/prompt_manifest.json
→ current runtime-selectable Prompt manifest

application/prompt_runtime/sources/<prompt_id>.md
→ immutable prompt source artifact selected by manifest
```

`PromptRegistry.lookup(slot_key) -> PromptRef` uses the 15-owned key `(agent_role, subgraph_name, node_name, node_state, purpose, input_schema_version, output_schema_version)` and validates manifest/source/content_hash/activation status. `assemble_prompt(prompt_ref, input_projection, failure_record?)` may combine only the 15-owned Base Role/Node Purpose/Failure Block/Allowed Change Scope/Output Schema contract. Agent semantic operation chooses the PromptRef key; LLM provider adapters never select or synthesize PromptRef strings.

Tests:

```text
tests/unit/application/prompt_runtime/test_prompt_registry.py
tests/unit/application/prompt_runtime/test_assemble_prompt.py
tests/architecture/prompt/test_prompt_manifest_source_caller_equality.py
```

`application/prompt_runtime` is a structural package, not a seventh Agent/Application semantic owner.

### LLM Runtime Router exact production mapping

03 owns mode/fallback semantics; 07 owns `StructuredInferencePort` callable/result contract. Repository realization is exactly:

```text
ports/llm/structured_inference_port.py
→ StructuredInferencePort

adapters/llm/runtime/structured_inference_router.py
→ StructuredInferenceRuntimeRouter

adapters/llm/<provider>/structured_inference.py
→ <Provider>StructuredInferenceAdapter
```

Only `StructuredInferenceRuntimeRouter` is bound to `StructuredInferencePort` in production. It receives immutable per-Run `requested_mode`, checks 03/09/10 eligibility/status **and current Settings `external_llm_consent` before every API provider call**, applies the allowed AUTO fallback rule, invokes exactly one leaf adapter at a time, and returns `StructuredInferenceResultV1(actual_runtime, provider, model, fallback_reason, ...)`.

`LlmCredentialPort` and `LlmRuntimeStatusPort` follow the same single-binding rule: `adapters/llm/runtime/llm_credential_router.py → LlmCredentialRouter`, `adapters/llm/runtime/llm_runtime_status_router.py → LlmRuntimeStatusRouter`. Their provider-specific leaf adapters remain Router-private.

Leaf provider/Ollama adapters are Router-private concrete dependencies. Application/Agent/LangGraph/API must not import/select them directly. PromptRef selection remains PromptRegistry responsibility; Router receives an already selected `prompt_ref`.

Tests:

```text
tests/unit/adapters/llm/runtime/test_structured_inference_router.py
tests/unit/adapters/llm/runtime/test_llm_credential_router.py
tests/unit/adapters/llm/runtime/test_llm_runtime_status_router.py
tests/architecture/llm/test_structured_inference_single_binding.py
tests/architecture/llm/test_llm_support_port_single_binding.py
```

### Confirmation Controller exact production mapping

```text
application/use_cases/run/confirm_run.py
→ ConfirmRunHandler
# input: run_id + ConfirmationResponseV1
# output: CommandResponseV1
```

Single responsibility:

```text
ConfirmationResponseV1
→ validate current pending interrupt/options/free-text
→ create/validate PolicyConfirmationReceiptV1 when required
→ call mapped ResumeConfirmation lifecycle handler
→ validate RegisteredResumeTargetRefV2 through ResumeTargetRegistry
→ on applied=true stage same-UoW WorkflowHandoffV1 then post-commit call run.schedule_run_execution(handoff_id)
```

`ConfirmRunHandler` does not own the `ResumeConfirmation` transition; it is the API-facing orchestration boundary around that lifecycle command. API route, LangGraph node, and Prompt code may not independently create PolicyConfirmationReceiptV1.

Test: `tests/unit/application/use_cases/run/test_confirm_run.py` + confirmation API/E2E tests.

### Background Run execution exact mapping

```text
application/use_cases/run/schedule_run_execution.py
→ ScheduleRunExecutionHandler
# input: handoff_id + submission_kind -> current guard/effective binding -> persisted WorkflowExecutionAdmissionV1 -> WorkflowExecutionSubmissionV2
# output: RunExecutionAcceptedV1

ports/system/workflow_execution_port.py
→ WorkflowExecutionPort

adapters/langgraph/runtime/background_run_executor.py
→ BackgroundRunExecutorAdapter

adapters/system/workflow_handoff_reconciliation_loop.py
→ WorkflowHandoffReconciliationLoop
```

`ScheduleRunExecutionHandler` accepts `handoff_id + submission_kind` and **must claim/reuse a durable `WorkflowExecutionAdmissionV1` before WEP**. NORMAL only admits the current PENDING dispatch head (or reuses its exact DISPATCHED admission); claim stores the effective exact/ordered-rebind binding and Run authority version while moving PENDING→DISPATCHED. CONSUMED recovery requires latest active lineage/current Domain guard and stores a RESUME admission built from the latest descendant checkpoint while status remains CONSUMED. Before resubmitting an existing admitted row, the handler compares admission expected Run authority with current Run.version; stale NORMAL admission is retired to SUPERSEDED without WEP through `release_execution_admission(..., AUTHORITY_EPOCH_CHANGED)` and recovery admission is cleared/re-evaluated. `WorkflowExecutionSubmissionV2` carries that admission; original handoff execution is not recovery wire authority. Exact same-admission WEP replay is idempotent ACCEPTED. `ACCEPTED` has no post-submit repository write; only non-ACCEPTED results from a non-accepted submitted admission use authority-aware release.

External-control lifecycle handlers stage `WorkflowHandoffStageV1` in the **same UoW** as their successful mutation; `SqliteWorkflowHandoffRepository.stage_pending` allocates server-owned `run_sequence`. `ScheduleRunExecutionHandler` validates current target/Domain facts and claims the execution admission using handoff+Run versions before WEP. `BackgroundRunExecutorAdapter` executes only that persisted admission. The checkpointer commits `execution_admission_id` evidence; NORMAL may combine it with one-shot control + `applied_handoff_id + active_handoff_id/run_sequence` + exact runnable entry. Before semantic owner I/O, Repository settlement checks the admission expected_run_version against current Run.version. Match returns `WorkflowExecutionSettlementV1.SETTLED`; mismatch returns `AUTHORITY_STALE_RETIRED` and atomically retires NORMAL to SUPERSEDED or clears a recovery admission while keeping CONSUMED, so the old owner never receives I/O authority and no stale dispatch head remains. The Background adapter owns no Domain Recovery/live reconciliation; the existing Application reconciler selects the current coordinator after stale retirement. Descendant checkpoints propagate active lineage until a release boundary. Crash recovery may therefore resume the latest descendant checkpoint, not only the initial entry, but Domain `REAUTH_REQUIRED|RECOVERY_REQUIRED|terminal` and cancel-specific authority override stale lineage.

FastAPI Route may not directly select `BackgroundTasks`, `asyncio.create_task`, queue implementation, or LangGraph executor. Exact queue primitive, worker-pool size, and fairness algorithm remain implementation choices behind `WorkflowExecutionPort`.

Reconciliation uses no second execution authority. `RedriveWorkflowHandoffsHandler` is the single Application operation for startup and live reconciliation. For each Open Run it first applies the current Domain/state-specific authority gate. When a continuation is otherwise resumable and the current typed checkpoint declares required retrieval handles, it invokes the injected `ReconcileRetrievalCacheRestartHandler` prerequisite; a staged/existing `RETRIEVAL_CACHE_RESTART` becomes the durable continuation authority before old semantic owner I/O. It then performs: (1) cache prerequisite where applicable, (2) CONSUMED active-continuation evaluation, (3) BLOCKED_BINDING reconciliation through deterministic `system:handoff-binding-recovery:<handoff_id>` + existing RequireRecovery unless already cancel/terminal-preempted, (4) PENDING/DISPATCHED dispatch-head redrive, then (5) generic SAFE evaluation. All execution continues through `ScheduleRunExecutionHandler`; no direct WEP/LangGraph invocation is introduced. `adapters/system/workflow_handoff_reconciliation_loop.py → WorkflowHandoffReconciliationLoop` is a driving adapter that periodically/boundary-wakes the same handler while the service is alive. `api/app.py → create_app()` runs the initial bounded drain, starts this injected loop before READY, and stops it during shutdown; `api/composition.py → build_production_runtime()` remains the only concrete binding authority.

Tests:

```text
tests/unit/application/use_cases/run/test_schedule_run_execution.py
tests/unit/application/use_cases/run/test_redrive_workflow_handoffs.py
tests/integration/startup/test_workflow_handoff_redrive.py
tests/integration/runtime/test_workflow_handoff_live_reconciliation.py
tests/integration/workflow/test_consumed_continuation_recovery.py
tests/unit/adapters/langgraph/runtime/test_background_run_executor.py
tests/architecture/langgraph/test_single_running_run_execution.py
```

Durable handoff exact repository mapping:

```text
ports/system/contracts/workflow_handoff.py
→ WorkflowHandoffStageV1 / WorkflowHandoffV1 / WorkflowExecutionBindingV1 / WorkflowExecutionAdmissionV1 / WorkflowExecutionReleaseReasonV1 / WorkflowExecutionSettlementV1 / WorkflowControlEnvelopeV1 / WorkflowExecutionSubmissionV2

ports/persistence/workflow_handoff_repository.py
→ WorkflowHandoffRepository

adapters/persistence/sqlite/repositories/workflow_handoff_repository.py
→ SqliteWorkflowHandoffRepository
# stage_pending allocates run_sequence and returns persisted WorkflowHandoffV1
# get/get_by_trigger_command_id/get_dispatch_head/list_redriveable/list_blocked_binding return persisted versioned rows
# claim_execution_admission / release_execution_admission / mark_superseded are expected-version CAS returning incremented WorkflowHandoffV1; mark_consumed_and_clear_payload / complete_recovery_admission return WorkflowExecutionSettlementV1; claim and release/settlement also check the persisted admission Run authority version as specified by 07
# supersede_unconsumed_for_run(run_id,reason_code) retires only not-yet-admitted PENDING|DISPATCHED|BLOCKED_BINDING rows; admitted rows already crossed the execution-authority linearization cut

migrations/0009_workflow_handoff_outbox.sql
→ workflow_handoffs table/index/constraints

adapters/langgraph/main/nodes/retrieval_entry_node.py
→ RETRIEVAL_ENTRY
adapters/langgraph/main/nodes/planning_entry_node.py
→ PLANNING_ENTRY
adapters/langgraph/main/nodes/review_entry_node.py
→ REVIEW_ENTRY
adapters/langgraph/main/nodes/cancel_resolution_node.py
→ CANCEL_RESOLUTION

application/use_cases/run/continue_cancel_resolution.py
→ ContinueCancelResolutionCommandV1 / ContinueCancelResolutionResultV1 / ContinueCancelResolutionHandler
```

`CheckpointPort` typed metadata methods `store/load_retrieval_head` and `store/load_external_llm_scope` are implemented by the existing SQLite checkpointer adapter; no second checkpoint reader or Main-State deserializer is allowed. `GraphCheckpointEnvelopeV1.checkpoint_generation + applied_handoff_id + active_handoff_id + active_handoff_run_sequence` are adapter-owned typed metadata used for handoff CAS/dedupe and active-continuation recovery, never Product Prompt input. Descendant checkpoints propagate active lineage until the 06/State release boundary. `RetrievalHeadV1` lives in `ports/system/contracts/retrieval_head.py`.

Tests:

```text
tests/unit/adapters/persistence/sqlite/repositories/test_workflow_handoff_repository.py
tests/integration/workflow/test_external_control_handoff_crash_recovery.py
tests/integration/workflow/test_handoff_submit_reason_matrix.py
tests/unit/application/use_cases/run/test_continue_cancel_resolution.py
tests/integration/retrieval/test_retrieval_head_restart_cas.py
tests/integration/llm/test_external_llm_scope_precedes_provider_call.py
```

### Production composition root exact mapping

The one FastAPI Service production wiring authority is:

```text
api/app.py
→ create_app()
→ api/composition.py
→ build_production_runtime()
```

It may import concrete adapters solely to construct/bind:

```text
Domain Repositories + SqliteUnitOfWork
ConnectorRuntimeRegistry + SignedToolRegistry
MCP/Connector Ports
PromptRegistry
LLM runtime routers (`StructuredInferenceRuntimeRouter`, `LlmCredentialRouter`, `LlmRuntimeStatusRouter`) + provider/local leaf adapters
NodeRegistry + ResumeTargetRegistry + Graph Profile Registry (`get_graph_profile_builder`)
CheckpointPort + WorkflowExecutionPort
system/keyring Ports
FastAPI dependency providers
```

`api/composition.py` owns **wiring only**. It may not own Tool selection, Connector policy, Prompt selection, Domain transitions, lifecycle state, or LLM semantic routing. `api/app.py` owns app construction only. No `application/composition.py`, `launcher/composition.py`, adapter-local second composition root, or FastAPI-startup ad-hoc concrete binding is current production authority.

Test: `tests/architecture/test_production_composition_root.py`.

### Graph Profile composition mapping

| Responsibility | Canonical path/file | Symbol | Test |
| --- | --- | --- | --- |
| SINGLE profile composition | `adapters/langgraph/profiles/single_baseline.py` | `build_single_baseline_graph` | `tests/architecture/langgraph/test_single_baseline_profile.py` |
| THREE profile composition | `adapters/langgraph/profiles/three_stage.py` | `build_three_stage_graph` | `tests/architecture/langgraph/test_three_stage_profile.py` |
| SIX profile composition | `adapters/langgraph/profiles/six_role_baseline.py` | `build_six_role_baseline_graph` | `tests/architecture/langgraph/test_six_role_baseline_profile.py` |
| profile registry | `adapters/langgraph/profiles/profile_registry.py` | `get_graph_profile_builder` | `tests/architecture/langgraph/test_graph_profile_registry.py` |


### Workflow binding shared contract mapping

| Responsibility | Path | Symbol | Test |
| --- | --- | --- | --- |
| same-Run workflow/profile binding typed contract only | `ports/system/contracts/workflow_binding.py` | `GraphProfileIdV1`, `WorkflowBindingV1` | `tests/architecture/contracts/test_workflow_binding_contract.py` |

`CheckpointPort` implementation may persist this contract, but this file contains no Checkpoint I/O and no graph builder selection.


### Evaluation current-artifact mapping

| Responsibility | Path | Symbol | Test |
| --- | --- | --- | --- |
| Canonical Case contract | `evaluation/contracts/canonical_case.py` | `CanonicalCaseV7`, `EndStateGoldV1` | `tests/evaluation/contracts/test_canonical_case.py` |
| E2E Projection contract | `evaluation/contracts/e2e_projection.py` | `E2EProjectionV5` | `tests/evaluation/contracts/test_e2e_projection.py` |
| Product Episode contract | `evaluation/contracts/product_episode_projection.py` | `ProductEpisodeE2EProjectionV1` | `tests/evaluation/contracts/test_product_episode_projection.py` |
| Routing Trajectory contract | `evaluation/contracts/routing_trajectory_projection.py` | `RoutingTrajectoryProjectionV2` | `tests/evaluation/contracts/test_routing_trajectory_projection.py` |
| Context Ready snapshot contract | `evaluation/contracts/context_ready_snapshot.py` | `ContextReadySnapshotV1`, `EvaluationPolicyProjectionV1` | `tests/evaluation/contracts/test_context_ready_snapshot.py` |
| canonical case load | `evaluation/datasets/load_canonical_cases.py` | `load_canonical_cases` | `tests/evaluation/datasets/test_load_canonical_cases.py` |
| current projection build | `evaluation/projections/build_current_projections.py` | `build_current_projections` | `tests/evaluation/projections/test_build_current_projections.py` |
| experiment orchestration | `evaluation/runner/run_experiment.py` | `run_experiment` | `tests/evaluation/runner/test_run_experiment.py` |
| grader dispatch | `evaluation/graders/grade_item.py` | `grade_item` | `tests/evaluation/graders/test_grade_item.py` |
| result artifacts | `evaluation/reporting/write_results.py` | `write_results` | `tests/evaluation/reporting/test_write_results.py` |


### Repository callable closure rule

Mutable lifecycle Repository interfaces use the exact public symbol `update_if_version_and_status(...)` declared in 16/07. Lifecycle handlers decide guards/next state; repositories only perform expected-version/source-status CAS persistence. No alternate public mutation aliases or command-specific repository methods are canonical.


### Operational command replay exact repository mapping

```text
ports/system/operational_command_replay_port.py
→ OperationalCommandReplayPort

adapters/system/filesystem_operational_command_replay.py
→ FilesystemOperationalCommandReplayAdapter

ports/system/contracts/operational_command_replay.py
→ OperationalCommandContextV1 / OperationalReplayDecisionV2 / OperationalReconcileResultV1

tests/unit/adapters/system/test_filesystem_operational_command_replay.py
tests/architecture/test_non_domain_operational_idempotency_boundary.py
```

The production composition root binds exactly this replay adapter. Non-Domain command handlers first persist an fsync-backed reservation including one opaque stable `operation_ref`. `RECOVER_RESERVED` returns that same ref and always calls the exact 07 operation-specific reconciliation surface before any retry: OAuth start/revoke on `OAuthCredentialPort`, LLM credential store/delete on `LlmCredentialPort`, Settings on `SettingsPort`, Runtime Mode on `RuntimeModePort`, Backup/Restore on `BackupPort`, Diagnostics on `DiagnosticsPort`, Shutdown on `ShutdownPort`, Attachment staging on `AttachmentStagingPort`. Artifact callables receive `operation_ref`; Restore receives it with `backup_ref`. Reconcile returns `OperationalReconcileResultV1`; Application performs no raw filesystem/keyring/process inspection. `SAFE_CHECKPOINT_RESUME` also uses this replay boundary; its stored result is `handoff_id`, recovered through `WorkflowHandoffRepository.get_by_trigger_command_id(command_id)`. No non-Domain handler writes 04 Domain `command_receipts`.

### Retrieval stable segment identity realization

`05 SourceSegmentIdentityV1`/`segment_id` construction is owned by `application/agents/retrieval/normalize_segments.py` deterministic normalization/chunking responsibility and its typed contract module under `application/agents/retrieval/contracts/segment_identity.py`. Random UUID/retrieval-revision-scoped IDs are forbidden. `RetrievalStateV2.exclusion_obligation_segment_ids` is checkpoint-local typed state, and `RetrievalResultV1.excluded_segment_ids` is the official finalized artifact field; no SQLite Domain table or second exclusion repository is introduced. Tests: `tests/unit/application/agents/retrieval/test_normalize_segments.py`, `tests/integration/retrieval/test_context_adjustment_restart.py`.

### QueryAttempt current-contract realization

`05 Retrieval §16.1 QueryAttemptV1` is the single semantic/schema authority. Repository placement is `application/agents/retrieval/contracts/query_attempt.py → QueryAttemptV1`; Retrieval operations import that type rather than defining owner-local variants. `15 Prompt/Failure` and Evaluation/Observability consumers may project only the 05-owned fields and canonical `QUERY_UNCHANGED_AFTER_FAILURE` vocabulary; a second `schema_version=1` QueryAttempt contract, `QUERY_REPEATED_WITHOUT_CHANGE`, or Provider-specific source enum is forbidden. Tests: `tests/architecture/contracts/test_query_attempt_single_authority.py` + Retrieval planner/failure regressions in 12.

### Run Retrieval Cache exact realization

`ports/system/run_retrieval_cache_port.py → RunRetrievalCachePort` is the single Core boundary for run-scoped raw continuation/read-result memory. `adapters/system/sqlite_checkpoint.py → SqliteCheckpointAdapter` projects only `RetrievalCacheRequirementV1(read_result_handle, route_id, query_identity_hash)` into `GraphCheckpointEnvelopeV1.retrieval_cache_requirements`; Application code never opens `checkpoint_blob` to discover cache dependencies. P0 binds it once in `api/composition.py` to `adapters/system/memory/run_retrieval_cache.py → InMemoryRunRetrievalCache`. `application/agents/retrieval/execute_read.py` is the normal producer/consumer; it never owns module-global cache state. `application/use_cases/run/reconcile_retrieval_cache_restart.py → ReconcileRetrievalCacheRestartHandler` is the only Application authority that converts a typed handle-resolution failure into durable `RETRIEVAL_CACHE_RESTART`. Terminalizing Run handlers (`complete_answer_only_run`, `complete_read_only_run`, `complete_write_run`, `finalize_cancel`, terminal `resolve_recovery`) call `discard_run(run_id)` **after** their terminal Domain UoW commits; cleanup failure cannot roll back the terminal fact because cache loss is already a safe condition. Process restart begins with an empty cache. Tests: `tests/unit/adapters/system/memory/test_run_retrieval_cache.py`, `tests/unit/application/use_cases/run/test_reconcile_retrieval_cache_restart.py`, `tests/integration/retrieval/test_cache_loss_restart.py`.


### Per-Run requested_mode exact repository realization

`run.start_run` writes wire `requested_mode` into the Run aggregate in the same UoW as Run/USER Message creation. `RunRepository.create/get/get_snapshot` include this immutable field. `RunInputV1`, `WorkflowBindingV1`, and `RunExecutionRefV1` exact-copy it. No resume handler reads Settings `preferred_llm_mode` or process runtime-mode as a substitute.
