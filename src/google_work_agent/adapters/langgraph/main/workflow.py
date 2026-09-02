"""Concrete Stage 17 workflow runtime assembled on LangGraph."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping
from copy import deepcopy
from functools import partial
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from langgraph.types import interrupt

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.main.application_services import (
    WorkflowApplicationServices,
    WorkflowRuntimeHooks,
)
from google_work_agent.adapters.langgraph.main.artifact_freshness import (
    ArtifactFreshnessMixin,
)
from google_work_agent.adapters.langgraph.main.confirmation_controller import (
    ConfirmationControllerMixin,
)
from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
)
from google_work_agent.adapters.langgraph.main.nodes.action_execution_node import (
    action_execution_node,
)
from google_work_agent.adapters.langgraph.main.nodes.cancel_resolution_node import (
    cancel_resolution_node,
)
from google_work_agent.adapters.langgraph.main.nodes.domain_reconcile_node import (
    domain_reconcile_node,
)
from google_work_agent.adapters.langgraph.main.nodes.domain_validation_node import (
    domain_validation_node,
)
from google_work_agent.adapters.langgraph.main.nodes.finalize_node import finalize_node
from google_work_agent.adapters.langgraph.main.nodes.initialize_node import initialize_node
from google_work_agent.adapters.langgraph.main.nodes.planning_entry_node import (
    planning_entry_node,
)
from google_work_agent.adapters.langgraph.main.nodes.preflight_node import preflight_node
from google_work_agent.adapters.langgraph.main.nodes.recovery_node import recovery_node
from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
    response_synthesis_node,
)
from google_work_agent.adapters.langgraph.main.nodes.retrieval_entry_node import (
    retrieval_entry_node,
)
from google_work_agent.adapters.langgraph.main.nodes.review_entry_node import review_entry_node
from google_work_agent.adapters.langgraph.main.nodes.terminal_commit_node import (
    terminal_commit_node,
)
from google_work_agent.adapters.langgraph.main.nodes.verification_node import verification_node
from google_work_agent.adapters.langgraph.main.plan_persistence import (
    PlanPersistenceMixin,
    _connector_id_for_evidence_handle,
)
from google_work_agent.adapters.langgraph.main.response_synthesis import (
    ResponseSynthesisMixin,
)
from google_work_agent.adapters.langgraph.main.resume_checkpoint import (
    ResumeCheckpointMixin,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
    GraphRouteTranslator,
    UnroutableSupervisorTargetError,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
    _acquired_resource_by_handle,
    _require_state_value,
    _resource_handle_for_ref,
    initial_graph_state,
    request_from_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
    route_supervisor,
)
from google_work_agent.adapters.langgraph.main.validate_planning_output import (
    CurrentRunResourceIdentityV1,
)
from google_work_agent.adapters.langgraph.pre_analysis_composition import (
    build_pre_analysis_subgraphs,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import (
    GraphProfile,
    get_graph_profile_builder,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.graph import ReviewSubgraph
from google_work_agent.adapters.langgraph.subgraphs.single_workflow import (
    SingleWorkflowSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.three_stage import (
    ThreeStageOneSubgraph,
    ThreeStageTwoSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import (
    WorkAnalysisSubgraph,
)
from google_work_agent.adapters.langgraph.write_execution import (
    WriteExecutionNode,
    write_action_statuses_are_closed,
)
from google_work_agent.adapters.langgraph.write_execution_driver import (
    UnknownRecoveryPhaseRequest,
    WriteExecutionStructuralDriver,
)
from google_work_agent.adapters.langgraph.write_recovery import WriteRecoveryCoordinator
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.adapters.system.memory.run_retrieval_cache import (
    InMemoryRunRetrievalCache,
)
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
)
from google_work_agent.application.agents.planning.contracts.domain_validation import (
    DomainValidationResult,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
    CalendarWorkHours,
)
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    evidence_calendar_conflict_risk,
)
from google_work_agent.application.use_cases.action.cancel_pending_action import (
    CancelPendingActionCommand,
)
from google_work_agent.application.use_cases.action.feasibility import evidence_feasibility_risk
from google_work_agent.application.use_cases.action.read_contracts import (
    ClaimReadActionCommand,
    CompleteReadActionCommand,
    FailReadActionCommand,
    FinalizeReadActionCommand,
)
from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionCommandV1,
)
from google_work_agent.application.use_cases.execution_attempt.connector_write_projection import (
    ConnectorWriteProjection,
)
from google_work_agent.application.use_cases.execution_attempt.persistence_projection import (
    latest_attempt_for_action,
)
from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
    load_plan_record,
)
from google_work_agent.application.use_cases.plan.project_dependencies import (
    project_dependency_ids,
)
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultCommandV1,
    ReviewDispositionV1,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommandV1,
)
from google_work_agent.application.use_cases.resource.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.use_cases.run.begin_planning import (
    BeginPlanningCommand,
)
from google_work_agent.application.use_cases.run.begin_retrieval import (
    BeginRetrievalCommand,
)
from google_work_agent.application.use_cases.run.begin_verification import (
    BeginVerificationCommand,
)
from google_work_agent.application.use_cases.run.block_run import (
    BlockRunCommand,
)
from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunCommand,
)
from google_work_agent.application.use_cases.run.complete_read_only_run import (
    CompleteReadOnlyRunCommand,
)
from google_work_agent.application.use_cases.run.complete_write_run import (
    CompleteWriteRunCommand,
)
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionCommandV1,
    ContinueCancelResolutionResultV1,
)
from google_work_agent.application.use_cases.run.finalize_cancel import (
    FinalizeCancelCommand,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetRunSnapshotQuery,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    approve_planning_revision,
)
from google_work_agent.application.use_cases.run.start_analysis import (
    StartAnalysisCommand,
)
from google_work_agent.application.use_cases.run.terminal_contract import (
    ReviewResult,
)
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
)
from google_work_agent.application.use_cases.trace_event.emit_trace_event import (
    EmitTraceEventCommand,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanReviewStatus
from google_work_agent.domain.recovery.model import RecoveryResolution
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.connector.contracts.google_workspace import GoogleWorkspaceGatewayError
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork as CanonicalUnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.observability import (
    EventCategory,
    ObservabilityContext,
    Severity,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.sse_event_buffer_port import SseEventBufferPort

JsonObject = dict[str, object]


class _ResourceIdentityProjection:
    def __init__(self, resources: Mapping[str, ResourceRefRecord]) -> None:
        self._resources = resources

    def resolve_resource_identity(
        self,
        *,
        run_id: str,
        resource_handle: str,
    ) -> CurrentRunResourceIdentityV1 | None:
        resource = self._resources.get(resource_handle)
        if resource is None or resource.run_id != run_id:
            return None
        return {
            "resource_handle": resource_handle,
            "resource_type": resource.resource_type,
            "resource_id": resource.resource_id,
            "parent_id": resource.parent_resource_id,
        }


class _CloseableCheckpoint(Protocol):
    def close(self) -> None: ...


class _WorkflowRuntimeComposition:
    """LangGraph runtime with selectable Stage 18 graph profiles."""

    if TYPE_CHECKING:
        _has_persisted_cancel_intent: Callable[[str], bool]
        discard_run_transients: Callable[[str], None]

        def _confirm_request_understanding_inline(
            self, state: GraphState
        ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]: ...

        def _confirm_tool_route_inline(
            self, state: GraphState
        ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]: ...

        def _confirm_context_retrieval_inline(
            self, state: GraphState
        ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]: ...

        def _confirm_work_analysis_inline(
            self, state: GraphState
        ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]: ...

        def _confirm_planning_inline(
            self, state: GraphState
        ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]: ...

        def _confirm_review_inline(
            self, state: GraphState
        ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]: ...

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        llm_runtime: Any,
        connector_reader: ConnectorReadProjection,
        connector_execution: ConnectorWriteProjection,
        tool_catalog: SignedToolRegistry,
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        signing_secret: str,
        service_instance_id: str,
        checkpoint_port: CheckpointPort,
        application_services: WorkflowApplicationServices,
        runtime_hooks: WorkflowRuntimeHooks,
        retrieval_cache: InMemoryRunRetrievalCache | None = None,
        claim_context_signer: Callable[[dict[str, object]], str] | None = None,
        mcp_process_instance_id: Callable[[], str] | None = None,
        graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path: Path | None = None,
        timezone_provider: Callable[[], str] | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
        attachment_verifier: Any | None = None,
        resume_target_registry: ResumeTargetRegistry | None = None,
        sse_event_buffer: SseEventBufferPort | None = None,
        environment: str = "TEST",
        release_version: str = "test",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._tool_catalog = tool_catalog
        self._llm_runtime = llm_runtime
        self._now_ms = now_ms
        self._id_factory = id_factory
        del signing_secret
        self._service_instance_id = service_instance_id
        self._checkpoint_port = checkpoint_port
        self._graph_profile = graph_profile
        self._route_translator = GraphRouteTranslator(graph_profile)
        self._resume_target_registry = resume_target_registry or ResumeTargetRegistry(
            node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
            graph_version=RESUME_CONTRACT_VERSION,
        )
        self._work_hours_provider = work_hours_provider or (
            lambda: CalendarWorkHours(timezone=(timezone_provider or (lambda: "Asia/Seoul"))())
        )
        self._default_tasklist_id_provider = default_tasklist_id_provider
        self._default_calendar_id_provider = default_calendar_id_provider
        self._cancel_signal_lock = Lock()
        self._cancel_signals: set[str] = set()
        self._checkpointer = self._checkpoint_port
        runtime_hooks.bind(self)
        services = application_services
        self._start_analysis_handler = services.start_analysis
        self._get_run_snapshot_handler = services.get_run_snapshot
        self._build_terminal_message = services.build_terminal_message
        self._emit_terminal_trace = services.emit_terminal_trace
        self._project_terminal_event = services.project_terminal_event
        self._begin_retrieval_handler = services.begin_retrieval
        self._begin_planning_handler = services.begin_planning
        self._request_confirmation_handler = services.request_confirmation
        self._read_result_cache = retrieval_cache or InMemoryRunRetrievalCache()
        self._evidence_store = RunScopedEvidenceStore()
        self._canonical_domain_validation = services.domain_validation
        self._complete_answer_only = services.complete_answer_only
        self._complete_read_only_run = services.complete_read_only_run
        self._complete_write_run = services.complete_write_run
        self._block_run = services.block_run
        self._publish_read_plan = services.publish_read_plan
        self._save_read_plan = self._publish_read_plan.save
        self._claim_read = services.claim_read
        self._complete_read = services.complete_read
        self._execute_read = self._complete_read.execute
        self._finalize_read = services.finalize_read
        self._fail_read = services.fail_read
        self._publish_write_plan = services.publish_write_plan
        self._save_write_plan = self._publish_write_plan.save
        self._build_claim_context = services.build_claim_context
        self._begin_execution_attempt = services.begin_execution_attempt
        self._abort_claimed_execution = services.abort_claimed_execution
        self._classify_dispatch_result = services.classify_dispatch_result
        self._expire_approval = services.expire_approval
        self._refresh_expired_action = services.refresh_expired_action
        self._claim_execution = services.claim_execution
        self._preflight_write = self._claim_execution.preflight
        self._store_write_success = services.store_write_success
        self._mark_write_failed = services.mark_write_failed
        self._mark_write_unknown = services.mark_write_unknown
        self._verify_effect = services.verify_effect
        self._store_verification = services.store_verification
        self._require_recovery = services.require_recovery
        self._resolve_recovery = services.resolve_recovery
        self._require_write_reauth = services.require_write_reauth
        self._lookup_unknown_result = services.lookup_unknown_result
        self._recover_existing_result = services.recover_existing_result
        self._resolve_as_failed = services.resolve_as_failed
        self._begin_write_verification = services.begin_write_verification
        self._record_review_result = services.record_review_result
        self._validate_action_arguments = services.validate_action_arguments
        self._write_execution_phase = WriteExecutionStructuralDriver(
            id_factory=id_factory,
            request_hash=self._request_hash,
            should_stop_for_cancel=self._should_stop_for_cancel,
            preflight_write=self._preflight_write,
            claim_execution=self._claim_execution,
            build_claim_context=self._build_claim_context,
            begin_execution_attempt=self._begin_execution_attempt,
            abort_claimed_execution=self._abort_claimed_execution,
            connector_execution=connector_execution,
            classify_dispatch_result=self._classify_dispatch_result,
            store_write_success=self._store_write_success,
            begin_verification=self._begin_write_verification,
            verify_effect=self._verify_effect,
            store_verification=self._store_verification,
            require_recovery=self._require_recovery,
            resolve_recovery=self._resolve_recovery,
            mark_write_failed=self._mark_write_failed,
            mark_write_unknown=self._mark_write_unknown,
            service_instance_id=service_instance_id,
            mcp_process_instance_id=mcp_process_instance_id or (lambda: "test-mcp-process"),
            require_write_reauth=self._require_write_reauth,
            lookup_unknown_result=self._lookup_unknown_result,
            recover_existing_result=self._recover_existing_result,
            resolve_as_failed=self._resolve_as_failed,
        )
        self._write_execution_node = WriteExecutionNode(
            id_factory=id_factory,
            request_hash=self._request_hash,
            should_stop_for_cancel=self._should_stop_for_cancel,
            list_actions=self._list_actions,
            has_independent_executable_action=self._has_independent_executable_action,
            execute_read_only_plan=self._execute_read_only_plan,
            execution_phase=self._write_execution_phase,
            has_persisted_cancel_intent=self._has_persisted_cancel_intent,
        )
        self._write_recovery = WriteRecoveryCoordinator(
            latest_unknown_action=self._latest_unknown_action,
            execution_phase=self._write_execution_phase,
            write_run_completion_ready=self._write_run_completion_ready,
            plans_for_run=self._plans_for_run,
            list_actions=self._list_actions,
            begin_verification=lambda run_id, action_id, attempt_id: (
                None
                if self._current_run_status(run_id) == RunStatusV1.VERIFYING.value
                else self._begin_write_verification(
                    BeginVerificationCommand(
                        command_id=self._id_factory(),
                        request_hash=calculate_canonical_json_hash(
                            {
                                "kind": "begin_verification_recovery",
                                "run_id": run_id,
                                "action_id": action_id,
                                "execution_attempt_id": attempt_id,
                            }
                        ),
                        run_id=run_id,
                        action_id=action_id,
                        execution_attempt_id=attempt_id,
                    )
                )
            ),
            latest_attempt_id=self._latest_attempt_id,
        )
        self._cancel_pending_action = services.cancel_pending_action
        self._finalize_cancel = services.finalize_cancel
        self._continue_cancel_resolution = services.continue_cancel_resolution
        entry_subgraphs = build_pre_analysis_subgraphs(
            llm_runtime=self._llm_runtime,
            prompt_manifest_path=prompt_manifest_path,
            connector_reader=connector_reader.connector_reader,
            tool_catalog=tool_catalog,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            transition_run=self._transition_run,
            merge_decision=self._merge_decision,
            confirm_request_understanding_inline=self._confirm_request_understanding_inline,
            confirm_tool_route_inline=self._confirm_tool_route_inline,
            confirm_context_retrieval_inline=self._confirm_context_retrieval_inline,
            evidence_store=self._evidence_store,
            read_result_cache=self._read_result_cache,
            default_tasklist_id_provider=self._default_tasklist_id_provider,
            default_calendar_id_provider=self._default_calendar_id_provider,
        )
        self._request_subgraph = entry_subgraphs.request_understanding
        self._tool_route_subgraph = entry_subgraphs.tool_route
        self._context_subgraph = entry_subgraphs.context_retrieval
        self._analysis_subgraph = WorkAnalysisSubgraph(
            llm_runtime=self._llm_runtime,
            prompt_manifest_path=prompt_manifest_path,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            transition_run=self._transition_run,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            confirm_inline=self._confirm_work_analysis_inline,
        ).build()
        self._planning_subgraph = PlanningSubgraph(
            llm_runtime=self._llm_runtime,
            prompt_manifest_path=prompt_manifest_path,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            merge_decision=cast(Any, self._merge_decision),
            evidence_store=self._evidence_store,
            confirm_inline=cast(Any, self._confirm_planning_inline),
            default_tasklist_id_provider=self._default_tasklist_id_provider,
            default_calendar_id_provider=self._default_calendar_id_provider,
        ).build()
        self._review_subgraph = ReviewSubgraph(
            llm_runtime=self._llm_runtime,
            prompt_manifest_path=prompt_manifest_path,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            confirm_inline=cast(Any, self._confirm_review_inline),
            resume_target_registry=self._resume_target_registry,
        ).build()
        self._three_stage_one_subgraph: Any = None
        self._three_stage_two_subgraph: Any = None
        self._three_stage_review_subgraph: Any = None
        if self._graph_profile is GraphProfile.THREE_STAGE:
            self._three_stage_one_subgraph = ThreeStageOneSubgraph(
                request_understanding=self._request_subgraph,
                tool_route=self._tool_route_subgraph,
                retrieval=self._context_subgraph,
            ).build()
            self._three_stage_two_subgraph = ThreeStageTwoSubgraph(
                work_analysis=self._analysis_subgraph,
                planning=self._planning_subgraph,
            ).build()
            self._three_stage_review_subgraph = self._review_subgraph
        self._single_workflow_subgraph: Any = None
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            self._single_workflow_subgraph = SingleWorkflowSubgraph(
                request_understanding=self._request_subgraph,
                tool_route=self._tool_route_subgraph,
                retrieval=self._context_subgraph,
                work_analysis=self._analysis_subgraph,
                planning=self._planning_subgraph,
                review=self._review_subgraph,
            ).build()
        self._topology = self._topology_for_profile()
        self._graph_node_bindings = GraphNodeBindings(
            request_understanding=self._request_subgraph,
            tool_route=self._tool_route_subgraph,
            context_retriever=self._context_subgraph,
            work_analysis=self._analysis_subgraph,
            planning=self._planning_subgraph,
            review=self._review_subgraph,
            single_workflow=self._single_workflow_subgraph,
            waiting_approval=self._waiting_approval_node,
            stage_one=self._three_stage_one_subgraph,
            stage_two=self._three_stage_two_subgraph,
            stage_three=self._three_stage_review_subgraph,
        )
        self._main_graph_control_bindings = self._main_control_bindings()
        profile_builder = get_graph_profile_builder(self._graph_profile)
        self._graph_composition = profile_builder(
            bindings=self._graph_node_bindings,
            control_bindings=self._main_graph_control_bindings,
            should_stop_for_cancel=self._should_stop_for_cancel,
            checkpointer=self._checkpointer,
        )
        self._native_agent_subgraphs = self._native_subgraphs_for_profile()
        self._graph = self._build_graph()
        self._invocation = WorkflowInvocationCoordinator(
            graph=self._graph,
            graph_profile=self._graph_profile,
            graph_version=RESUME_CONTRACT_VERSION,
            start_node="initialize",
            initial_state=self._initial_state,
            current_run_status=self._current_run_status,
            latest_unknown_action=self._latest_unknown_action,
            recovery_node=partial(
                recovery_node,
                recover_from_durable_facts=self._write_recovery.recover_unknown,
            ),
            has_executed_action=self._has_executed_action,
            recover_executed_actions=self._write_recovery.recover_executed,
            mark_stalled_claims_as_unknown=self._mark_stalled_claims_as_unknown,
            cancel_signal_lock=self._cancel_signal_lock,
            cancel_signals=self._cancel_signals,
            now_ms=now_ms,
            retrieval_node=self._physical_agent_node("context_retriever"),
        )

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        try:
            return self._invocation.start(request)
        except LLMInvocationError as error:
            return self._settle_llm_budget_exhaustion(
                error=error,
                run_id=request.run_id,
                workflow_key=request.workflow_key,
            )

    def prepare_start(self, request: WorkflowStartRequest) -> None:
        self._invocation.prepare_start(request)

    def control_resume_node(self, stage_id: str) -> str:
        """Resolve a registered external-control stage to this profile's native node."""
        exact_control = {
            "READ_EXECUTION": "action_execution",
            "VERIFICATION": "verification",
            "RECOVERY": "recovery",
            "CANCEL_RESOLUTION": "cancel_resolution",
        }.get(stage_id)
        if exact_control is not None:
            return exact_control
        target_by_stage = {
            "RETRIEVAL_ENTRY": SupervisorTarget.CONTEXT_RETRIEVAL.value,
            "PLANNING_ENTRY": SupervisorTarget.SOLUTION_PLANNING.value,
            "REVIEW_ENTRY": SupervisorTarget.PLAN_REVIEW_INSPECT.value,
            "PREFLIGHT": SupervisorTarget.PREFLIGHT.value,
        }
        target = target_by_stage.get(stage_id)
        if target is None:
            raise ValueError(f"main resume stage is not realized by this runtime: {stage_id}")
        return self._route_translator.translate(target).node

    def agent_resume_node(self, semantic_owner_id: str) -> str:
        target_by_owner = {
            "REQUEST_UNDERSTANDING": self._topology[0],
            "TOOL_ROUTE": SupervisorTarget.TOOL_ROUTE.value,
            "RETRIEVAL": SupervisorTarget.CONTEXT_RETRIEVAL.value,
            "WORK_ANALYSIS": SupervisorTarget.WORK_ANALYSIS.value,
            "PLANNING": SupervisorTarget.SOLUTION_PLANNING.value,
            "REVIEW": SupervisorTarget.PLAN_REVIEW_INSPECT.value,
        }
        target = target_by_owner.get(semantic_owner_id)
        if target is None:
            raise ValueError(f"unknown semantic resume owner: {semantic_owner_id}")
        if target == self._topology[0]:
            return self._topology[0]
        return self._route_translator.translate(target).node

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        try:
            return self._invocation.resume(request)
        except LLMInvocationError as error:
            return self._settle_llm_budget_exhaustion(
                error=error,
                run_id=request.run_id,
                workflow_key=request.workflow_key,
            )

    def _settle_llm_budget_exhaustion(
        self,
        *,
        error: LLMInvocationError,
        run_id: str,
        workflow_key: str,
    ) -> WorkflowInvocationResult:
        """Fail closed when the canonical per-Run provider budget is exhausted."""

        if error.code is not LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED:
            raise error
        message = str(error)
        reason_code = (
            "ABSOLUTE_LLM_LIMIT_EXHAUSTED"
            if "ABSOLUTE_LLM_LIMIT_EXHAUSTED" in message
            else "PROFILE_LLM_LIMIT_EXHAUSTED"
        )
        config = self._config_for_thread(workflow_key)
        snapshot = self._graph.get_state(config)
        pending_owner = next(
            (node for node in snapshot.next if isinstance(node, str) and node != "__start__"),
            None,
        )
        if pending_owner is None:
            raise RuntimeError("LLM budget exhaustion has no resumable graph owner")
        self._graph.update_state(
            config,
            {
                "__logical_target__": "response_synthesis",
                "__target__": "response_synthesis",
                "finalize_intent": {
                    "schema_version": 1,
                    "intent": "BLOCKED",
                    "reason_code": reason_code,
                },
            },
            as_node=pending_owner,
        )
        self._graph.invoke(None, config=config)
        return self._invocation.result_from_thread(
            workflow_key=workflow_key,
            run_id=run_id,
        )

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        with self._cancel_signal_lock:
            self._cancel_signals.add(request.run_id)
        return WorkflowInvocationResult(
            run_id=request.run_id,
            workflow_key=request.workflow_key,
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"phase": "cancel_requested", "reason_code": request.reason_code},
        )

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        return self._invocation.recover_open_run(request)

    def close(self) -> None:
        """Release the concrete checkpoint lifecycle owned by this runtime."""

        cast(_CloseableCheckpoint, self._checkpoint_port).close()

    def _main_control_bindings(self) -> MainControlNodeBindings:
        request_node = self._physical_agent_node("request_understanding")
        retrieval_node = self._physical_agent_node("context_retriever")
        planning_node = self._physical_agent_node("planning")
        review_node = self._physical_agent_node("review")
        return MainControlNodeBindings(
            initialize=partial(
                initialize_node,
                start_analysis=self._start_analysis_for_main,
                request_node=request_node,
                request_logical_node="request_understanding",
            ),
            retrieval_entry=partial(
                retrieval_entry_node,
                current_run_status=self._current_run_status,
                begin_retrieval=self._begin_retrieval_for_main,
                retrieval_node=retrieval_node,
                retrieval_logical_node="context_retriever",
            ),
            planning_entry=partial(
                planning_entry_node,
                current_run_status=self._current_run_status,
                begin_planning=self._begin_planning_for_main,
                planning_node=planning_node,
                planning_logical_node="planning",
            ),
            review_entry=partial(
                review_entry_node,
                prepare_persisted_review=self._prepare_current_persisted_review_state,
                settle_persisted_review=self._settle_persisted_review,
                review_node=review_node,
                review_logical_node="review",
            ),
            domain_validation=partial(
                domain_validation_node,
                validate_and_project=self._validate_domain_and_project,
            ),
            preflight=partial(
                preflight_node,
                check_freshness_and_claim=self._write_execution_node.preflight,
            ),
            domain_reconcile=partial(
                domain_reconcile_node,
                read_durable_run=self._read_durable_run,
            ),
            action_execution=partial(
                action_execution_node,
                execute_claimed_action=self._write_execution_node,
            ),
            verification=partial(
                verification_node,
                verify_durable_effects=lambda state: self._write_recovery.recover_executed(
                    cast(GraphState, state), cast(str, state["run_id"])
                ),
            ),
            recovery=partial(
                recovery_node,
                recover_from_durable_facts=self._write_recovery.recover_unknown,
            ),
            cancel_resolution=partial(
                cancel_resolution_node,
                continue_cancel_resolution=self._continue_cancel_resolution_for_main,
            ),
            response_synthesis=partial(
                response_synthesis_node,
                read_terminal_facts=self._read_terminal_facts,
                build_terminal_message=self._build_terminal_message,
            ),
            terminal_commit=partial(
                terminal_commit_node,
                read_terminal_facts=self._read_terminal_facts,
                complete_answer_only=self._terminal_complete_answer_only,
                complete_read_only=self._terminal_complete_read_only,
                complete_write=self._terminal_complete_write,
                block_run=self._terminal_block_run,
                finalize_cancel=self._terminal_finalize_cancel,
                resolve_recovery=self._terminal_resolve_recovery,
            ),
            finalize=partial(
                finalize_node,
                read_terminal_facts=self._read_terminal_facts,
                emit_trace=self._emit_terminal_finalize_trace,
                project_run_event=self._project_terminal_finalize_event,
                discard_run_transients=self.discard_run_transients,
            ),
        )

    def _physical_agent_node(self, semantic_node: str) -> str:
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            return "single_workflow"
        if self._graph_profile is GraphProfile.THREE_STAGE:
            if semantic_node in {"request_understanding", "tool_route", "context_retriever"}:
                return "stage_one"
            if semantic_node in {"work_analysis", "planning"}:
                return "stage_two"
            if semantic_node == "review":
                return "stage_three"
        if semantic_node in {
            "request_understanding",
            "tool_route",
            "context_retriever",
            "work_analysis",
            "planning",
            "review",
        }:
            return semantic_node
        raise ValueError(f"unknown semantic agent node: {semantic_node}")

    def _read_durable_run(self, run_id: str) -> Any:
        snapshot = self._get_run_snapshot_handler(GetRunSnapshotQuery(run_id))
        return None if snapshot is None else snapshot.run

    def _read_terminal_facts(self, run_id: str) -> dict[str, object]:
        snapshot = self._get_run_snapshot_handler(GetRunSnapshotQuery(run_id))
        if snapshot is None:
            raise LookupError(f"run not found: {run_id}")
        return {
            "run_id": run_id,
            "conversation_id": snapshot.run.conversation_id,
            "status": snapshot.run.status,
            "version": snapshot.run.version,
            "terminal_result_kind": (
                None if snapshot.terminal_result_kind == "NONE" else snapshot.terminal_result_kind
            ),
            "final_message_count": sum(
                message.role == "ASSISTANT" for message in snapshot.messages
            ),
            "plan_id": (
                None if snapshot.current_plan is None else snapshot.current_plan.get("plan_id")
            ),
            "action_statuses": [action.status for action in snapshot.actions],
            "action_effect_types": [action.effect_type for action in snapshot.actions],
        }

    def _terminal_complete_answer_only(
        self, state: Mapping[str, object], intent: TerminalCommitIntentV1
    ) -> object:
        run_id = cast(str, state["run_id"])
        payload = self._terminal_command_payload(run_id, intent)
        return self._complete_answer_only(
            CompleteAnswerOnlyRunCommand(
                command_id=self._terminal_command_id(payload),
                conversation_id=cast(str, state["conversation_id"]),
                run_id=run_id,
                assistant_message=intent["terminal_message"].content,
                expected_version=intent["expected_run_version"],
                request_hash=calculate_canonical_json_hash(payload),
                result_kind=cast(
                    Literal["SUCCESS", "PARTIAL"],
                    intent["terminal_message"].result_kind,
                ),
            )
        )

    def _terminal_complete_read_only(
        self, state: Mapping[str, object], intent: TerminalCommitIntentV1
    ) -> object:
        run_id = cast(str, state["run_id"])
        facts = self._read_terminal_facts(run_id)
        plan_id = self._required_string(facts.get("plan_id"), "plan_id")
        payload = self._terminal_command_payload(run_id, intent)
        return self._complete_read_only_run(
            CompleteReadOnlyRunCommand(
                command_id=self._terminal_command_id(payload),
                request_hash=calculate_canonical_json_hash(payload),
                run_id=run_id,
                plan_id=plan_id,
                expected_version=intent["expected_run_version"],
            )
        )

    def _terminal_complete_write(
        self, state: Mapping[str, object], intent: TerminalCommitIntentV1
    ) -> object:
        run_id = cast(str, state["run_id"])
        payload = self._terminal_command_payload(run_id, intent)
        return self._complete_write_run(
            CompleteWriteRunCommand(
                command_id=self._terminal_command_id(payload),
                request_hash=calculate_canonical_json_hash(payload),
                run_id=run_id,
                expected_version=intent["expected_run_version"],
            )
        )

    def _terminal_block_run(
        self, state: Mapping[str, object], intent: TerminalCommitIntentV1
    ) -> object:
        run_id = cast(str, state["run_id"])
        payload = self._terminal_command_payload(run_id, intent)
        return self._block_run(
            BlockRunCommand(
                command_id=self._terminal_command_id(payload),
                request_hash=calculate_canonical_json_hash(payload),
                run_id=run_id,
                expected_version=intent["expected_run_version"],
                reason_code=intent["reason_codes"][0] if intent["reason_codes"] else "BLOCKED",
            )
        )

    def _terminal_finalize_cancel(
        self, state: Mapping[str, object], intent: TerminalCommitIntentV1
    ) -> object:
        run_id = cast(str, state["run_id"])
        payload = self._terminal_command_payload(run_id, intent)
        return self._finalize_cancel(
            FinalizeCancelCommand(
                command_id=self._terminal_command_id(payload),
                request_hash=calculate_canonical_json_hash(payload),
                run_id=run_id,
                expected_run_version=intent["expected_run_version"],
            )
        )

    def _terminal_resolve_recovery(
        self, state: Mapping[str, object], intent: TerminalCommitIntentV1
    ) -> object:
        run_id = cast(str, state["run_id"])
        with self._unit_of_work_factory() as unit_of_work:
            context = unit_of_work.recovery_contexts.load_current_context(run_id)
        if context is None:
            raise RuntimeError("terminal recovery requires current RecoveryContextV1")
        resolution = {
            "RECOVERY_ACCEPT_PARTIAL": RecoveryResolution.ACCEPT_PARTIAL,
            "RECOVERY_CANCEL": RecoveryResolution.CANCEL,
            "RECOVERY_FAIL": RecoveryResolution.FAIL,
        }.get(intent["kind"])
        if resolution is None:
            raise ValueError("terminal recovery kind is invalid")
        payload = self._terminal_command_payload(run_id, intent)
        action_id = context.get("action_id")
        return self._resolve_recovery(
            ResolveRecoveryCommandV1(
                run_id=run_id,
                expected_version=intent["expected_run_version"],
                command_id=self._terminal_command_id(payload),
                request_hash=calculate_canonical_json_hash(payload),
                recovery_context_version=int(context["version"]),
                resolution=resolution,
                target_kind=cast(Literal["RUN", "ACTION"], context["scope"]),
                target_action_id=None if action_id is None else str(action_id),
            )
        )

    def _emit_terminal_finalize_trace(self, facts: Mapping[str, object]) -> object:
        run_id = cast(str, facts["run_id"])
        return self._emit_terminal_trace(
            EmitTraceEventCommand(
                correlation=ObservabilityContext(
                    service_instance_id=self._service_instance_id,
                    run_id=run_id,
                    conversation_id=cast(str, facts["conversation_id"]),
                ),
                event_name="workflow.finalized",
                event_category=EventCategory.WORKFLOW,
                occurred_at_ms=self._now_ms(),
                severity=Severity.INFO,
                component="langgraph-finalize",
                attributes={
                    "run_status": facts["status"],
                    "run_version": facts["version"],
                    "result_kind": facts["terminal_result_kind"],
                },
                result_code="TERMINAL_COMMITTED",
                status=cast(str, facts["status"]),
            )
        )

    def _project_terminal_finalize_event(self, facts: Mapping[str, object]) -> object:
        if self._project_terminal_event is None:
            return None
        status = cast(str, facts["status"])
        return self._project_terminal_event(
            ProjectRunEventCommand(
                run_id=cast(str, facts["run_id"]),
                occurred_at_ms=self._now_ms(),
                event_type="error" if status == "FAILED" else "completed",
                payload={
                    "run_status": status,
                    "run_version": facts["version"],
                    "result_kind": facts["terminal_result_kind"],
                },
            )
        )

    @staticmethod
    def _terminal_command_payload(run_id: str, intent: TerminalCommitIntentV1) -> dict[str, object]:
        return {
            "run_id": run_id,
            "expected_run_version": intent["expected_run_version"],
            "kind": intent["kind"],
        }

    @staticmethod
    def _terminal_command_id(payload: dict[str, object]) -> str:
        return f"terminal:{calculate_canonical_json_hash(payload)}"

    def _prepare_current_persisted_review_state(self, state: Mapping[str, object]) -> GraphState:
        plan_id = self._required_string(state.get("approved_plan_id"), "approved_plan_id")
        with self._unit_of_work_factory() as unit_of_work:
            plan = load_plan_record(unit_of_work.plans, plan_id)
        if plan is None:
            raise LookupError(f"plan not found: {plan_id}")
        return self._prepare_modify_review_state(
            cast(GraphState, state),
            plan_id=plan_id,
            review_version=plan.review_version,
        )

    def _build_graph(self) -> Any:
        return self._graph_composition.build()

    def _edge_map(self) -> dict[Hashable, str]:
        return cast(dict[Hashable, str], self._graph_composition.edge_map())

    def _initial_state(self, request: WorkflowStartRequest) -> GraphState:
        return initial_graph_state(
            request,
            graph_profile=self._graph_profile,
            graph_version=RESUME_CONTRACT_VERSION,
            initial_target=self._topology[0],
        )

    def describe_topology(self) -> tuple[str, ...]:
        return self._topology

    def graph_profile(self) -> GraphProfile:
        return self._graph_profile

    def _topology_for_profile(self) -> tuple[str, ...]:
        return self._route_translator.topology()

    def _node_handler(self, name: str) -> Any:
        return self._graph_composition.node_handler(name)

    def _native_subgraphs_for_profile(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._graph_composition.native_subgraphs())

    def _validate_domain_and_project(self, state: Mapping[str, object]) -> GraphState:
        typed_state = cast(GraphState, state)
        original_state = typed_state
        planning_result = typed_state.get("planning_result")
        if (
            isinstance(planning_result, Mapping)
            and planning_result.get("schema_version") == 2
            and isinstance(planning_result.get("meta"), Mapping)
        ):
            run_id = self._required_string(typed_state.get("run_id"), "run_id")
            retrieval_result = _require_state_value(
                typed_state.get("retrieval_result"), "retrieval_result"
            )
            evidence_drafts = list(
                resolve_evidence_projection(
                    store=self._evidence_store,
                    run_id=run_id,
                    retrieval_result=retrieval_result,
                )
            )
            with self._unit_of_work_factory() as unit_of_work:
                resource_refs = {
                    _resource_handle_for_ref(item): item
                    for item in unit_of_work.resource_refs.list_for_run_bounded(run_id, limit=1000)
                }
            acquisition_result = typed_state.get("acquisition_result")
            for draft in evidence_drafts:
                handle = draft.get("resource_handle")
                if not isinstance(handle, str) or handle in resource_refs:
                    continue
                acquired = (
                    _acquired_resource_by_handle(
                        acquisition_result=cast(Any, acquisition_result),
                        resource_handle=handle,
                    )
                    if isinstance(acquisition_result, Mapping)
                    else None
                )
                if acquired is None:
                    resource_type, separator, resource_id = handle.partition(":")
                    if not separator or not resource_id:
                        continue
                    parent_id: str | None = None
                    raw_actions = cast(Mapping[str, object], planning_result).get("actions", [])
                    for action in cast(list[Mapping[str, object]], raw_actions):
                        if draft.get("evidence_id") not in cast(
                            list[object], action.get("evidence_refs", [])
                        ):
                            continue
                        arguments = action.get("arguments")
                        if isinstance(arguments, Mapping):
                            parent_field = (
                                "task_list_id"
                                if resource_type == "task"
                                else "calendar_id"
                                if resource_type == "calendar_event"
                                else None
                            )
                            if parent_field is not None:
                                parent_id = cast(str | None, arguments.get(parent_field))
                        break
                    acquired = {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "parent_id": parent_id,
                        "payload": {},
                    }
                payload = cast(dict[str, object], acquired["payload"])
                resource_refs[handle] = ResourceRefRecord(
                    id=f"projection-{run_id}-{handle.replace(':', '-')}",
                    run_id=run_id,
                    connector_id=_connector_id_for_evidence_handle(
                        state=typed_state,
                        resource_handle=handle,
                    ),
                    resource_type=str(acquired["resource_type"]),
                    resource_id=str(acquired["resource_id"]),
                    parent_resource_id=cast(str | None, acquired.get("parent_id")),
                    canonical_url=None,
                    title=str(
                        payload.get("subject") or payload.get("title") or acquired["resource_id"]
                    )[:200],
                    event_time_ms=None,
                    version_token=cast(str | None, acquired.get("version")),
                    metadata_json=dumps(payload, sort_keys=True),
                    captured_at_ms=self._now_ms(),
                )
            plan_review = _require_state_value(typed_state.get("plan_review"), "plan_review")
            resource_identity_reader = _ResourceIdentityProjection(resource_refs)
            result = self._canonical_domain_validation(
                run_id=run_id,
                planning_result=cast(Any, planning_result),
                plan_review=cast(PlanReviewResultV2, plan_review),
                work_analysis_result=typed_state.get("work_analysis_result"),
                evidence_drafts=evidence_drafts,
                policy_confirmation_receipts=typed_state.get("policy_confirmation_receipts", []),
                resource_identity_reader=resource_identity_reader,
            )
        else:
            raise ValueError(
                "DOMAIN_VALIDATION requires canonical PlanningResultV2; "
                "non-canonical planning channels are not accepted"
            )
        decision = route_supervisor(
            phase=WorkflowPhase.DOMAIN_VALIDATION,
            state=cast(GraphState, typed_state),
            result=result,
        )
        is_modify_review = typed_state.get("__modify_review_plan_id__") is not None
        if is_modify_review:
            review_status = (
                PlanReviewStatus.PASSED
                if result["result"] == DomainValidationResult.REQUIRE_APPROVAL.value
                else PlanReviewStatus.REQUIRED
            )
            if not self._store_modify_review_result(
                typed_state,
                review_status,
                "PASS" if review_status is PlanReviewStatus.PASSED else "BLOCK",
            ):
                return {
                    **typed_state,
                    "__target__": "end",
                    "__workflow_control__": _workflow_control("STALE_MODIFY_REVIEW"),
                }
            if review_status is PlanReviewStatus.PASSED:
                decision["target"] = SupervisorTarget.WAITING_APPROVAL.value
                decision["state_update"] = {
                    **decision["state_update"],
                    "approved_plan_id": typed_state["__modify_review_plan_id__"],
                }
        elif result["result"] == DomainValidationResult.REQUIRE_APPROVAL.value:
            plan_id = cast(PlanPersistenceMixin, self)._persist_write_plan(
                typed_state,
                cast(ActionPlanDraftV2, planning_result),
                resource_identity_reader,
            )
            decision["target"] = SupervisorTarget.WAITING_APPROVAL.value
            decision["state_update"] = {
                **decision["state_update"],
                "approved_plan_id": plan_id,
            }
        merged = self._merge_decision(
            typed_state,
            {"workflow_phase": WorkflowPhase.DOMAIN_VALIDATION.value},
            decision,
        )
        return cast(
            GraphState,
            {key: value for key, value in merged.items() if original_state.get(key) != value},
        )

    def _waiting_approval_node(self, state: GraphState) -> GraphState:
        plan_id = cast(str | None, state.get("approved_plan_id"))
        payload = {
            "interrupt_kind": "APPROVAL",
            "run_id": state["run_id"],
            "plan_id": plan_id,
        }
        resume_payload = interrupt(payload)
        if (
            isinstance(resume_payload, dict)
            and resume_payload.get("resume_kind") == "MODIFY_REVIEW"
        ):
            return self._prepare_modify_review_state(
                state,
                plan_id=self._required_string(resume_payload.get("plan_id"), "plan_id"),
                review_version=int(resume_payload.get("review_version", -1)),
            )
        if self._current_run_status(cast(str, state["run_id"])) in {
            RunStatusV1.COMPLETED.value,
            RunStatusV1.BLOCKED.value,
            RunStatusV1.FAILED.value,
            RunStatusV1.CANCELLED.value,
        }:
            return {
                **state,
                "__target__": "response_synthesis",
                "__logical_target__": "response_synthesis",
            }
        return {
            **state,
            "__target__": "preflight",
            "workflow_phase": WorkflowPhase.PREFLIGHT.value,
        }

    def _prepare_modify_review_state(
        self,
        state: GraphState,
        *,
        plan_id: str,
        review_version: int,
    ) -> GraphState:
        with self._unit_of_work_factory() as unit_of_work:
            plan = load_plan_record(unit_of_work.plans, plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {plan_id}")
            if (
                plan.review_status is not PlanReviewStatus.REQUIRED
                or plan.review_version != review_version
            ):
                return {
                    **state,
                    "__target__": "end",
                    "__workflow_control__": _workflow_control("STALE_MODIFY_REVIEW"),
                }
            bundle = unit_of_work.plans.load_bundle(plan_id)
            if bundle is None:
                raise LookupError(f"plan not found: {plan_id}")
            actions = bundle.actions
            dependencies = project_dependency_ids(bundle)

        # G3 RunBudgetV2 (docs/06 SS11, docs/15 SS8.2): mandatory Modify
        # Review re-invokes Review with one more real Provider call because
        # the user's edit invalidated the prior PASS -- that re-review call
        # is itself the Domain safety gate Approval cannot proceed without,
        # so it is authorized before it runs. Reuses approve_planning_revision
        # directly (same planning_revisions_used counter and REVISION_HEAVY
        # promotion a Review-REVISE-triggered revision gets) instead of a
        # separate counter/rule -- Modify Review and Review REVISE both
        # consume the same Run-level "how many times was this plan revised"
        # budget.
        budget = approve_planning_revision(state["retry_budget"])
        if budget["decision"] == BudgetDecision.DENY.value:
            return {
                **state,
                "__target__": "end",
                "__workflow_control__": _workflow_control("MODIFY_REVIEW_BUDGET_EXHAUSTED"),
            }

        draft = deepcopy(
            cast(
                ActionPlanDraftV2,
                _require_state_value(state["planning_result"], "planning_result"),
            )
        )
        draft_actions = draft.get("actions")
        ordered_actions = sorted(actions, key=lambda item: item.position)
        if not isinstance(draft_actions, list) or len(draft_actions) != len(ordered_actions):
            raise ValueError("persisted Plan no longer matches the Planning artifact")
        for action_draft, action in zip(draft_actions, ordered_actions, strict=True):
            if action_draft.get("tool_id") != action.tool_name:
                raise ValueError("persisted Action tool no longer matches Planning")
            action_draft["action_id"] = action.id
            action_draft["arguments"] = cast(dict[str, object], loads(action.arguments_json))
            action_draft["depends_on_action_ids"] = list(dependencies[action.id])

        return {
            **state,
            "planning_result": draft,
            "plan_review": None,
            "approved_plan_id": plan_id,
            "__modify_review_plan_id__": plan_id,
            "__modify_review_version__": review_version,
            "__modify_review_risks__": {action.id: action.risk for action in actions},
            "__target__": "review_entry",
            "__logical_target__": "review_entry",
            "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
            "retry_budget": budget["run_budget"],
        }

    def _settle_persisted_review(self, state: Mapping[str, object]) -> GraphState:
        reviewed = cast(GraphState, state)
        reviewed = {
            **reviewed,
            "__modify_review_plan_id__": cast(str | None, state["__modify_review_plan_id__"]),
            "__modify_review_version__": cast(int | None, state["__modify_review_version__"]),
            "__modify_review_risks__": cast(
                dict[str, dict[str, object]] | None,
                state["__modify_review_risks__"],
            ),
        }

        route_reconsideration_signal = reviewed.get("workflow_signal")
        if (
            reviewed.get("plan_review") is None
            and isinstance(route_reconsideration_signal, dict)
            and route_reconsideration_signal.get("kind") == "ROUTE_RECONSIDERATION_REQUIRED"
        ):
            if not self._store_modify_review_result(
                reviewed,
                PlanReviewStatus.REQUIRED,
                ReviewResult.ROUTE_RECONSIDERATION.value,
            ):
                return {
                    **reviewed,
                    "__target__": "end",
                    "__workflow_control__": _workflow_control("STALE_MODIFY_REVIEW"),
                }
            if not self._begin_modify_replan(reviewed):
                return {
                    **reviewed,
                    "__target__": "end",
                    "__workflow_control__": _workflow_control("STALE_MODIFY_REVIEW"),
                }
            reviewed = cast(GraphState, dict(reviewed))
            reviewed["__replan_from_plan_id__"] = cast(str, reviewed["__modify_review_plan_id__"])
            reviewed["__modify_review_plan_id__"] = None
            reviewed["__modify_review_version__"] = None
            reviewed["__modify_review_risks__"] = None
            reviewed["__target__"] = "end"
            reviewed["__workflow_control__"] = _workflow_control(
                "MODIFY_ROUTE_RECONSIDERATION_REPLAN"
            )
            return reviewed

        review = cast(
            PlanReviewResultV2,
            _require_state_value(reviewed["plan_review"], "plan_review"),
        )
        if review["status"] == ReviewResult.PASS.value:
            return reviewed
        if review["status"] == ReviewResult.ROUTE_RECONSIDERATION.value:
            if not self._store_modify_review_result(
                reviewed,
                PlanReviewStatus.REQUIRED,
                ReviewResult.ROUTE_RECONSIDERATION.value,
            ) or not self._begin_modify_replan(reviewed):
                return {
                    **reviewed,
                    "__target__": "end",
                    "__workflow_control__": _workflow_control("STALE_MODIFY_REVIEW"),
                }
            reviewed = cast(GraphState, dict(reviewed))
            reviewed["__replan_from_plan_id__"] = cast(str, reviewed["__modify_review_plan_id__"])
            reviewed["__modify_review_plan_id__"] = None
            reviewed["__modify_review_version__"] = None
            reviewed["__modify_review_risks__"] = None
            reviewed["__target__"] = "end"
            reviewed["__workflow_control__"] = _workflow_control(
                "MODIFY_ROUTE_RECONSIDERATION_REPLAN"
            )
            return reviewed
        if not self._store_modify_review_result(
            reviewed,
            self._review_status(review),
            review["status"],
        ):
            return {
                **reviewed,
                "__target__": "end",
                "__workflow_control__": _workflow_control("STALE_MODIFY_REVIEW"),
            }
        if review["status"] in {
            ReviewResult.REVISE.value,
            ReviewResult.RETRIEVE_MORE.value,
        }:
            if not self._begin_modify_replan(reviewed):
                return {
                    **reviewed,
                    "__target__": "end",
                    "__workflow_control__": _workflow_control("STALE_MODIFY_REVIEW"),
                }
            reviewed = cast(GraphState, dict(reviewed))
            reviewed["__replan_from_plan_id__"] = cast(str, reviewed["__modify_review_plan_id__"])
            reviewed["__modify_review_plan_id__"] = None
            reviewed["__modify_review_version__"] = None
            reviewed["__modify_review_risks__"] = None
        return reviewed

    @staticmethod
    def _review_status(review: PlanReviewResultV2) -> PlanReviewStatus:
        return {
            ReviewResult.REVISE.value: PlanReviewStatus.REQUIRED,
            ReviewResult.RETRIEVE_MORE.value: PlanReviewStatus.REQUIRED,
            ReviewResult.CONFIRM.value: PlanReviewStatus.REQUIRED,
            ReviewResult.BLOCK.value: PlanReviewStatus.REQUIRED,
        }[review["status"]]

    def _store_modify_review_result(
        self,
        state: GraphState,
        review_status: PlanReviewStatus,
        review_disposition: ReviewDispositionV1,
    ) -> bool:
        plan_id = state.get("__modify_review_plan_id__")
        review_version = state.get("__modify_review_version__")
        if plan_id is None or review_version is None:
            return False
        with self._unit_of_work_factory() as unit_of_work:
            plan = load_plan_record(unit_of_work.plans, plan_id)
            if plan is None:
                return False
            action_versions = {
                action.id: action.version for action in unit_of_work.actions.list_for_plan(plan_id)
            }
        result = self._record_review_result(
            RecordReviewResultCommandV1(
                command_id=self._phase_command_id(plan.run_id, "record_review", review_version),
                plan_id=plan.id,
                expected_plan_version=plan.revision_no,
                expected_review_version=review_version,
                review_artifact_id=f"{plan.id}:review:{review_version}",
                review_version=review_version,
                disposition=review_disposition,
                based_on_action_versions=action_versions,
            )
        )
        return bool(result.applied)

    def _begin_modify_replan(self, state: GraphState) -> bool:
        plan_id = state.get("__modify_review_plan_id__")
        review_version = state.get("__modify_review_version__")
        if plan_id is None or review_version is None:
            return False
        with self._unit_of_work_factory() as unit_of_work:
            canonical_uow = cast(CanonicalUnitOfWork, unit_of_work)
            plan = load_plan_record(unit_of_work.plans, plan_id)
            if plan is None or plan.review_version != review_version:
                return False
            run = canonical_uow.runs.get(plan.run_id)
            if run is None:
                return False
        result = self._begin_planning_handler(
            BeginPlanningCommand(
                run_id=plan.run_id,
                expected_version=run.version,
                command_id=self._phase_command_id(
                    plan.run_id, "published_review_begin_planning", run.version
                ),
                request_hash=self._request_hash(
                    {
                        "kind": "published_review_begin_planning",
                        "plan_id": plan.id,
                        "review_version": review_version,
                    }
                ),
                plan_id=plan.id,
                expected_review_version=review_version,
            )
        )
        return bool(result.applied)

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        decision_state = decision["state_update"]
        merged: GraphState = {**state, **update, **decision_state}
        merged["prompt_context"] = {
            **state.get("prompt_context", {}),
            **update.get("prompt_context", {}),
            **decision_state.get("prompt_context", {}),
        }
        merged["trace_context"] = {
            **state.get("trace_context", {}),
            **update.get("trace_context", {}),
            **decision_state.get("trace_context", {}),
        }
        try:
            translation = self._route_translator.translate(cast(str, decision["target"]))
        except UnroutableSupervisorTargetError:
            # Fail-closed: an unmapped Supervisor target must never silently
            # fall through to a normal "end" termination. Route into
            # Recovery the same way Supervisor itself already handles an
            # unrecognized contract (see supervisor.py's
            # TOOL_ROUTE_CONTRACT_VIOLATION handling) -- "recovery" is
            # always mapped for every profile, so this cannot recurse.
            merged["__workflow_control__"] = _workflow_control("CONTRACT_VIOLATION")
            merged["workflow_phase"] = WorkflowPhase.RECOVERY.value
            merged["__logical_target__"] = "recovery"
            merged["__target__"] = "recovery"
            return merged
        merged["__logical_target__"] = translation.logical_target
        merged["__target__"] = translation.node
        return merged

    def _request_from_state(self, state: GraphState) -> WorkflowStartRequest:
        return request_from_state(state)

    def _config_for_thread(self, workflow_key: str) -> dict[str, object]:
        return self._invocation.config_for_thread(workflow_key)

    def _workflow_result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        return self._invocation.workflow_result_from_state(
            state=state,
            workflow_key=workflow_key,
            run_id=run_id,
        )

    def _result_from_thread(self, *, workflow_key: str, run_id: str) -> WorkflowInvocationResult:
        return self._invocation.result_from_thread(workflow_key=workflow_key, run_id=run_id)

    def _result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        return self._invocation.result_from_state(
            state=state,
            workflow_key=workflow_key,
            run_id=run_id,
        )

    def _is_profile_compatible(self, state: GraphState) -> bool:
        return self._invocation.is_profile_compatible(state)

    def _calendar_plan_risk(self, *, state: GraphState, action: Any) -> dict[str, object]:
        arguments = cast(dict[str, object], action["arguments"])
        acquisition = _require_state_value(state["acquisition_result"], "acquisition_result")
        checked_at_ms = self._now_ms()
        conflict = evidence_calendar_conflict_risk(
            arguments=arguments,
            acquisition_result=acquisition,
            checked_at_ms=checked_at_ms,
            work_hours=self._work_hours_provider(),
        )
        feasibility = evidence_feasibility_risk(
            arguments=arguments,
            analysis_result=cast(Mapping[str, object], state.get("work_analysis_result") or {}),
            acquisition_result=acquisition,
            checked_at_ms=checked_at_ms,
            work_hours=self._work_hours_provider(),
        )
        return {**conflict, **feasibility}

    def _start_analysis_for_main(self, run_id: str) -> Any:
        return self._apply_run_transition(run_id, "start_analysis")

    def _begin_retrieval_for_main(self, run_id: str) -> Any:
        return self._apply_run_transition(run_id, "begin_retrieval")

    def _begin_planning_for_main(self, run_id: str) -> Any:
        return self._apply_run_transition(run_id, "begin_planning")

    def _transition_run(self, run_id: str, transition_name: str) -> None:
        expected_status = {
            "start_analysis": RunStatusV1.ANALYZING.value,
            "begin_retrieval": RunStatusV1.RETRIEVING.value,
            "begin_planning": RunStatusV1.PLANNING.value,
        }.get(transition_name)
        if expected_status is None:
            raise ValueError(f"unsupported Run transition callback: {transition_name}")
        if self._current_run_status(run_id) == expected_status:
            return
        result = self._apply_run_transition(run_id, transition_name)
        if not result.applied and result.current_status not in {
            RunStatusV1.ANALYZING.value,
            RunStatusV1.RETRIEVING.value,
            RunStatusV1.PLANNING.value,
        }:
            raise RuntimeError(
                f"{transition_name} rejected for Run {run_id}: {result.conflict_detail}"
            )

    def _apply_run_transition(self, run_id: str, transition_name: str) -> Any:
        with self._unit_of_work_factory() as unit_of_work:
            canonical_uow = cast(CanonicalUnitOfWork, unit_of_work)
            run = canonical_uow.runs.get(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
        result: Any
        if transition_name == "start_analysis":
            if run.status in {
                RunStatusV1.ANALYZING,
                RunStatusV1.RETRIEVING,
                RunStatusV1.PLANNING,
            }:
                return self._start_analysis_handler(
                    StartAnalysisCommand(
                        run_id=run_id,
                        expected_version=run.version,
                        command_id=self._phase_command_id(run_id, transition_name, run.version),
                        request_hash=self._request_hash(
                            {
                                "kind": "start_analysis",
                                "run_id": run_id,
                                "version": run.version,
                            }
                        ),
                    )
                )
            result = self._start_analysis_handler(
                StartAnalysisCommand(
                    run_id=run_id,
                    expected_version=run.version,
                    command_id=self._phase_command_id(run_id, transition_name, run.version),
                    request_hash=self._request_hash(
                        {"kind": "start_analysis", "run_id": run_id, "version": run.version}
                    ),
                )
            )
        elif transition_name == "begin_retrieval":
            if run.status is RunStatusV1.RETRIEVING:
                return self._begin_retrieval_handler(
                    BeginRetrievalCommand(
                        run_id=run_id,
                        expected_version=run.version,
                        command_id=self._phase_command_id(run_id, transition_name, run.version),
                        request_hash=self._request_hash(
                            {
                                "kind": "begin_retrieval",
                                "run_id": run_id,
                                "version": run.version,
                            }
                        ),
                    )
                )
            result = self._begin_retrieval_handler(
                BeginRetrievalCommand(
                    run_id=run_id,
                    expected_version=run.version,
                    command_id=self._phase_command_id(run_id, transition_name, run.version),
                    request_hash=self._request_hash(
                        {"kind": "begin_retrieval", "run_id": run_id, "version": run.version}
                    ),
                )
            )
        elif transition_name == "begin_planning":
            if run.status is RunStatusV1.PLANNING:
                return self._begin_planning_handler(
                    BeginPlanningCommand(
                        run_id=run_id,
                        expected_version=run.version,
                        command_id=self._phase_command_id(run_id, transition_name, run.version),
                        request_hash=self._request_hash(
                            {
                                "kind": "begin_planning",
                                "run_id": run_id,
                                "version": run.version,
                            }
                        ),
                    )
                )
            result = self._begin_planning_handler(
                BeginPlanningCommand(
                    run_id=run_id,
                    expected_version=run.version,
                    command_id=self._phase_command_id(run_id, transition_name, run.version),
                    request_hash=self._request_hash(
                        {"kind": "begin_planning", "run_id": run_id, "version": run.version}
                    ),
                )
            )
        else:
            raise ValueError(f"unsupported Run transition callback: {transition_name}")
        return result

    @staticmethod
    def _phase_command_id(run_id: str, operation: str, expected_version: int) -> str:
        identity = dumps(
            {
                "expected_version": expected_version,
                "operation": operation,
                "run_id": run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"run-phase-{sha256(identity.encode('utf-8')).hexdigest()}"

    def _current_run_status(self, run_id: str) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            canonical_uow = cast(CanonicalUnitOfWork, unit_of_work)
            run = canonical_uow.runs.get(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            return run.status.value

    def _current_run_version(self, run_id: str) -> int:
        with self._unit_of_work_factory() as unit_of_work:
            canonical_uow = cast(CanonicalUnitOfWork, unit_of_work)
            run = canonical_uow.runs.get(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            return run.version

    def _list_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return tuple(
                sorted(unit_of_work.actions.list_for_plan(plan_id), key=lambda item: item.position)
            )

    def _execute_read_only_plan(
        self,
        state: GraphState,
        plan_id: str,
        actions: tuple[ActionRecord, ...],
    ) -> GraphState:
        """Execute the persisted compatibility READ lifecycle without Write facts."""

        run_id = cast(str, state["run_id"])
        for action in actions:
            if action.status in {
                ActionStatusV1.VERIFIED.value,
                ActionStatusV1.FAILED.value,
            }:
                continue
            if self._should_stop_for_cancel(run_id):
                return cast(
                    GraphState,
                    {
                        **state,
                        "__target__": "cancel_resolution",
                        "__logical_target__": "cancel_resolution",
                        "workflow_phase": "CANCEL_RESOLUTION",
                    },
                )
            action_version = action.version
            if action.status == ActionStatusV1.PROPOSED.value:
                claimed = self._claim_read(
                    ClaimReadActionCommand(
                        command_id=self._id_factory(),
                        request_hash=self._request_hash(
                            {"kind": "claim_read", "action_id": action.id}
                        ),
                        action_id=action.id,
                        expected_version=action.version,
                    )
                )
                if not claimed.applied:
                    continue
                action_version = claimed.action_version
            elif action.status != ActionStatusV1.EXECUTING.value:
                raise RuntimeError(f"legacy READ action has invalid status: {action.status}")
            try:
                executed = self._execute_read(action_id=action.id)
            except GoogleWorkspaceGatewayError as error:
                self._fail_read(
                    FailReadActionCommand(
                        command_id=self._id_factory(),
                        request_hash=self._request_hash(
                            {"kind": "fail_read", "action_id": action.id}
                        ),
                        action_id=action.id,
                        expected_version=action_version,
                        safe_error_code=error.code.value,
                        retryable=False,
                        safe_error_detail=str(error),
                    )
                )
                continue
            completed = self._complete_read(
                CompleteReadActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "complete_read", "action_id": action.id}
                    ),
                    action_id=action.id,
                    expected_version=action_version,
                    output_json=executed.output_json,
                    resource_refs=executed.resource_refs,
                    evidence=executed.evidence,
                )
            )
            if not completed.applied:
                raise RuntimeError(f"complete legacy READ failed: {completed.result_code}")
            finalized = self._finalize_read(
                FinalizeReadActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "finalize_read", "action_id": action.id}
                    ),
                    action_id=action.id,
                    expected_version=completed.action_version,
                )
            )
            if not finalized.applied:
                raise RuntimeError(f"finalize legacy READ failed: {finalized.result_code}")
        current_actions = self._list_actions(plan_id)
        if any(
            action.status
            not in {
                ActionStatusV1.VERIFIED.value,
                ActionStatusV1.FAILED.value,
            }
            for action in current_actions
        ):
            return cast(
                GraphState,
                {
                    **state,
                    "__target__": "domain_reconcile",
                    "__logical_target__": "domain_reconcile",
                    "workflow_phase": WorkflowPhase.READ_EXECUTION.value,
                },
            )
        return cast(
            GraphState,
            {
                **state,
                "__target__": "response_synthesis",
                "__logical_target__": "response_synthesis",
                "workflow_phase": WorkflowPhase.RESPONSE_SYNTHESIS.value,
                "__workflow_control__": _workflow_control(
                    "READ_RUN_COMPLETABLE",
                    plan_id=plan_id,
                    action_statuses=[action.status for action in current_actions],
                ),
            },
        )

    def _has_independent_executable_action(self, plan_id: str, failed_action_id: str) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            return any(
                action.id != failed_action_id
                and action.status == ActionStatusV1.APPROVED.value
                and unit_of_work.actions.is_dependency_ready(action.id)
                for action in unit_of_work.actions.list_for_plan(plan_id)
            )

    def continue_graphless_bootstrap_cancel(
        self, command: ContinueCancelResolutionCommandV1
    ) -> ContinueCancelResolutionResultV1:
        """Advance cancellation when no durable workflow handoff exists yet."""

        result = cast(ContinueCancelResolutionResultV1, self._continue_cancel_resolution(command))
        if result.outcome != "READY_TO_FINALIZE":
            return result
        run_version = self._current_run_version(command.run_id)
        payload = {
            "kind": "graphless_bootstrap_cancel",
            "run_id": command.run_id,
            "expected_run_version": run_version,
        }
        finalized = self._finalize_cancel(
            FinalizeCancelCommand(
                command_id=f"system:cancel-resolution:finalize:{command.run_id}:{run_version}",
                request_hash=calculate_canonical_json_hash(payload),
                run_id=command.run_id,
                expected_run_version=run_version,
            )
        )
        return ContinueCancelResolutionResultV1(
            1,
            "FINALIZED" if finalized.applied else "WAITING_FOR_SETTLEMENT",
            finalized.run_status,
        )

    def _continue_cancel_resolution_for_main(self, run_id: str) -> dict[str, object]:
        result = self._continue_cancel_resolution(ContinueCancelResolutionCommandV1(1, run_id))
        if result.outcome in {"READY_TO_FINALIZE", "FINALIZED"}:
            target = "response_synthesis"
        elif result.outcome == "PROGRESSED":
            target = "cancel_resolution"
        else:
            target = "end"
        return {
            "__target__": target,
            "__logical_target__": target,
            "workflow_phase": "CANCEL_RESOLUTION",
            "__workflow_control__": {
                "schema_version": 1,
                "stage": "CANCEL_RESOLUTION",
                "reason": result.outcome,
                "run_status": result.run_status,
                "progressed_action_id": result.progressed_action_id,
            },
        }

    def _settle_pending_cancel_action(self, action_id: str, version: int) -> bool:
        payload = {"action_id": action_id, "expected_version": version}
        return bool(
            self._cancel_pending_action(
                CancelPendingActionCommand(
                    command_id=f"system:cancel-resolution:action:{action_id}:{version}",
                    request_hash=calculate_canonical_json_hash(payload),
                    action_id=action_id,
                    expected_version=version,
                )
            ).applied
        )

    def _reconcile_cancelling_action(self, action_id: str) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
        if action is None:
            return False
        if action.effect_type == "READ":
            failed = self._fail_read(
                FailReadActionCommand(
                    command_id=f"system:cancel-resolution:read:{action.id}:{action.version}",
                    request_hash=calculate_canonical_json_hash(
                        {"action_id": action.id, "expected_version": action.version}
                    ),
                    action_id=action.id,
                    expected_version=action.version,
                    safe_error_code="CANCEL_REQUESTED",
                    retryable=False,
                    safe_error_detail="cancel intent forbids a new legacy READ dispatch",
                )
            )
            return bool(failed.applied)
        attempt = self._latest_attempt(action_id)
        if attempt.status is not ExecutionAttemptStatusV1.CLAIMED:
            return False
        payload = {
            "action_id": action.id,
            "attempt_id": attempt.id,
            "expected_action_version": action.version,
            "expected_attempt_version": attempt.version,
            "error_code": "CANCEL_REQUESTED",
            "error_detail": "write was not sent because cancellation was requested",
        }
        return bool(
            self._abort_claimed_execution(
                AbortClaimedExecutionCommandV1(
                    command_id=f"system:cancel-resolution:abort:{attempt.id}:{attempt.version}",
                    request_hash=calculate_canonical_json_hash(payload),
                    action_id=action.id,
                    attempt_id=attempt.id,
                    expected_action_version=action.version,
                    expected_attempt_version=attempt.version,
                    error_code="CANCEL_REQUESTED",
                    error_detail="write was not sent because cancellation was requested",
                )
            ).applied
        )

    def _verify_cancelling_action(self, action_id: str) -> bool:
        action, run_id = self._action_and_run_id(action_id)
        attempt_id = self._latest_attempt_id(action.id)
        if self._current_run_status(run_id) == RunStatusV1.CANCEL_REQUESTED.value:
            begun = self._begin_write_verification(
                BeginVerificationCommand(
                    command_id=f"system:cancel-resolution:begin-verification:{run_id}",
                    request_hash=calculate_canonical_json_hash(
                        {
                            "kind": "cancel_begin_verification",
                            "run_id": run_id,
                            "action_id": action.id,
                            "execution_attempt_id": attempt_id,
                        }
                    ),
                    run_id=run_id,
                    action_id=action.id,
                    execution_attempt_id=attempt_id,
                )
            )
            if not begun.applied:
                return False
        try:
            verified = self._write_execution_phase.verify_executed(
                action_id=action.id,
                action_version=action.version,
                attempt_id=attempt_id,
                request_kind="cancel_verification",
            )
        except GoogleWorkspaceGatewayError:
            return False
        return verified.applied

    def _resolve_cancelling_unknown_action(self, action_id: str) -> bool:
        action, run_id = self._action_and_run_id(action_id)
        attempt = self._latest_attempt(action_id)
        response = self._write_execution_phase.recover_unknown(
            UnknownRecoveryPhaseRequest(
                run_id=run_id,
                action_id=action.id,
                effect_type=action.effect_type,
                action_version=action.version,
                attempt_id=attempt.id,
                attempt_version=attempt.version,
            ),
            allow_reauth=False,
        )
        return response.applied

    def _action_and_run_id(self, action_id: str) -> tuple[ActionRecord, str]:
        with self._unit_of_work_factory() as unit_of_work:
            action = unit_of_work.actions.get(action_id)
            plan = None if action is None else load_plan_record(unit_of_work.plans, action.plan_id)
        if action is None or plan is None:
            raise LookupError(f"action/plan not found: {action_id}")
        return action, plan.run_id

    def _plans_for_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return current_plan_tuple(unit_of_work.plans, run_id)

    def _has_executed_action(self, run_id: str) -> bool:
        return any(
            action.status == ActionStatusV1.EXECUTED.value
            for plan in self._plans_for_run(run_id)
            for action in self._list_actions(plan.id)
        )

    def _latest_attempt_id(self, action_id: str) -> str:
        return self._latest_attempt(action_id).id

    def _latest_attempt(self, action_id: str) -> ExecutionAttemptRecord:
        with self._unit_of_work_factory() as unit_of_work:
            attempt = latest_attempt_for_action(unit_of_work, action_id)
            if attempt is None:
                raise LookupError(f"execution attempt not found for action: {action_id}")
            return attempt

    def _mark_stalled_claims_as_unknown(self, run_id: str) -> bool:
        # A CLAIMED attempt has not crossed BeginExecutionAttempt, so provider
        # dispatch is proven to be zero and the durable claim can be aborted.
        marked_any = False
        for plan in self._plans_for_run(run_id):
            for action in self._list_actions(plan.id):
                if action.status != ActionStatusV1.EXECUTING.value:
                    continue
                attempt = self._latest_attempt(action.id)
                if attempt.status != ExecutionAttemptStatusV1.CLAIMED.value:
                    continue
                error_detail = "process restarted before BeginExecutionAttempt committed"
                response = self._abort_claimed_execution(
                    AbortClaimedExecutionCommandV1(
                        command_id=self._id_factory(),
                        request_hash=calculate_canonical_json_hash(
                            {
                                "action_id": action.id,
                                "attempt_id": attempt.id,
                                "expected_action_version": action.version,
                                "expected_attempt_version": attempt.version,
                                "error_code": "PROCESS_RESTART_BEFORE_BEGIN",
                                "error_detail": error_detail,
                            }
                        ),
                        action_id=action.id,
                        attempt_id=attempt.id,
                        expected_action_version=action.version,
                        expected_attempt_version=attempt.version,
                        error_code="PROCESS_RESTART_BEFORE_BEGIN",
                        error_detail=error_detail,
                    )
                )
                marked_any = marked_any or response.applied
        return marked_any

    def _write_run_completion_ready(self, plan_id: str, run_id: str) -> bool:
        if self._has_persisted_cancel_intent(run_id):
            return False
        actions = self._list_actions(plan_id)
        return write_action_statuses_are_closed([action.status for action in actions])

    def _should_stop_for_cancel(self, run_id: str) -> bool:
        with self._cancel_signal_lock:
            if run_id in self._cancel_signals:
                return True
        return self._current_run_status(
            run_id
        ) == RunStatusV1.CANCEL_REQUESTED.value or self._has_persisted_cancel_intent(run_id)

    def _latest_unknown_action(self, run_id: str) -> tuple[ActionRecord, str, int] | None:
        with self._unit_of_work_factory() as unit_of_work:
            plans = current_plan_tuple(unit_of_work.plans, run_id)
            if not plans:
                return None
            latest_plan = sorted(plans, key=lambda item: (item.revision_no, item.created_at_ms))[-1]
            for action in unit_of_work.actions.list_for_plan(latest_plan.id):
                if action.status != ActionStatusV1.UNKNOWN_RESULT.value:
                    continue
                approvals = unit_of_work.approvals.list_for_action(action.id)
                for approval in sorted(approvals, key=lambda item: item.approval_no, reverse=True):
                    attempts = active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
                    if not attempts:
                        continue
                    latest_attempt = sorted(attempts, key=lambda item: item.attempt_no)[-1]
                    return action, latest_attempt.id, latest_attempt.version
        return None

    def _request_with_confirmation(
        self,
        request: WorkflowStartRequest,
        resume_payload: dict[str, object],
    ) -> WorkflowStartRequest:
        del resume_payload
        return WorkflowStartRequest(
            run_id=request.run_id,
            conversation_id=request.conversation_id,
            workflow_key=request.workflow_key,
            entry_mode=request.entry_mode,
            requested_mode=request.requested_mode,
            request_text=request.request_text,
            selected_resource_ids=request.selected_resource_ids,
            run_budget=dict(request.run_budget),
            correlation=request.correlation,
            selected_resources=request.selected_resources,
        )

    def _required_string(self, value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} is required")
        return value

    def _request_hash(self, payload: dict[str, object]) -> str:
        return sha256(dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _workflow_control(reason: str, **details: object) -> dict[str, object]:
    """Project deterministic control diagnostics without forging Domain facts."""

    return {
        "schema_version": 1,
        "stage": "MAIN_CONTROL",
        "reason": reason,
        **details,
    }


class LangGraphWorkflowRuntime(
    ResumeCheckpointMixin,
    ArtifactFreshnessMixin,
    ResponseSynthesisMixin,
    PlanPersistenceMixin,
    ConfirmationControllerMixin,
    _WorkflowRuntimeComposition,
):
    """Single concrete production authority for the LangGraph workflow."""


__all__ = ["LangGraphWorkflowRuntime"]
