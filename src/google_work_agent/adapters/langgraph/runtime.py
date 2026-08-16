"""Concrete Stage 17 workflow runtime assembled on LangGraph."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Hashable
from copy import deepcopy
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from threading import Lock
from typing import Any, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt

from google_work_agent.adapters.connectors import GoogleWorkspaceConnectorReader
from google_work_agent.adapters.langgraph.graph_composition import (
    GraphNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.graph_state import (
    GraphState,
    _acquired_resource_by_handle,
    _require_state_value,
    _resource_handle_for_ref,
    _stored_resource_type_for_acquired_resource,
    initial_graph_state,
    request_from_state,
)
from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.pre_analysis_composition import (
    build_pre_analysis_subgraphs,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.route_translation import (
    GraphRouteTranslator,
    build_resume_target_registry,
)
from google_work_agent.adapters.langgraph.subgraphs.planning import (
    PlanningSubgraph,
    planning_mode_from_request_intent,
)
from google_work_agent.adapters.langgraph.subgraphs.review import ReviewSubgraph
from google_work_agent.adapters.langgraph.subgraphs.single_workflow import (
    SingleWorkflowSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.three_stage import (
    ThreeStageOneSubgraph,
    ThreeStageReviewSubgraph,
    ThreeStageTwoSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis import WorkAnalysisSubgraph
from google_work_agent.adapters.langgraph.write_execution import WriteExecutionNode
from google_work_agent.adapters.langgraph.write_recovery import WriteRecoveryCoordinator
from google_work_agent.application import (
    BlockRunCommand,
    BlockRunService,
    ClaimReadActionCommand,
    ClaimReadActionService,
    CompleteAnswerOnlyRunCommand,
    CompleteAnswerOnlyRunService,
    CompleteReadActionCommand,
    CompleteReadActionService,
    CompleteWriteRunCommand,
    CompleteWriteRunService,
    ExecuteReadActionService,
    FailReadActionCommand,
    FailReadActionService,
    FailRunCommand,
    FailRunService,
    FinalizeReadActionCommand,
    FinalizeReadActionService,
    MarkWriteActionFailedService,
    MarkWriteActionUnknownResultService,
    PreflightWriteActionService,
    PublishReadOnlyPlanCommand,
    PublishReadOnlyPlanService,
    PublishWritePlanCommand,
    PublishWritePlanService,
    ReadActionDraft,
    ReadEvidenceDraft,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionService,
    RequireWriteReauthService,
    SaveReadOnlyPlanCommand,
    SaveReadOnlyPlanService,
    SaveWritePlanCommand,
    SaveWritePlanService,
    StoreWriteActionSuccessService,
    VerifyWriteActionService,
    WriteActionDraft,
    WriteEvidenceDraft,
    derive_finalize_intent,
)
from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    evidence_calendar_conflict_risk,
)
from google_work_agent.application.execution_phase import (
    BeginWriteVerificationService,
    WriteExecutionPhaseCoordinator,
)
from google_work_agent.application.feasibility import evidence_feasibility_risk
from google_work_agent.application.ports import ConnectorExecutionPort
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    evidence_duplicate_risk,
)
from google_work_agent.application.workflows import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    ApiDiscoveryAcquisitionAgent,
    ContextRetrievalAgent,
    DomainValidationResult,
    DomainValidationService,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PlanReviewAgent,
    PlanReviewResultV1,
    RequestUnderstandingAgent,
    ReviewResult,
    SolutionPlanningAgent,
    SupervisorDecisionV1,
    SupervisorTarget,
    ToolRouteAgent,
    WorkAnalysisAgent,
    WorkflowPhase,
    route_supervisor,
)
from google_work_agent.application.workflows.api_acquisition import (
    load_acquisition_plan_sources_prompt_reference,
)
from google_work_agent.application.workflows.profile_fused import (
    load_profile_single_reason_plan_prompt_reference,
    load_profile_single_request_source_prompt_reference,
    load_profile_single_self_review_prompt_reference,
    load_profile_single_self_review_recheck_prompt_reference,
    load_profile_three_stage1_prompt_reference,
    load_profile_three_stage2_prompt_reference,
)
from google_work_agent.application.workflows.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.workflows.retrieval_query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.workflows.retrieval_query_planner import (
    RetrievalQueryPlannerAgent,
)
from google_work_agent.application.workflows.retrieval_read_cache import RunScopedReadResultCache
from google_work_agent.application.workflows.retrieval_read_executor import RetrievalReadExecutor
from google_work_agent.application.write_actions import (
    ClaimWriteActionService,
    ExecuteWriteActionService,
)
from google_work_agent.domain import (
    ActionStatus,
    CalendarWorkHours,
    ConnectorToolCatalog,
    ResultCode,
    RunStatus,
)
from google_work_agent.ports import (
    EvidenceOriginType,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    PlanRecord,
    PlanReviewStatus,
    PromptReference,
    ResourceRefRecord,
    ResourceSource,
    UnitOfWork,
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowRuntime,
    WorkflowStartRequest,
)
from google_work_agent.ports.repositories import ActionRecord

JsonObject = dict[str, object]


class LangGraphWorkflowRuntime(WorkflowRuntime):
    """LangGraph runtime with selectable Stage 18 graph profiles."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        llm_runtime: Any,
        gateway: GoogleWorkspaceGateway,
        connector_execution: ConnectorExecutionPort,
        tool_catalog: ConnectorToolCatalog,
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        signing_secret: str,
        service_instance_id: str,
        checkpoint_database_path: Path,
        graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path: Path | None = None,
        timezone_provider: Callable[[], str] | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._checkpoint_database_path = checkpoint_database_path
        self._graph_profile = graph_profile
        self._route_translator = GraphRouteTranslator(graph_profile)
        self._resume_target_registry = build_resume_target_registry(graph_profile)
        self._work_hours_provider = work_hours_provider or (
            lambda: CalendarWorkHours(timezone=(timezone_provider or (lambda: "Asia/Seoul"))())
        )
        self._default_tasklist_id_provider = default_tasklist_id_provider
        self._cancel_signal_lock = Lock()
        self._cancel_signals: set[str] = set()
        self._checkpoint_database_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = sqlite3.connect(
            self._checkpoint_database_path,
            check_same_thread=False,
        )
        self._checkpointer = SqliteSaver(self._checkpoint_connection)
        self._request_understanding = RequestUnderstandingAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._tool_route_agent = ToolRouteAgent(
            llm_runtime=llm_runtime,
            tool_catalog=tool_catalog,
            manifest_path=prompt_manifest_path,
        )
        self._read_result_cache = RunScopedReadResultCache()
        connector_reader = GoogleWorkspaceConnectorReader(gateway=gateway)
        self._acquisition = ApiDiscoveryAcquisitionAgent(
            llm_runtime=llm_runtime,
            connector_reader=connector_reader,
            manifest_path=prompt_manifest_path,
            now_ms=now_ms,
            timezone_provider=timezone_provider,
        )
        self._context = ContextRetrievalAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._retrieval_query_planner = RetrievalQueryPlannerAgent(
            llm_runtime=llm_runtime,
            prompt_ref=load_acquisition_plan_sources_prompt_reference(prompt_manifest_path),
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            manifest_path=prompt_manifest_path,
        )
        self._retrieval_read_executor = RetrievalReadExecutor(
            connector_reader=connector_reader,
            read_result_cache=self._read_result_cache,
            now_ms=now_ms,
            timezone_provider=timezone_provider or (lambda: "Asia/Seoul"),
        )
        self._evidence_store = RunScopedEvidenceStore()
        self._analysis = WorkAnalysisAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._planning = SolutionPlanningAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._review = PlanReviewAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        # Each non-default graph_profile (SINGLE_BASELINE, THREE_STAGE) is an
        # E06-A architecture-candidate under comparison, not a feature that
        # ships alongside SIX_ROLE_BASELINE (docs/06-agent-workflow.md 1.1,
        # 1.3). Loading a profile's prompt refs/subgraph -- and therefore
        # requiring its RUNTIME_ACTIVE prompts -- only when that profile is
        # the one actually selected keeps an inactive candidate profile's
        # prompts from blocking the product (SIX_ROLE_BASELINE) runtime.
        self._single_request_source_prompt_ref: PromptReference | None = None
        self._single_reason_plan_prompt_ref: PromptReference | None = None
        self._single_review: PlanReviewAgent | None = None
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            self._single_request_source_prompt_ref = (
                load_profile_single_request_source_prompt_reference(prompt_manifest_path)
            )
            self._single_reason_plan_prompt_ref = load_profile_single_reason_plan_prompt_reference(
                prompt_manifest_path
            )
            self._single_review = PlanReviewAgent(
                llm_runtime=llm_runtime,
                inspect_prompt_ref=load_profile_single_self_review_prompt_reference(
                    prompt_manifest_path
                ),
                recheck_prompt_ref=load_profile_single_self_review_recheck_prompt_reference(
                    prompt_manifest_path
                ),
                manifest_path=prompt_manifest_path,
            )
        self._three_stage1_prompt_ref: PromptReference | None = None
        self._three_stage2_prompt_ref: PromptReference | None = None
        if self._graph_profile is GraphProfile.THREE_STAGE:
            self._three_stage1_prompt_ref = load_profile_three_stage1_prompt_reference(
                prompt_manifest_path
            )
            self._three_stage2_prompt_ref = load_profile_three_stage2_prompt_reference(
                prompt_manifest_path
            )
        self._domain_validation = DomainValidationService()

        self._complete_answer_only = CompleteAnswerOnlyRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            message_id_factory=id_factory,
        )
        self._complete_write_run = CompleteWriteRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._block_run = BlockRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._fail_run = FailRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._save_write_plan = SaveWritePlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._save_read_plan = SaveReadOnlyPlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._publish_read_plan = PublishReadOnlyPlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._claim_read = ClaimReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._execute_read = ExecuteReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            gateway=gateway,
        )
        self._complete_read = CompleteReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._finalize_read = FinalizeReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._fail_read = FailReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._publish_write_plan = PublishWritePlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._claim_write = ClaimWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            signing_secret=signing_secret,
            service_instance_id=service_instance_id,
        )
        self._preflight_write = PreflightWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            gateway=gateway,
            now_ms=now_ms,
            work_hours_provider=self._work_hours_provider,
        )
        self._execute_write = ExecuteWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            gateway=connector_execution,
            now_ms=now_ms,
            signing_secret=signing_secret,
            service_instance_id=service_instance_id,
        )
        self._store_write_success = StoreWriteActionSuccessService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._mark_write_failed = MarkWriteActionFailedService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._mark_write_unknown = MarkWriteActionUnknownResultService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._verify_write = VerifyWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=connector_execution,
        )
        self._require_write_reauth = RequireWriteReauthService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._recover_unknown_create = RecoverUnknownCreateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=connector_execution,
        )
        self._recover_unknown_send = RecoverUnknownSendActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=connector_execution,
        )
        self._recover_unknown_delete = RecoverUnknownDeleteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=connector_execution,
        )
        self._recover_unknown_update = RecoverUnknownUpdateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=connector_execution,
        )
        self._begin_write_verification = BeginWriteVerificationService(
            unit_of_work_factory=unit_of_work_factory,
        )
        self._write_execution_phase = WriteExecutionPhaseCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            id_factory=id_factory,
            request_hash=self._request_hash,
            should_stop_for_cancel=self._should_stop_for_cancel,
            preflight_write=self._preflight_write,
            claim_write=self._claim_write,
            execute_write=self._execute_write,
            store_write_success=self._store_write_success,
            begin_verification=self._begin_write_verification,
            verify_write=self._verify_write,
            mark_write_failed=self._mark_write_failed,
            mark_write_unknown=self._mark_write_unknown,
            require_write_reauth=self._require_write_reauth,
            recover_unknown_create=self._recover_unknown_create,
            recover_unknown_send=self._recover_unknown_send,
            recover_unknown_delete=self._recover_unknown_delete,
            recover_unknown_update=self._recover_unknown_update,
        )
        self._write_execution_node = WriteExecutionNode(
            id_factory=id_factory,
            request_hash=self._request_hash,
            should_stop_for_cancel=self._should_stop_for_cancel,
            list_actions=self._list_actions,
            execute_read_only_plan=self._execute_read_only_plan,
            execution_phase=self._write_execution_phase,
            has_persisted_cancel_intent=self._has_persisted_cancel_intent,
            complete_write_run=self._complete_write_run,
            current_run_version=self._current_run_version,
        )
        self._write_recovery = WriteRecoveryCoordinator(
            latest_unknown_action=self._latest_unknown_action,
            execution_phase=self._write_execution_phase,
            complete_write_run_if_verified=self._complete_write_run_if_verified,
            plans_for_run=self._plans_for_run,
            list_actions=self._list_actions,
            begin_verification=self._begin_write_verification,
            latest_attempt_id=self._latest_attempt_id,
        )
        entry_subgraphs = build_pre_analysis_subgraphs(
            request_agent=self._request_understanding,
            tool_route_agent=self._tool_route_agent,
            acquisition_agent=self._acquisition,
            retrieval_query_planner=self._retrieval_query_planner,
            context_agent=self._context,
            tool_catalog=tool_catalog,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            transition_run=self._transition_run,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            read_result_cache=self._read_result_cache,
            retrieval_read_executor=self._retrieval_read_executor,
            default_tasklist_id_provider=self._default_tasklist_id_provider,
        )
        self._request_subgraph = entry_subgraphs.request_understanding
        self._tool_route_subgraph = entry_subgraphs.tool_route
        self._acquisition_subgraph = entry_subgraphs.acquisition
        self._context_subgraph = entry_subgraphs.context_retrieval
        self._analysis_subgraph = WorkAnalysisSubgraph(
            agent=self._analysis,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            transition_run=self._transition_run,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
        ).build()
        self._planning_subgraph = PlanningSubgraph(
            agent=self._planning,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
        ).build()
        self._review_subgraph = ReviewSubgraph(
            agent=self._review,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
        ).build()
        self._three_stage_one_subgraph: Any = None
        self._three_stage_two_subgraph: Any = None
        self._three_stage_review_subgraph: Any = None
        if self._graph_profile is GraphProfile.THREE_STAGE:
            assert self._three_stage1_prompt_ref is not None
            assert self._three_stage2_prompt_ref is not None
            self._three_stage_one_subgraph = ThreeStageOneSubgraph(
                request_understanding_agent=self._request_understanding,
                acquisition_agent=self._acquisition,
                prompt_ref=self._three_stage1_prompt_ref,
                id_factory=id_factory,
                graph_profile=self._graph_profile,
                transition_run=self._transition_run,
                merge_decision=self._merge_decision,
            ).build()
            self._three_stage_two_subgraph = ThreeStageTwoSubgraph(
                request_understanding_agent=self._request_understanding,
                planning_agent=self._planning,
                prompt_ref=self._three_stage2_prompt_ref,
                id_factory=id_factory,
                graph_profile=self._graph_profile,
                transition_run=self._transition_run,
                merge_decision=self._merge_decision,
            ).build()
            self._three_stage_review_subgraph = ThreeStageReviewSubgraph(
                agent=self._review,
                id_factory=id_factory,
                graph_profile=self._graph_profile,
                merge_decision=self._merge_decision,
            ).build()
        self._single_workflow_subgraph: Any = None
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            assert self._single_request_source_prompt_ref is not None
            assert self._single_reason_plan_prompt_ref is not None
            assert self._single_review is not None
            self._single_workflow_subgraph = SingleWorkflowSubgraph(
                request_understanding_agent=self._request_understanding,
                acquisition_agent=self._acquisition,
                planning_agent=self._planning,
                review_agent=self._single_review,
                request_source_prompt_ref=self._single_request_source_prompt_ref,
                reason_plan_prompt_ref=self._single_reason_plan_prompt_ref,
                id_factory=id_factory,
                graph_profile=self._graph_profile,
                transition_run=self._transition_run,
                merge_decision=self._merge_decision,
            ).build()
        self._topology = self._topology_for_profile()
        self._graph_composition = WorkflowGraphComposition(
            profile=self._graph_profile,
            topology=self._topology,
            bindings=GraphNodeBindings(
                request_understanding=self._request_subgraph,
                tool_route=self._tool_route_subgraph,
                acquisition=self._acquisition_subgraph,
                context_retriever=self._context_subgraph,
                work_analysis=self._analysis_subgraph,
                planning=self._planning_subgraph,
                review=self._review_subgraph,
                single_workflow=self._single_workflow_subgraph,
                domain_validation=self._domain_validation_node,
                waiting_confirmation=self._waiting_confirmation_node,
                waiting_approval=self._waiting_approval_node,
                modify_review=self._modify_review_node,
                action_execution=self._write_execution_node,
                recovery=self._write_recovery.recover_unknown,
                finalize=self._finalize_node,
                stage_one=self._three_stage_one_subgraph,
                stage_two=self._three_stage_two_subgraph,
                stage_three=self._three_stage_review_subgraph,
            ),
            route_next_node=self._route_next_node,
            checkpointer=self._checkpointer,
        )
        self._native_agent_subgraphs = self._native_subgraphs_for_profile()
        self._graph = self._build_graph()
        self._invocation = WorkflowInvocationCoordinator(
            graph=self._graph,
            graph_profile=self._graph_profile,
            initial_state=self._initial_state,
            current_run_status=self._current_run_status,
            latest_unknown_action=self._latest_unknown_action,
            recovery_node=self._write_recovery.recover_unknown,
            has_executed_action=self._has_executed_action,
            recover_executed_actions=self._write_recovery.recover_executed,
            cancel_signal_lock=self._cancel_signal_lock,
            cancel_signals=self._cancel_signals,
        )

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        return self._invocation.start(request)

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        return self._invocation.resume(request)

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
        self._checkpoint_connection.close()

    def _build_graph(self) -> Any:
        return self._graph_composition.build()

    def _edge_map(self) -> dict[Hashable, str]:
        return self._graph_composition.edge_map()

    def _initial_state(self, request: WorkflowStartRequest) -> GraphState:
        return initial_graph_state(
            request,
            graph_profile=self._graph_profile,
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
        return self._graph_composition.native_subgraphs()

    def _domain_validation_node(self, state: GraphState) -> GraphState:
        plan_draft = _require_state_value(state["plan_draft"], "plan_draft")
        result = self._domain_validation(
            plan_draft=plan_draft,
            analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
        )
        decision = route_supervisor(
            phase=WorkflowPhase.DOMAIN_VALIDATION,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        is_modify_review = state.get("__modify_review_plan_id__") is not None
        if is_modify_review:
            review_status = (
                PlanReviewStatus.PASSED
                if result["result"] == DomainValidationResult.REQUIRE_APPROVAL.value
                else PlanReviewStatus.BLOCKED
            )
            if not self._store_modify_review_result(state, review_status):
                return {
                    **state,
                    "__target__": "end",
                    "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
                }
            if review_status is PlanReviewStatus.PASSED:
                decision["target"] = SupervisorTarget.WAITING_APPROVAL.value
                decision["state_update"] = {
                    **decision["state_update"],
                    "approved_plan_id": state["__modify_review_plan_id__"],
                }
        elif result["result"] == DomainValidationResult.REQUIRE_APPROVAL.value:
            plan_id = self._persist_write_plan(state, plan_draft)
            decision["target"] = SupervisorTarget.WAITING_APPROVAL.value
            decision["state_update"] = {
                **decision["state_update"],
                "approved_plan_id": plan_id,
            }
        elif result["result"] == DomainValidationResult.ALLOW_READ.value:
            plan_id = self._persist_read_plan(state, plan_draft)
            decision["target"] = SupervisorTarget.ACTION_EXECUTION.value
            decision["state_update"] = {
                **decision["state_update"],
                "approved_plan_id": plan_id,
                "workflow_phase": WorkflowPhase.PREFLIGHT.value,
            }
        return self._merge_decision(
            state, {"workflow_phase": WorkflowPhase.DOMAIN_VALIDATION.value}, decision
        )

    def _waiting_confirmation_node(self, state: GraphState) -> GraphState:
        interrupt_payload = cast(dict[str, object], state["user_interrupt"])
        request = self._request_from_state(state)
        if (
            RunStatus(self._current_run_status(request.run_id))
            is not RunStatus.WAITING_CONFIRMATION
        ):
            self._transition_run(request.run_id, "request_confirmation")
        resume_payload = interrupt(
            {
                "interrupt_kind": "CONFIRMATION",
                "run_id": request.run_id,
                **interrupt_payload,
            }
        )
        augmented_request = self._request_with_confirmation(
            request,
            cast(dict[str, object], resume_payload),
        )
        return {
            **state,
            "__request__": augmented_request,
            "__target__": self._confirmation_resume_target(interrupt_payload),
            "user_interrupt": None,
            "workflow_phase": WorkflowPhase.SOURCE_PLANNING.value,
            "prompt_context": {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_response": cast(dict[str, object], resume_payload),
            },
        }

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
            RunStatus.COMPLETED.value,
            RunStatus.BLOCKED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }:
            return {**state, "__target__": "end"}
        return {
            **state,
            "__target__": "action_execution",
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
            plan = unit_of_work.plans.get_by_id(plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {plan_id}")
            if (
                plan.review_status is not PlanReviewStatus.REQUIRED
                or plan.review_version != review_version
            ):
                return {
                    **state,
                    "__target__": "end",
                    "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
                }
            actions = unit_of_work.actions.list_by_plan(plan_id)
            dependencies = {
                action.id: unit_of_work.action_dependencies.list_dependencies(action.id)
                for action in actions
            }

        draft = deepcopy(_require_state_value(state["plan_draft"], "plan_draft"))
        persisted = {action.id: action for action in actions}
        for action_draft in draft["actions"]:
            action = persisted.get(action_draft["action_id"])
            if action is None:
                raise LookupError(f"persisted action not found: {action_draft['action_id']}")
            action_draft["arguments"] = cast(dict[str, object], loads(action.arguments_json))
            action_draft["expected"] = cast(dict[str, object], loads(action.expected_json))
            action_draft["depends_on_action_ids"] = list(dependencies[action.id])

        return {
            **state,
            "plan_draft": draft,
            "plan_review": None,
            "approved_plan_id": plan_id,
            "__modify_review_plan_id__": plan_id,
            "__modify_review_version__": review_version,
            "__modify_review_risks__": {action.id: action.risk for action in actions},
            "__target__": "modify_review",
            "__logical_target__": self._modify_review_profile_target(),
            "workflow_phase": WorkflowPhase.PLAN_REVIEW.value,
        }

    def _modify_review_node(self, state: GraphState) -> GraphState:
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            reviewed = cast(GraphState, self._review_subgraph.invoke(state))
        elif self._graph_profile is GraphProfile.THREE_STAGE:
            reviewed = cast(GraphState, self._three_stage_review_subgraph.invoke(state))
        else:
            assert self._single_review is not None
            request = self._request_from_state(state)
            result = self._single_review.inspect(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=None,
                plan_draft=_require_state_value(state["plan_draft"], "plan_draft"),
                request=request,
                deterministic_action_risks=state.get("__modify_review_risks__"),
            )
            decision = route_supervisor(
                phase=WorkflowPhase.PLAN_REVIEW,
                state=cast(MultiAgentGraphState, state),
                result=result,
            )
            reviewed = self._merge_decision(
                state, self._single_review.build_state_update(result), decision
            )

        reviewed = {
            **reviewed,
            "__modify_review_plan_id__": state["__modify_review_plan_id__"],
            "__modify_review_version__": state["__modify_review_version__"],
            "__modify_review_risks__": state["__modify_review_risks__"],
        }

        route_reconsideration_signal = reviewed.get("workflow_signal")
        if (
            reviewed.get("plan_review") is None
            and isinstance(route_reconsideration_signal, dict)
            and route_reconsideration_signal.get("kind") == "ROUTE_RECONSIDERATION_REQUIRED"
        ):
            # Pre-Prompt LangGraph Code Completion: the re-invoked Review's
            # own ROUTE_RECONSIDERATION disposition was already intercepted
            # by supervisor._route_reconsideration (plan_review cleared,
            # __target__ pointed at Tool Route, workflow_signal populated)
            # before this node ever saw a PlanReviewResultV1 -- there is no
            # `review["status"]` to read here. Canonical (04 SS25.5, 08
            # SS Modify sequence) never specifies this edge for the
            # post-approval modify-review gate; it only defines REVISE/
            # RETRIEVE_MORE -> supersede + REPLAN-to-PLANNING. Per this
            # task's explicit "no unconditional DB enum/migration" rule and
            # since `plans.review_status` has a SQL CHECK enumerating only
            # PASSED/REQUIRED/REVISE/RETRIEVE_MORE/BLOCKED (migration 0004,
            # not modified here), a route-level defect discovered post-
            # approval is folded into the existing RETRIEVE_MORE bucket and
            # resolved through the same supersede+replan-to-PLANNING path
            # already used for REVISE/RETRIEVE_MORE -- a documented,
            # reported downgrade from the primary flow's Tool-Route
            # redirect, not a silent one. Trusting the supervisor's own
            # __target__ (Tool Route) here instead would durably strand
            # `plans.review_status='REQUIRED'` and `Run.status=
            # WAITING_APPROVAL`, since nothing else ever resolves that claim.
            if not self._store_modify_review_result(reviewed, PlanReviewStatus.RETRIEVE_MORE):
                return {
                    **reviewed,
                    "__target__": "end",
                    "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
                }
            if not self._begin_modify_replan(reviewed, PlanReviewStatus.RETRIEVE_MORE):
                return {
                    **reviewed,
                    "__target__": "end",
                    "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
                }
            reviewed = cast(GraphState, dict(reviewed))
            reviewed["__replan_from_plan_id__"] = cast(str, reviewed["__modify_review_plan_id__"])
            reviewed["__modify_review_plan_id__"] = None
            reviewed["__modify_review_version__"] = None
            reviewed["__modify_review_risks__"] = None
            reviewed["__target__"] = "end"
            reviewed["execution_summary"] = {"result": "MODIFY_ROUTE_RECONSIDERATION_REPLAN"}
            return reviewed

        review = _require_state_value(reviewed["plan_review"], "plan_review")
        if review["status"] == ReviewResult.PASS.value:
            return reviewed
        if not self._store_modify_review_result(reviewed, self._review_status(review)):
            return {
                **reviewed,
                "__target__": "end",
                "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
            }
        if review["status"] in {
            ReviewResult.REVISE.value,
            ReviewResult.RETRIEVE_MORE.value,
        }:
            if not self._begin_modify_replan(reviewed, self._review_status(review)):
                return {
                    **reviewed,
                    "__target__": "end",
                    "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
                }
            reviewed = cast(GraphState, dict(reviewed))
            reviewed["__replan_from_plan_id__"] = cast(str, reviewed["__modify_review_plan_id__"])
            reviewed["__modify_review_plan_id__"] = None
            reviewed["__modify_review_version__"] = None
            reviewed["__modify_review_risks__"] = None
        return reviewed

    def _modify_review_profile_target(self) -> str:
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            return "single_workflow"
        if self._graph_profile is GraphProfile.THREE_STAGE:
            return "stage_three"
        return "review"

    @staticmethod
    def _review_status(review: PlanReviewResultV1) -> PlanReviewStatus:
        return {
            ReviewResult.REVISE.value: PlanReviewStatus.REVISE,
            ReviewResult.RETRIEVE_MORE.value: PlanReviewStatus.RETRIEVE_MORE,
            ReviewResult.CONFIRM.value: PlanReviewStatus.REQUIRED,
            ReviewResult.BLOCK.value: PlanReviewStatus.BLOCKED,
        }[review["status"]]

    def _store_modify_review_result(
        self, state: GraphState, review_status: PlanReviewStatus
    ) -> bool:
        plan_id = state.get("__modify_review_plan_id__")
        review_version = state.get("__modify_review_version__")
        if plan_id is None or review_version is None:
            return False
        with self._unit_of_work_factory() as unit_of_work:
            applied = unit_of_work.plans.store_review_result(
                plan_id,
                expected_review_version=review_version,
                review_status=review_status.value,
            )
            if applied:
                unit_of_work.commit()
            return applied

    def _begin_modify_replan(self, state: GraphState, review_status: PlanReviewStatus) -> bool:
        plan_id = state.get("__modify_review_plan_id__")
        review_version = state.get("__modify_review_version__")
        if plan_id is None or review_version is None:
            return False
        with self._unit_of_work_factory() as unit_of_work:
            plan = unit_of_work.plans.get_by_id(plan_id)
            if (
                plan is None
                or plan.review_version != review_version
                or plan.review_status is not review_status
            ):
                return False
            run = unit_of_work.runs.get_by_id(plan.run_id)
            if run is None:
                return False
            transitioned = unit_of_work.runs.replan(
                run.id,
                expected_version=run.version,
            )
            if not transitioned.applied:
                return False
            unit_of_work.plans.supersede(plan.id)
            unit_of_work.commit()
            return True

    def _finalize_node(self, state: GraphState) -> GraphState:
        finalize_intent = derive_finalize_intent(state=cast(MultiAgentGraphState, state))
        if finalize_intent is None:
            return {**state, "__target__": "end", "workflow_phase": WorkflowPhase.FINALIZE.value}
        run_id = cast(str, state["run_id"])
        if finalize_intent["intent"] == "COMPLETED" and state.get("answer_draft") is not None:
            draft = cast(dict[str, object], state["answer_draft"])
            self._complete_answer_only(
                CompleteAnswerOnlyRunCommand(
                    command_id=self._id_factory(),
                    conversation_id=cast(str, state["conversation_id"]),
                    run_id=run_id,
                    assistant_message=self._required_string(draft.get("answer"), "answer"),
                    expected_version=self._current_run_version(run_id),
                    request_hash=self._request_hash({"kind": "answer_only", "run_id": run_id}),
                )
            )
        elif finalize_intent["intent"] == "BLOCKED":
            self._block_run(
                BlockRunCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "block", "run_id": run_id}),
                    run_id=run_id,
                    expected_version=self._current_run_version(run_id),
                    reason_code=finalize_intent["reason_code"],
                )
            )
        elif finalize_intent["intent"] == "FAILED":
            self._fail_run(
                FailRunCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "fail", "run_id": run_id}),
                    run_id=run_id,
                    expected_version=self._current_run_version(run_id),
                    reason_code=finalize_intent["reason_code"],
                )
            )
        self._evidence_store.discard_run(run_id=run_id)
        self._read_result_cache.discard_run(run_id=run_id)
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.FINALIZE.value,
            "finalize_intent": finalize_intent,
        }

    def _route_next_node(self, state: GraphState) -> str:
        run_id = state.get("run_id")
        if isinstance(run_id, str) and self._should_stop_for_cancel(run_id):
            return "end"
        return cast(str, state.get("__target__", "end"))

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
        logical_target = self._logical_target_name(cast(str, decision["target"]))
        target = self._target_to_node(cast(str, decision["target"]))
        merged["__logical_target__"] = logical_target
        merged["__target__"] = target
        return merged

    def _logical_target_name(self, target: str) -> str:
        return self._route_translator.translate(target).logical_target

    def _target_to_node(self, target: str) -> str:
        return self._route_translator.translate(target).node

    def _confirmation_resume_target(self, interrupt_payload: dict[str, object]) -> str:
        return self._route_translator.confirmation_resume_target(interrupt_payload)

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

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        run_id = state["run_id"]
        run_version = self._current_run_version(run_id)
        replan_from_plan_id = state.get("__replan_from_plan_id__")
        revision_no = 1
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        action_id_map = {
            action["action_id"]: action["action_id"] for action in plan_draft["actions"]
        }
        evidence_id_map = {evidence_id: evidence_id for evidence_id in plan_draft["evidence_refs"]}
        if replan_from_plan_id is not None:
            plans = self._plans_for_run(run_id)
            if not any(plan.id == replan_from_plan_id for plan in plans):
                raise LookupError(f"replan source not found: {replan_from_plan_id}")
            revision_no = max(plan.revision_no for plan in plans) + 1
            plan_id = self._id_factory()
            action_id_map = {
                action["action_id"]: self._id_factory() for action in plan_draft["actions"]
            }
            evidence_id_map = {
                evidence_id: self._id_factory() for evidence_id in plan_draft["evidence_refs"]
            }
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = {
            item["evidence_id"]: item
            for item in resolve_evidence_projection(
                store=self._evidence_store,
                run_id=run_id,
                retrieval_result=retrieval_result,
            )
        }
        mapped_evidence = []
        for evidence_id in plan_draft["evidence_refs"]:
            item = evidence_drafts[evidence_id]
            mapped_evidence.append(
                WriteEvidenceDraft(
                    evidence_id=evidence_id_map[evidence_id],
                    origin_type=EvidenceOriginType.DERIVED,
                    kind=item["kind"],
                    excerpt=item["excerpt"],
                    locator_json=None
                    if item.get("locator") is None
                    else dumps(item["locator"], sort_keys=True),
                )
            )
        mapped_actions = tuple(
            WriteActionDraft(
                action_id=action_id_map[action["action_id"]],
                position=action["position"],
                tool_name=action["tool_name"],
                arguments=action["arguments"],
                expected=action["expected"],
                evidence_ids=tuple(evidence_id_map[item] for item in action["evidence_refs"]),
                depends_on_action_ids=tuple(
                    action_id_map[item] for item in action.get("depends_on_action_ids", [])
                ),
                target_resource_ref_id=self._resolve_target_resource_ref_id(
                    run_id=run_id,
                    resource_handle=action.get("target_resource_ref_id"),
                    acquisition_result=_require_state_value(
                        state["acquisition_result"], "acquisition_result"
                    ),
                ),
                risk=(
                    evidence_duplicate_risk(
                        arguments=action["arguments"],
                        acquisition_result=_require_state_value(
                            state["acquisition_result"], "acquisition_result"
                        ),
                        checked_at_ms=self._now_ms(),
                    )
                    if action["tool_name"] == TASK_CREATE_TOOL
                    else self._calendar_plan_risk(state=state, action=action)
                    if action["tool_name"] in CALENDAR_CONFLICT_TOOLS
                    else {}
                ),
            )
            for action in plan_draft["actions"]
        )
        save_response = self._save_write_plan(
            SaveWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_write_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                revision_no=revision_no,
                summary_text=self._required_string(plan_draft.get("summary"), "summary"),
                expected_run_version=run_version,
                actions=mapped_actions,
                evidence=tuple(mapped_evidence),
            )
        )
        if not save_response.applied:
            raise RuntimeError(f"save_write_plan failed: {save_response.result_code}")
        publish_response = self._publish_write_plan(
            PublishWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "publish_write_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                expected_run_version=save_response.run_version,
            )
        )
        if not publish_response.applied:
            raise RuntimeError(f"publish_write_plan failed: {publish_response.result_code}")
        return plan_id

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
            analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            acquisition_result=acquisition,
            checked_at_ms=checked_at_ms,
            work_hours=self._work_hours_provider(),
        )
        return {**conflict, **feasibility}

    def _resolve_target_resource_ref_id(
        self,
        *,
        run_id: str,
        resource_handle: str | None,
        acquisition_result: AcquisitionResultV1,
    ) -> str | None:
        if resource_handle is None:
            return None
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.resource_refs.get_by_id(resource_handle)
            if existing is not None:
                return existing.id
            for resource_ref in unit_of_work.resource_refs.list_by_run(run_id):
                if resource_handle == _resource_handle_for_ref(resource_ref):
                    return resource_ref.id
            resource = _acquired_resource_by_handle(
                acquisition_result=acquisition_result,
                resource_handle=resource_handle,
            )
            if resource is None:
                raise LookupError(
                    f"target resource handle was not acquired for this run: {resource_handle}"
                )
            source = ResourceSource(str(resource["source"]))
            resource_type = _stored_resource_type_for_acquired_resource(
                source=source,
                resource_type=str(resource["resource_type"]),
            )
            payload = cast(dict[str, object], resource["payload"])
            resource_ref = ResourceRefRecord(
                id=f"resource-ref-{run_id}-{resource_handle.replace(':', '-')}",
                run_id=run_id,
                source=source,
                resource_type=resource_type,
                resource_id=str(resource["resource_id"]),
                parent_resource_id=cast(str | None, resource.get("parent_id")),
                canonical_url=None,
                title=str(
                    payload.get("subject") or payload.get("title") or resource["resource_id"]
                )[:200],
                event_time_ms=None,
                version_token=cast(str | None, resource.get("version")),
                metadata_json=dumps(payload, sort_keys=True),
                captured_at_ms=self._now_ms(),
            )
            unit_of_work.resource_refs.upsert(resource_ref)
            persisted = unit_of_work.resource_refs.get_by_unique_key(
                run_id=run_id,
                source=source.value,
                resource_type=resource_type.value,
                resource_id=resource_ref.resource_id,
            )
            if persisted is None:
                raise RuntimeError("target resource reference was not persisted")
            unit_of_work.commit()
            return persisted.id

    def _persist_read_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        run_id = state["run_id"]
        run_version = self._current_run_version(run_id)
        retrieval_result = _require_state_value(state["retrieval_result"], "retrieval_result")
        evidence_drafts = {
            item["evidence_id"]: item
            for item in resolve_evidence_projection(
                store=self._evidence_store,
                run_id=run_id,
                retrieval_result=retrieval_result,
            )
        }
        mapped_evidence = []
        for evidence_id in plan_draft["evidence_refs"]:
            item = evidence_drafts[evidence_id]
            mapped_evidence.append(
                ReadEvidenceDraft(
                    evidence_id=evidence_id,
                    origin_type=EvidenceOriginType.DERIVED,
                    kind=item["kind"],
                    excerpt=item["excerpt"],
                    locator_json=None
                    if item.get("locator") is None
                    else dumps(item["locator"], sort_keys=True),
                )
            )
        mapped_actions = tuple(
            ReadActionDraft(
                action_id=action["action_id"],
                position=action["position"],
                tool_name=action["tool_name"],
                arguments=action["arguments"],
                expected=action["expected"],
                evidence_ids=tuple(action["evidence_refs"]),
                depends_on_action_ids=tuple(action.get("depends_on_action_ids", [])),
                target_resource_ref_id=action.get("target_resource_ref_id"),
            )
            for action in plan_draft["actions"]
        )
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        save_response = self._save_read_plan(
            SaveReadOnlyPlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_read_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                revision_no=1,
                summary_text=self._required_string(plan_draft.get("summary"), "summary"),
                expected_run_version=run_version,
                actions=mapped_actions,
                evidence=tuple(mapped_evidence),
            )
        )
        if not save_response.applied:
            raise RuntimeError(f"save_read_plan failed: {save_response.result_code}")
        publish_response = self._publish_read_plan(
            PublishReadOnlyPlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "publish_read_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                expected_run_version=save_response.run_version,
            )
        )
        if not publish_response.applied:
            raise RuntimeError(f"publish_read_plan failed: {publish_response.result_code}")
        return plan_id

    def _execute_read_only_plan(
        self,
        state: GraphState,
        plan_id: str,
        actions: tuple[ActionRecord, ...],
    ) -> GraphState:
        verification_statuses: list[str] = []
        for action in actions:
            if action.status in {
                ActionStatus.VERIFIED.value,
                ActionStatus.FAILED.value,
                ActionStatus.BLOCKED.value,
                ActionStatus.DEPENDENCY_BLOCKED.value,
                ActionStatus.REJECTED.value,
                ActionStatus.EXPIRED.value,
                ActionStatus.MISMATCH.value,
            }:
                verification_statuses.append(action.status)
                continue
            if action.status != ActionStatus.PROPOSED.value:
                continue
            claimed = self._claim_read(
                ClaimReadActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "claim_read", "action_id": action.id}),
                    action_id=action.id,
                    expected_version=action.version,
                )
            )
            if not claimed.applied:
                continue
            try:
                executed = self._execute_read(action_id=action.id)
            except GoogleWorkspaceGatewayError as error:
                failed = self._fail_read(
                    FailReadActionCommand(
                        command_id=self._id_factory(),
                        request_hash=self._request_hash(
                            {"kind": "fail_read", "action_id": action.id}
                        ),
                        action_id=action.id,
                        expected_version=claimed.action_version,
                        safe_error_code=error.code.value,
                        retryable=False,
                        safe_error_detail=str(error),
                    )
                )
                verification_statuses.append(failed.action_status)
                continue
            completed = self._complete_read(
                CompleteReadActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "complete_read", "action_id": action.id}
                    ),
                    action_id=action.id,
                    expected_version=claimed.action_version,
                    output_json=executed.output_json,
                    resource_refs=executed.resource_refs,
                    evidence=executed.evidence,
                )
            )
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
            verification_statuses.append(finalized.action_status)
        return {
            **state,
            "__target__": "finalize",
            "workflow_phase": WorkflowPhase.VERIFICATION.value,
            "execution_summary": {"result": "READ_EXECUTED", "plan_id": plan_id},
            "verification_summary": {"action_statuses": verification_statuses},
        }

    def _transition_run(self, run_id: str, transition_name: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            if transition_name == "start_analysis" and run.status is not RunStatus.CREATED:
                return
            if transition_name == "begin_retrieval" and run.status in {
                RunStatus.RETRIEVING,
                RunStatus.PLANNING,
                RunStatus.WAITING_APPROVAL,
            }:
                return
            if transition_name == "begin_planning" and run.status is not RunStatus.RETRIEVING:
                return
            if (
                transition_name == "request_confirmation"
                and run.status is RunStatus.WAITING_CONFIRMATION
            ):
                return
            repository_method = getattr(unit_of_work.runs, transition_name)
            result = repository_method(
                run_id,
                expected_version=run.version,
                finished_at_ms=None,
            )
            if result.applied:
                unit_of_work.commit()

    def _current_run_status(self, run_id: str) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            return run.status.value

    def _current_run_version(self, run_id: str) -> int:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            return run.version

    def _list_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return tuple(
                sorted(unit_of_work.actions.list_by_plan(plan_id), key=lambda item: item.position)
            )

    def _plans_for_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.plans.list_by_run(run_id)

    def _has_executed_action(self, run_id: str) -> bool:
        return any(
            action.status == ActionStatus.EXECUTED.value
            for plan in self._plans_for_run(run_id)
            for action in self._list_actions(plan.id)
        )

    def _latest_attempt_id(self, action_id: str) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            approvals = unit_of_work.approvals.list_by_action(action_id)
            attempts = [
                attempt
                for approval in approvals
                for attempt in unit_of_work.execution_attempts.list_by_approval(approval.id)
            ]
            if not attempts:
                raise LookupError(f"execution attempt not found for action: {action_id}")
            return max(attempts, key=lambda item: (item.attempt_no, item.started_at_ms)).id

    def _complete_write_run_if_verified(self, plan_id: str, run_id: str) -> None:
        if self._has_persisted_cancel_intent(run_id):
            return
        actions = self._list_actions(plan_id)
        if not actions or not all(
            action.status == ActionStatus.VERIFIED.value for action in actions
        ):
            return
        response = self._complete_write_run(
            CompleteWriteRunCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "complete_recovered_write_run", "run_id": run_id}
                ),
                run_id=run_id,
                expected_version=self._current_run_version(run_id),
            )
        )
        if not response.applied and response.result_code != ResultCode.STATE_CONFLICT.value:
            raise RuntimeError(f"recovered write completion failed: {response.result_code}")

    def _should_stop_for_cancel(self, run_id: str) -> bool:
        with self._cancel_signal_lock:
            if run_id in self._cancel_signals:
                return True
        return self._current_run_status(
            run_id
        ) == RunStatus.CANCEL_REQUESTED.value or self._has_persisted_cancel_intent(run_id)

    def _has_persisted_cancel_intent(self, run_id: str) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            cursor: int | None = None
            while True:
                events = unit_of_work.audits.list_by_aggregate(
                    run_id=run_id,
                    cursor_after=cursor,
                    limit=100,
                )
                if any(
                    event.event_type == "RUN_CANCELLATION_REQUESTED"
                    and event.outcome == ResultCode.TRANSITION_APPLIED.value
                    for event in events
                ):
                    return True
                if len(events) < 100:
                    return False
                cursor = events[-1].id

    def _latest_unknown_action(self, run_id: str) -> tuple[ActionRecord, str, int] | None:
        with self._unit_of_work_factory() as unit_of_work:
            plans = unit_of_work.plans.list_by_run(run_id)
            if not plans:
                return None
            latest_plan = sorted(plans, key=lambda item: (item.revision_no, item.created_at_ms))[-1]
            for action in unit_of_work.actions.list_by_plan(latest_plan.id):
                if action.status != ActionStatus.UNKNOWN_RESULT.value:
                    continue
                approvals = unit_of_work.approvals.list_by_action(action.id)
                for approval in sorted(approvals, key=lambda item: item.approval_no, reverse=True):
                    attempts = unit_of_work.execution_attempts.list_by_approval(approval.id)
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
            correlation=request.correlation,
            selected_resources=request.selected_resources,
        )

    def _required_string(self, value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} is required")
        return value

    def _request_hash(self, payload: dict[str, object]) -> str:
        return sha256(dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    _planning_mode_from_request_intent = staticmethod(planning_mode_from_request_intent)
