"""Concrete Stage 17 workflow runtime assembled on LangGraph."""

from __future__ import annotations

from collections.abc import Callable, Hashable
from copy import deepcopy
from hashlib import sha256
from json import dumps, loads
from pathlib import Path
from threading import Lock
from typing import Any, cast

from langgraph.types import interrupt

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    WorkflowGraphComposition,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
    GraphRouteTranslator,
    UnroutableSupervisorTargetError,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    _acquired_resource_by_handle,
    _require_state_value,
    _resource_handle_for_ref,
    _stored_resource_type_for_acquired_resource,
    initial_graph_state,
    request_from_state,
)
from google_work_agent.adapters.langgraph.pre_analysis_composition import (
    build_pre_analysis_subgraphs,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningSubgraph,
    planning_mode_from_request_intent,
)
from google_work_agent.adapters.langgraph.subgraphs.review.runtime_active_graph import (
    RuntimeActiveReviewSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.single_workflow import (
    SingleWorkflowSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.three_stage import (
    ThreeStageOneSubgraph,
    ThreeStageReviewSubgraph,
    ThreeStageTwoSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis_workflow import (
    WorkAnalysisSubgraph,
)
from google_work_agent.adapters.langgraph.write_execution import WriteExecutionNode
from google_work_agent.adapters.langgraph.write_recovery import WriteRecoveryCoordinator
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    evidence_calendar_conflict_risk,
)
from google_work_agent.application.connector_write_projection import ConnectorWriteProjection
from google_work_agent.application.execution_phase import WriteExecutionPhaseCoordinator
from google_work_agent.application.use_cases.approval.expire_approval import ExpireApprovalHandler
from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionHandler,
)
from google_work_agent.application.feasibility import evidence_feasibility_risk
from google_work_agent.application.orchestration.api_acquisition import (
    ApiDiscoveryAcquisitionAgent,
    load_acquisition_plan_sources_prompt_reference,
)
from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.orchestration.context_retrieval import (
    ContextRetrievalAgent,
)
from google_work_agent.application.orchestration.contracts import (
    BudgetDecision,
    ConfirmationResponseProjectionV1,
    DomainValidationResult,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    ReviewResult,
    WorkflowPhase,
    approve_planning_revision,
)
from google_work_agent.application.orchestration.domain_validation import (
    DomainValidationService,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    PlanReviewResultV1,
)
from google_work_agent.application.orchestration.plan_review import PlanReviewAgent
from google_work_agent.application.orchestration.planning_argument_orchestrator import (
    PlanningArgumentOrchestrator,
)
from google_work_agent.application.orchestration.planning_argument_writer import (
    PlanningArgumentWriter,
)
from google_work_agent.application.orchestration.planning_arguments import (
    DefaultContainerResolver,
)
from google_work_agent.application.orchestration.profile_fused import (
    load_profile_single_reason_plan_prompt_reference,
    load_profile_single_request_source_prompt_reference,
    load_profile_single_self_review_prompt_reference,
    load_profile_single_self_review_recheck_prompt_reference,
    load_profile_three_stage1_prompt_reference,
    load_profile_three_stage2_prompt_reference,
)
from google_work_agent.application.orchestration.request_understanding import (
    RequestUnderstandingAgent,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.orchestration.retrieval_query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.orchestration.retrieval_query_planner import (
    RetrievalQueryPlannerAgent,
)
from google_work_agent.application.orchestration.retrieval_read_cache import (
    RunScopedReadResultCache,
)
from google_work_agent.application.orchestration.retrieval_read_executor import (
    RetrievalReadExecutor,
)
from google_work_agent.application.orchestration.solution_planning import (
    SolutionPlanningAgent,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
    route_supervisor,
)
from google_work_agent.application.orchestration.tool_route_semantic import ToolRouteAgent
from google_work_agent.application.orchestration.tool_routing import ToolRouteCoordinator
from google_work_agent.application.orchestration.work_analysis import WorkAnalysisAgent
from google_work_agent.application.use_cases.resource_ref.persist_resource_ref import (
    persist_registered_resource_ref,
)
from google_work_agent.application.policy_kernels.calendar_conflict import CalendarWorkHours
from google_work_agent.application.read_contracts import (
    ClaimReadActionCommand,
    CompleteReadActionCommand,
    FailReadActionCommand,
    FinalizeReadActionCommand,
    PublishReadOnlyPlanCommand,
    ReadActionDraft,
    ReadEvidenceDraft,
    SaveReadOnlyPlanCommand,
)
from google_work_agent.application.read_execution import ExecuteReadActionService
from google_work_agent.application.read_plan import (
    SaveReadOnlyPlanService,
)
from google_work_agent.application.run_terminal import (
    FailRunCommand,
    FailRunService,
    derive_finalize_intent,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    evidence_duplicate_risk,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.claim_read_action import ClaimReadActionHandler
from google_work_agent.application.use_cases.action.complete_read_action import (
    CompleteReadActionHandler,
)
from google_work_agent.application.use_cases.action.fail_read_action import FailReadActionHandler
from google_work_agent.application.use_cases.action.finalize_read_action import (
    FinalizeReadActionHandler,
)
from google_work_agent.application.use_cases.claim.build_claim_context import (
    BuildClaimContextHandler,
)
from google_work_agent.application.use_cases.claim.claim_execution import ClaimExecutionHandler
from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionCommandV1,
    AbortClaimedExecutionHandler,
)
from google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt import (
    BeginExecutionAttemptHandler,
)
from google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result import (
    ClassifyDispatchResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.mark_failed import MarkFailedHandler
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.store_success import (
    StoreSuccessHandler,
)
from google_work_agent.application.use_cases.plan.publish_plan import PublishPlanHandler
from google_work_agent.application.use_cases.plan.publish_read_only_plan import (
    PublishReadOnlyPlanHandler,
)
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultCommandV1,
    RecordReviewResultHandler,
)
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryHandler,
)
from google_work_agent.application.use_cases.run.begin_planning import (
    BeginPlanningCommand,
    BeginPlanningHandler,
)
from google_work_agent.application.use_cases.run.begin_retrieval import (
    BeginRetrievalCommand,
    BeginRetrievalHandler,
)
from google_work_agent.application.use_cases.run.begin_verification import (
    BeginVerificationCommand,
    BeginVerificationHandler,
)
from google_work_agent.application.use_cases.run.block_run import (
    BlockRunCommand,
    BlockRunHandler,
)
from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunCommand,
    CompleteAnswerOnlyRunHandler,
)
from google_work_agent.application.use_cases.run.complete_write_run import (
    CompleteWriteRunCommand,
    CompleteWriteRunHandler,
)
from google_work_agent.application.use_cases.run.request_confirmation import (
    RequestConfirmationHandler,
)
from google_work_agent.application.use_cases.run.require_reauth import RequireReauthHandler
from google_work_agent.application.use_cases.run.start_analysis import (
    StartAnalysisCommand,
    StartAnalysisHandler,
)
from google_work_agent.application.use_cases.verification.store_verification import (
    StoreVerificationHandler,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    VerifyEffectHandler,
)
from google_work_agent.application.write_plan import (
    SaveWritePlanService,
)
from google_work_agent.application.write_plan_contracts import (
    PublishWritePlanCommand,
    SaveWritePlanCommand,
    WriteActionDraft,
    WriteEvidenceDraft,
)
from google_work_agent.application.write_preflight import PreflightWriteActionService
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanReviewStatus
from google_work_agent.domain.resource_ref.model import ResourceRef as ResourceRefRecord
from google_work_agent.domain.resource_ref.model import ResourceSource
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports import (
    GoogleWorkspaceGatewayError,
    PromptReference,
    UnitOfWork,
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowRuntime,
    WorkflowStartRequest,
)
from google_work_agent.ports.persistence.action_repository import dependency_ids_for_action
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.audit_event_repository import AuditEventCursor
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork as CanonicalUnitOfWork

JsonObject = dict[str, object]


def _legacy_connector_identity_unavailable() -> str:
    """Fail closed when the legacy base lacks frozen Tool Route connector identity.

    Production uses ``canonical_planning_runtime.LangGraphWorkflowRuntime``, whose
    persistence overrides join every action/resource to an explicit frozen route.
    The legacy base must never invent a connector or fall back to Google Workspace.
    """

    raise RuntimeError(
        "legacy LangGraph runtime cannot persist connector-aware DTOs without "
        "frozen Tool Route connector identity; use canonical planning runtime"
    )


class WorkflowRuntimeCore(WorkflowRuntime):
    """LangGraph runtime with selectable Stage 18 graph profiles."""

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
        claim_context_signer: Callable[[dict[str, object]], str] | None = None,
        mcp_process_instance_id: Callable[[], str] | None = None,
        checkpoint_port: SqliteCheckpointAdapter | None = None,
        checkpoint_database_path: Path | None = None,
        graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path: Path | None = None,
        timezone_provider: Callable[[], str] | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
        attachment_verifier: Any | None = None,
        resume_target_registry: ResumeTargetRegistry | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._llm_runtime = llm_runtime
        self._now_ms = now_ms
        self._id_factory = id_factory
        del signing_secret
        self._service_instance_id = service_instance_id
        if (checkpoint_port is None) == (checkpoint_database_path is None):
            raise ValueError("provide exactly one canonical checkpoint adapter or database path")
        self._checkpoint_port = (
            checkpoint_port
            if checkpoint_port is not None
            else SqliteCheckpointAdapter(cast(Path, checkpoint_database_path), now_ms=now_ms)
        )
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
        canonical_uow_factory = cast(Callable[[], CanonicalUnitOfWork], unit_of_work_factory)
        self._start_analysis_handler = StartAnalysisHandler(
            unit_of_work_factory=canonical_uow_factory,
            now_ms=now_ms,
        )
        self._begin_retrieval_handler = BeginRetrievalHandler(
            unit_of_work_factory=canonical_uow_factory,
            now_ms=now_ms,
        )
        self._begin_planning_handler = BeginPlanningHandler(
            unit_of_work_factory=canonical_uow_factory,
            now_ms=now_ms,
            id_factory=id_factory,
            resume_target_registry=self._resume_target_registry,
        )
        self._request_confirmation_handler = RequestConfirmationHandler(
            unit_of_work_factory=canonical_uow_factory,
            now_ms=now_ms,
            resume_target_registry=self._resume_target_registry,
        )
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
        # Canonical ACTION Planning: Tool Route already froze output_routes'
        # connector/resource/effect/tool identity -- the orchestrator only
        # binds each route's selected business-argument schema and invokes
        # the per-route Argument Writer, never re-selecting a Tool.
        self._planning_argument_orchestrator = PlanningArgumentOrchestrator(
            writer=PlanningArgumentWriter(
                llm_runtime=llm_runtime,
                manifest_path=prompt_manifest_path,
            ),
            default_container_resolver=DefaultContainerResolver(
                default_tasklist_id_provider=self._default_tasklist_id_provider,
                default_calendar_id_provider=self._default_calendar_id_provider,
            ),
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

        self._complete_answer_only = CompleteAnswerOnlyRunHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            message_id_factory=id_factory,
        )
        self._complete_write_run = CompleteWriteRunHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            message_id_factory=id_factory,
        )
        self._block_run = BlockRunHandler(
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
        self._publish_read_plan = PublishReadOnlyPlanHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._claim_read = ClaimReadActionHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._execute_read = ExecuteReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            gateway=connector_reader,
        )
        self._complete_read = CompleteReadActionHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._finalize_read = FinalizeReadActionHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._fail_read = FailReadActionHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._publish_write_plan = PublishPlanHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._claim_execution = ClaimExecutionHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._build_claim_context = BuildClaimContextHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            id_factory=id_factory,
            sign_claim_context=claim_context_signer or (lambda _payload: "test-signature"),
        )
        self._begin_execution_attempt = BeginExecutionAttemptHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._abort_claimed_execution = AbortClaimedExecutionHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._classify_dispatch_result = ClassifyDispatchResultHandler()
        self._preflight_write = PreflightWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            gateway=connector_reader,
            now_ms=now_ms,
            work_hours_provider=self._work_hours_provider,
        )
        self._store_write_success = StoreSuccessHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._mark_write_failed = MarkFailedHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._mark_write_unknown = MarkUnknownResultHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            resume_target_registry=self._resume_target_registry,
        )
        self._verify_effect = VerifyEffectHandler(
            connector_read=connector_reader.connector_reader,
            tool_registry=tool_catalog,
        )
        self._store_verification = StoreVerificationHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._require_recovery = RequireRecoveryHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._resolve_recovery = ResolveRecoveryHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            next_id=id_factory,
        )
        self._require_write_reauth = RequireReauthHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._lookup_unknown_result = LookupUnknownResultHandler(
            connector_read=connector_reader.connector_reader,
            tool_registry=tool_catalog,
        )
        self._recover_existing_result = RecoverExistingResultHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._resolve_as_failed = ResolveAsFailedHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._begin_write_verification = BeginVerificationHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            resume_target_registry=self._resume_target_registry,
        )
        self._write_execution_phase = WriteExecutionPhaseCoordinator(
            unit_of_work_factory=unit_of_work_factory,
            id_factory=id_factory,
            request_hash=self._request_hash,
            should_stop_for_cancel=self._should_stop_for_cancel,
            preflight_write=self._preflight_write,
            expire_approval=ExpireApprovalHandler(
                unit_of_work_factory=unit_of_work_factory,
                now_ms=now_ms,
            ),
            refresh_expired_action=RefreshExpiredActionHandler(
                unit_of_work_factory=unit_of_work_factory,
                now_ms=now_ms,
                id_factory=id_factory,
                resume_target_registry=self._resume_target_registry,
                schedule_run_execution=None,
            ),
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
            begin_verification=lambda run_id: (
                None
                if self._current_run_status(run_id) == RunStatusV1.VERIFYING.value
                else self._begin_write_verification(
                    BeginVerificationCommand(
                        command_id=self._id_factory(),
                        request_hash=calculate_canonical_json_hash(
                            {"kind": "begin_verification_recovery", "run_id": run_id}
                        ),
                        run_id=run_id,
                    )
                )
            ),
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
            confirm_request_understanding_inline=self._confirm_request_understanding_inline,
            confirm_tool_route_inline=self._confirm_tool_route_inline,
            confirm_context_retrieval_inline=self._confirm_context_retrieval_inline,
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
            confirm_inline=self._confirm_work_analysis_inline,
        ).build()
        self._planning_subgraph = PlanningSubgraph(
            agent=self._planning,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            confirm_inline=self._confirm_planning_inline,
            argument_orchestrator=self._planning_argument_orchestrator,
        ).build()
        self._review_subgraph = RuntimeActiveReviewSubgraph(
            agent=self._review,
            id_factory=id_factory,
            graph_profile=self._graph_profile,
            merge_decision=self._merge_decision,
            evidence_store=self._evidence_store,
            confirm_inline=self._confirm_review_inline,
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
                tool_route_coordinator=ToolRouteCoordinator(
                    tool_catalog=tool_catalog,
                    id_factory=id_factory,
                ),
                prompt_ref=self._three_stage1_prompt_ref,
                id_factory=id_factory,
                graph_profile=self._graph_profile,
                transition_run=self._transition_run,
                merge_decision=self._merge_decision,
                confirm_inline=self._confirm_context_retrieval_inline,
            ).build()
            self._three_stage_two_subgraph = ThreeStageTwoSubgraph(
                request_understanding_agent=self._request_understanding,
                planning_agent=self._planning,
                evidence_store=self._evidence_store,
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
                tool_route_coordinator=ToolRouteCoordinator(
                    tool_catalog=tool_catalog,
                    id_factory=id_factory,
                ),
                evidence_store=self._evidence_store,
                request_source_prompt_ref=self._single_request_source_prompt_ref,
                reason_plan_prompt_ref=self._single_reason_plan_prompt_ref,
                id_factory=id_factory,
                graph_profile=self._graph_profile,
                transition_run=self._transition_run,
                merge_decision=self._merge_decision,
                confirm_inline=self._confirm_context_retrieval_inline,
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
            start_node=self._topology[0],
            initial_state=self._initial_state,
            current_run_status=self._current_run_status,
            latest_unknown_action=self._latest_unknown_action,
            recovery_node=self._write_recovery.recover_unknown,
            has_executed_action=self._has_executed_action,
            recover_executed_actions=self._write_recovery.recover_executed,
            mark_stalled_claims_as_unknown=self._mark_stalled_claims_as_unknown,
            cancel_signal_lock=self._cancel_signal_lock,
            cancel_signals=self._cancel_signals,
        )

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        return self._invocation.start(request)

    def prepare_start(self, request: WorkflowStartRequest) -> None:
        self._invocation.prepare_start(request)

    def control_resume_node(self, stage_id: str) -> str:
        """Resolve a registered external-control stage to this profile's native node."""
        target_by_stage = {
            "RETRIEVAL_ENTRY": SupervisorTarget.CONTEXT_RETRIEVAL.value,
            "PLANNING_ENTRY": SupervisorTarget.SOLUTION_PLANNING.value,
            "REVIEW_ENTRY": SupervisorTarget.PLAN_REVIEW_INSPECT.value,
            "PREFLIGHT": SupervisorTarget.ACTION_EXECUTION.value,
            "READ_EXECUTION": SupervisorTarget.ACTION_EXECUTION.value,
            "VERIFICATION": SupervisorTarget.ACTION_EXECUTION.value,
            "RECOVERY": SupervisorTarget.RECOVERY.value,
            "CANCEL_RESOLUTION": SupervisorTarget.ACTION_EXECUTION.value,
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
        self._checkpoint_port.close()

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
            if not self._store_modify_review_result(
                state,
                review_status,
                "PASS" if review_status is PlanReviewStatus.PASSED else "BLOCK",
            ):
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

    def _confirm_request_understanding_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        """Overridden by ``canonical_runtime.LangGraphWorkflowRuntime``, the
        only subclass production ever constructs. This legacy base has no
        nested-subgraph interrupt/ResumeConfirmation implementation of its
        own -- kept here (rather than omitted) only so the type is visible on
        this class and a direct construction of the legacy runtime fails
        loudly instead of hitting an ``AttributeError`` deep inside a
        LangGraph node replay.
        """
        raise NotImplementedError(
            "Request Understanding nested confirmation resume requires "
            "adapters.langgraph.canonical_runtime.LangGraphWorkflowRuntime"
        )

    def _confirm_tool_route_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        """Overridden by ``canonical_runtime.LangGraphWorkflowRuntime`` -- see
        ``_confirm_request_understanding_inline`` above for the rationale."""
        raise NotImplementedError(
            "Tool Route nested confirmation resume requires "
            "adapters.langgraph.canonical_runtime.LangGraphWorkflowRuntime"
        )

    def _confirm_context_retrieval_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        """Overridden by ``canonical_runtime.LangGraphWorkflowRuntime`` -- see
        ``_confirm_request_understanding_inline`` above for the rationale."""
        raise NotImplementedError(
            "Retrieval nested confirmation resume requires "
            "adapters.langgraph.canonical_runtime.LangGraphWorkflowRuntime"
        )

    def _confirm_work_analysis_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        """Overridden by ``canonical_runtime.LangGraphWorkflowRuntime`` -- see
        ``_confirm_request_understanding_inline`` above for the rationale."""
        raise NotImplementedError(
            "Work Analysis nested confirmation resume requires "
            "adapters.langgraph.canonical_runtime.LangGraphWorkflowRuntime"
        )

    def _confirm_planning_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        """Overridden by ``canonical_runtime.LangGraphWorkflowRuntime`` -- see
        ``_confirm_request_understanding_inline`` above for the rationale."""
        raise NotImplementedError(
            "Planning nested confirmation resume requires "
            "adapters.langgraph.canonical_runtime.LangGraphWorkflowRuntime"
        )

    def _confirm_review_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]:
        """Overridden by ``canonical_runtime.LangGraphWorkflowRuntime`` -- see
        ``_confirm_request_understanding_inline`` above for the rationale."""
        raise NotImplementedError(
            "Review nested confirmation resume requires "
            "adapters.langgraph.canonical_runtime.LangGraphWorkflowRuntime"
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
            plan = unit_of_work.plans.load_bundle(plan_id)
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
            actions = unit_of_work.actions.list_for_plan(plan_id)
            dependencies = {
                action.id: dependency_ids_for_action(unit_of_work.actions, actions, action.id)
                for action in actions
            }

        # G3 RunBudgetV1 (docs/06 SS11, docs/15 SS8.2): mandatory Modify
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
                "execution_summary": {"result": "MODIFY_REVIEW_BUDGET_EXHAUSTED"},
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
            "retry_budget": budget["run_budget"],
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
            if not self._store_modify_review_result(
                reviewed,
                PlanReviewStatus.REQUIRED,
                ReviewResult.ROUTE_RECONSIDERATION.value,
            ):
                return {
                    **reviewed,
                    "__target__": "end",
                    "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
                }
            if not self._begin_modify_replan(reviewed):
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
        if not self._store_modify_review_result(
            reviewed,
            self._review_status(review),
            review["status"],
        ):
            return {
                **reviewed,
                "__target__": "end",
                "execution_summary": {"result": "STALE_MODIFY_REVIEW"},
            }
        if review["status"] in {
            ReviewResult.REVISE.value,
            ReviewResult.RETRIEVE_MORE.value,
        }:
            if not self._begin_modify_replan(reviewed):
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
        self,
        state: GraphState,
        review_status: PlanReviewStatus,
        review_disposition: str,
    ) -> bool:
        plan_id = state.get("__modify_review_plan_id__")
        review_version = state.get("__modify_review_version__")
        if plan_id is None or review_version is None:
            return False
        with self._unit_of_work_factory() as unit_of_work:
            plan = unit_of_work.plans.load_bundle(plan_id)
            if plan is None:
                return False
            action_versions = {
                action.id: action.version for action in unit_of_work.actions.list_for_plan(plan_id)
            }
        result = RecordReviewResultHandler(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )(
            RecordReviewResultCommandV1(
                command_id=self._phase_command_id(plan.run_id, "record_review", review_version),
                plan_id=plan.id,
                expected_plan_version=plan.revision_no,
                expected_review_version=review_version,
                review_artifact_id=f"{plan.id}:review:{review_version}",
                review_version=review_version,
                disposition=review_disposition,  # type: ignore[arg-type]
                based_on_action_versions=action_versions,
            )
        )
        return result.applied

    def _begin_modify_replan(self, state: GraphState) -> bool:
        plan_id = state.get("__modify_review_plan_id__")
        review_version = state.get("__modify_review_version__")
        if plan_id is None or review_version is None:
            return False
        with self._unit_of_work_factory() as unit_of_work:
            canonical_uow = cast(CanonicalUnitOfWork, unit_of_work)
            plan = unit_of_work.plans.load_bundle(plan_id)
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
        return result.applied

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
        self._llm_runtime.discard_run(run_id=run_id)
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
        try:
            translation = self._route_translator.translate(cast(str, decision["target"]))
        except UnroutableSupervisorTargetError:
            # Fail-closed: an unmapped Supervisor target must never silently
            # fall through to a normal "end" termination. Route into
            # Recovery the same way Supervisor itself already handles an
            # unrecognized contract (see supervisor.py's
            # TOOL_ROUTE_CONTRACT_VIOLATION handling) -- "recovery" is
            # always mapped for every profile, so this cannot recurse.
            merged["execution_summary"] = {"result": "CONTRACT_VIOLATION"}
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

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        connector_id = _legacy_connector_identity_unavailable()
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
                connector_id=connector_id,
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
            existing = unit_of_work.resource_refs.get(resource_handle)
            if existing is not None:
                return existing.id
            for resource_ref in unit_of_work.resource_refs.list_for_run_bounded(run_id, limit=1000):
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
            connector_id = _legacy_connector_identity_unavailable()
            source = ResourceSource(str(resource["source"]))
            resource_type = _stored_resource_type_for_acquired_resource(
                source=source,
                resource_type=str(resource["resource_type"]),
            )
            payload = cast(dict[str, object], resource["payload"])
            resource_ref = ResourceRefRecord(
                id=f"resource-ref-{run_id}-{resource_handle.replace(':', '-')}",
                run_id=run_id,
                connector_id=connector_id,
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
            persisted = persist_registered_resource_ref(unit_of_work, resource_ref)
            unit_of_work.commit()
            return persisted.id

    def _persist_read_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        connector_id = _legacy_connector_identity_unavailable()
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
                connector_id=connector_id,
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
                ActionStatusV1.VERIFIED.value,
                ActionStatusV1.FAILED.value,
                ActionStatusV1.BLOCKED.value,
                ActionStatusV1.DEPENDENCY_BLOCKED.value,
                ActionStatusV1.REJECTED.value,
                ActionStatusV1.EXPIRED.value,
                ActionStatusV1.MISMATCH.value,
            }:
                verification_statuses.append(action.status)
                continue
            if action.status != ActionStatusV1.PROPOSED.value:
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
                return
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
                return
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
                return
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
        if not result.applied:
            raise RuntimeError(
                f"{transition_name} rejected for Run {run_id}: {result.conflict_detail}"
            )

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
            approvals = unit_of_work.approval_history.list_for_action(action_id)
            attempts = [
                attempt
                for approval in approvals
                for attempt in active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
            ]
            if not attempts:
                attempts = [
                    attempt
                    for candidate in unit_of_work.execution_attempts.list_reconciliation_candidates(
                        256
                    )
                    if candidate.action_id == action_id
                    and (
                        attempt := unit_of_work.execution_attempts.get(
                            candidate.execution_attempt_id
                        )
                    )
                    is not None
                ]
            if not attempts:
                raise LookupError(f"execution attempt not found for action: {action_id}")
            return max(attempts, key=lambda item: (item.attempt_no, item.started_at_ms))

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
                error_detail = (
                    "process restarted before BeginExecutionAttempt committed"
                )
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

    def _complete_write_run_if_verified(self, plan_id: str, run_id: str) -> None:
        if self._has_persisted_cancel_intent(run_id):
            return
        actions = self._list_actions(plan_id)
        if not actions or not all(
            action.status == ActionStatusV1.VERIFIED.value for action in actions
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
        ) == RunStatusV1.CANCEL_REQUESTED.value or self._has_persisted_cancel_intent(run_id)

    def _has_persisted_cancel_intent(self, run_id: str) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            cursor: int | None = None
            while True:
                events = unit_of_work.audits.list_page(
                    AuditEventCursor(run_id=run_id, after_id=cursor),
                    100,
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
            plans = current_plan_tuple(unit_of_work.plans, run_id)
            if not plans:
                return None
            latest_plan = sorted(plans, key=lambda item: (item.revision_no, item.created_at_ms))[-1]
            for action in unit_of_work.actions.list_for_plan(latest_plan.id):
                if action.status != ActionStatusV1.UNKNOWN_RESULT.value:
                    continue
                approvals = unit_of_work.approval_history.list_for_action(action.id)
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


from google_work_agent.adapters.langgraph.main.artifact_freshness import (  # noqa: E402
    ArtifactFreshnessMixin,
)
from google_work_agent.adapters.langgraph.main.confirmation_controller import (  # noqa: E402
    ConfirmationControllerMixin,
)
from google_work_agent.adapters.langgraph.main.plan_persistence import (  # noqa: E402
    PlanPersistenceMixin,
)
from google_work_agent.adapters.langgraph.main.response_synthesis import (  # noqa: E402
    ResponseSynthesisMixin,
)
from google_work_agent.adapters.langgraph.main.resume_checkpoint import (  # noqa: E402
    ResumeCheckpointMixin,
)


class LangGraphWorkflowRuntime(
    ResumeCheckpointMixin,
    ArtifactFreshnessMixin,
    ResponseSynthesisMixin,
    PlanPersistenceMixin,
    ConfirmationControllerMixin,
    WorkflowRuntimeCore,
):
    """Single concrete production authority for the LangGraph workflow."""


__all__ = ["LangGraphWorkflowRuntime"]
