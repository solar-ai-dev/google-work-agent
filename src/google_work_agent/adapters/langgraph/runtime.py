"""Concrete Stage 17 workflow runtime assembled on LangGraph."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Hashable
from hashlib import sha256
from json import dumps
from pathlib import Path
from threading import Lock
from typing import Any, Final, Literal, NotRequired, TypedDict, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    merge_trace_context,
    record_llm_result,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
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
    MarkWriteActionFailedCommand,
    MarkWriteActionFailedService,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    PreflightWriteActionService,
    PublishReadOnlyPlanCommand,
    PublishReadOnlyPlanService,
    PublishWritePlanCommand,
    PublishWritePlanService,
    ReadActionDraft,
    ReadEvidenceDraft,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownCreateActionService,
    RecoverUnknownDeleteActionCommand,
    RecoverUnknownDeleteActionService,
    RecoverUnknownSendActionCommand,
    RecoverUnknownSendActionService,
    RecoverUnknownUpdateActionCommand,
    RecoverUnknownUpdateActionService,
    RequireWriteReauthCommand,
    RequireWriteReauthService,
    SaveReadOnlyPlanCommand,
    SaveReadOnlyPlanService,
    SaveWritePlanCommand,
    SaveWritePlanService,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    WriteActionDraft,
    WriteEvidenceDraft,
    derive_finalize_intent,
)
from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    evidence_calendar_conflict_risk,
)
from google_work_agent.application.feasibility import evidence_feasibility_risk
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    evidence_duplicate_risk,
)
from google_work_agent.application.workflows import (
    AcquisitionResultV1,
    ActionPlanDraftV1,
    AdditionalAcquisitionRequestV1,
    AgentLocalStateV1,
    AnswerDraftV1,
    ApiDiscoveryAcquisitionAgent,
    ContextBundleV1,
    ContextRetrievalAgent,
    ContextRetrievalResultV1,
    DomainValidationResult,
    DomainValidationService,
    EvidenceDraftV1,
    EvidenceSelectionOutputV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PlanReviewAgent,
    PlanReviewResultV1,
    RequestIntentV1,
    RequestUnderstandingAgent,
    RequestUnderstandingOutputV1,
    ReviewResult,
    RunBudgetV1,
    SolutionPlanningAgent,
    SourceFetchPlanV1,
    SourcePlanningOutputV1,
    SufficiencyOutputV1,
    SupervisorDecisionV1,
    SupervisorTarget,
    WorkAnalysisAgent,
    WorkAnalysisResultV1,
    WorkflowPhase,
    route_supervisor,
    validate_acquisition_result_v1,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
    validate_context_retrieval_result_v1,
)
from google_work_agent.application.workflows.profile_fused import (
    PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA,
    PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA,
    ProfilePlanningProjectionV1,
    ProfileReasonPlanOutputV1,
    ProfileRequestSourceOutputV1,
    load_profile_single_reason_plan_prompt_reference,
    load_profile_single_request_source_prompt_reference,
    load_profile_single_self_review_prompt_reference,
    load_profile_single_self_review_recheck_prompt_reference,
    load_profile_three_stage1_prompt_reference,
    load_profile_three_stage2_prompt_reference,
    validate_profile_reason_plan_output_v1,
    validate_profile_request_source_output_v1,
)
from google_work_agent.application.write_actions import (
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    ExecuteWriteActionService,
)
from google_work_agent.domain import (
    ActionStatus,
    CalendarWorkHours,
    PolicyViolationError,
    ResultCode,
    RunStatus,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    EvidenceOriginType,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    PlanRecord,
    PromptReference,
    ResourceRefRecord,
    ResourceSource,
    StoredResourceType,
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


class ParentGraphState(MultiAgentGraphState):
    """State projected from a native subgraph back to the parent graph."""

    __request__: WorkflowStartRequest
    __target__: str
    __logical_target__: str


class GraphState(TypedDict):
    """Executable graph state, including invocation-local subgraph projections."""

    schema_version: Literal[1]
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    request_intent: RequestIntentV1 | None
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    context_result: ContextRetrievalResultV1 | None
    analysis_result: WorkAnalysisResultV1 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV1 | None
    approved_plan_id: str | None
    execution_summary: dict[str, object] | None
    verification_summary: dict[str, object] | None
    finalize_intent: object | None
    user_interrupt: object | None
    retry_budget: RunBudgetV1
    prompt_context: dict[str, object]
    trace_context: dict[str, object]
    context_bundle: NotRequired[ContextBundleV1]
    evidence_drafts: NotRequired[list[EvidenceDraftV1]]
    llm_provider_result: NotRequired[dict[str, object] | None]
    __request__: WorkflowStartRequest
    __target__: str
    __logical_target__: str
    __request_agent_local__: NotRequired[AgentLocalStateV1]
    __request_output__: NotRequired[RequestUnderstandingOutputV1]
    __acquisition_agent_local__: NotRequired[AgentLocalStateV1]
    __acquisition_planning_output__: NotRequired[SourcePlanningOutputV1]
    __context_agent_local__: NotRequired[AgentLocalStateV1]
    __context_selection_output__: NotRequired[EvidenceSelectionOutputV1]
    __context_sufficiency_output__: NotRequired[SufficiencyOutputV1]
    __analysis_agent_local__: NotRequired[AgentLocalStateV1]
    __planning_agent_local__: NotRequired[AgentLocalStateV1]
    __planning_mode__: NotRequired[str]
    __planning_result__: NotRequired[AnswerDraftV1 | ActionPlanDraftV1]
    __review_agent_local__: NotRequired[AgentLocalStateV1]
    __review_mode__: NotRequired[str]
    __profile_agent_local__: NotRequired[AgentLocalStateV1]
    __profile_request_source_output__: NotRequired[ProfileRequestSourceOutputV1]
    __profile_reason_plan_output__: NotRequired[ProfileReasonPlanOutputV1]


REQUEST_AGENT_LOCAL_KEY: Final = "__request_agent_local__"
REQUEST_OUTPUT_KEY: Final = "__request_output__"
ACQUISITION_AGENT_LOCAL_KEY: Final = "__acquisition_agent_local__"
ACQUISITION_PLANNING_OUTPUT_KEY: Final = "__acquisition_planning_output__"
CONTEXT_AGENT_LOCAL_KEY: Final = "__context_agent_local__"
CONTEXT_SELECTION_OUTPUT_KEY: Final = "__context_selection_output__"
CONTEXT_SUFFICIENCY_OUTPUT_KEY: Final = "__context_sufficiency_output__"
ANALYSIS_AGENT_LOCAL_KEY: Final = "__analysis_agent_local__"
PLANNING_AGENT_LOCAL_KEY: Final = "__planning_agent_local__"
PLANNING_MODE_KEY: Final = "__planning_mode__"
REVIEW_AGENT_LOCAL_KEY: Final = "__review_agent_local__"
REVIEW_MODE_KEY: Final = "__review_mode__"
PROFILE_AGENT_LOCAL_KEY: Final = "__profile_agent_local__"
PROFILE_REQUEST_SOURCE_OUTPUT_KEY: Final = "__profile_request_source_output__"
PROFILE_REASON_PLAN_OUTPUT_KEY: Final = "__profile_reason_plan_output__"


def _require_state_value[StateValueT](
    value: StateValueT | None,
    field_name: str,
) -> StateValueT:
    if value is None:
        raise ValueError(f"graph state is missing required field: {field_name}")
    return value


def _resource_handle_for_ref(resource_ref: ResourceRefRecord) -> str:
    prefixes = {
        ("GMAIL", "THREAD"): "gmail_thread",
        ("GMAIL", "MESSAGE"): "gmail_message",
        ("TASKS", "TASK_LIST"): "task_list",
        ("TASKS", "TASK"): "task",
        ("CALENDAR", "CALENDAR"): "calendar",
        ("CALENDAR", "EVENT"): "calendar_event",
    }
    prefix = prefixes.get((resource_ref.source.value, resource_ref.resource_type.value))
    if prefix is None:
        raise LookupError(f"unsupported persisted resource reference: {resource_ref.id}")
    return f"{prefix}:{resource_ref.resource_id}"


def _acquired_resource_by_handle(
    *, acquisition_result: AcquisitionResultV1, resource_handle: str
) -> dict[str, object] | None:
    source_summaries = acquisition_result["source_summaries"]
    for summary in source_summaries:
        source = summary.get("source")
        resources = summary.get("resources")
        if not isinstance(source, str) or not isinstance(resources, list):
            continue
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            if resource.get("resource_handle") != resource_handle:
                continue
            payload = resource.get("payload")
            if not isinstance(payload, dict):
                raise LookupError(f"acquired resource payload is invalid: {resource_handle}")
            return {**resource, "source": source, "payload": payload}
    return None


def _stored_resource_type_for_acquired_resource(
    *, source: ResourceSource, resource_type: str
) -> StoredResourceType:
    mapping = {
        (ResourceSource.GMAIL, "gmail_thread"): StoredResourceType.THREAD,
        (ResourceSource.GMAIL, "gmail_message"): StoredResourceType.MESSAGE,
        (ResourceSource.TASKS, "task_list"): StoredResourceType.TASK_LIST,
        (ResourceSource.TASKS, "task"): StoredResourceType.TASK,
        (ResourceSource.CALENDAR, "calendar"): StoredResourceType.CALENDAR,
        (ResourceSource.CALENDAR, "calendar_event"): StoredResourceType.EVENT,
    }
    stored_type = mapping.get((source, resource_type))
    if stored_type is None:
        raise LookupError(f"unsupported acquired resource type: {source.value}/{resource_type}")
    return stored_type


class LangGraphWorkflowRuntime(WorkflowRuntime):
    """LangGraph runtime with selectable Stage 18 graph profiles."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        llm_runtime: Any,
        gateway: GoogleWorkspaceGateway,
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        signing_secret: str,
        service_instance_id: str,
        checkpoint_database_path: Path,
        graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path: Path | None = None,
        timezone_provider: Callable[[], str] | None = None,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._checkpoint_database_path = checkpoint_database_path
        self._graph_profile = graph_profile
        self._work_hours_provider = work_hours_provider or (
            lambda: CalendarWorkHours(timezone=(timezone_provider or (lambda: "Asia/Seoul"))())
        )
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
        self._acquisition = ApiDiscoveryAcquisitionAgent(
            llm_runtime=llm_runtime,
            gateway=gateway,
            manifest_path=prompt_manifest_path,
            now_ms=now_ms,
            timezone_provider=timezone_provider,
        )
        self._context = ContextRetrievalAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
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
            gateway=gateway,
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
            gateway=gateway,
        )
        self._require_write_reauth = RequireWriteReauthService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._recover_unknown_create = RecoverUnknownCreateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )
        self._recover_unknown_send = RecoverUnknownSendActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )
        self._recover_unknown_delete = RecoverUnknownDeleteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )
        self._recover_unknown_update = RecoverUnknownUpdateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )
        self._request_subgraph = self._build_request_subgraph()
        self._acquisition_subgraph = self._build_acquisition_subgraph()
        self._context_subgraph = self._build_context_subgraph()
        self._analysis_subgraph = self._build_analysis_subgraph()
        self._planning_subgraph = self._build_planning_subgraph()
        self._review_subgraph = self._build_review_subgraph()
        self._three_stage_one_subgraph: Any = None
        self._three_stage_two_subgraph: Any = None
        self._three_stage_review_subgraph: Any = None
        if self._graph_profile is GraphProfile.THREE_STAGE:
            self._three_stage_one_subgraph = self._build_three_stage_one_subgraph()
            self._three_stage_two_subgraph = self._build_three_stage_two_subgraph()
            self._three_stage_review_subgraph = self._build_three_stage_review_subgraph()
        self._single_workflow_subgraph: Any = None
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            self._single_workflow_subgraph = self._build_single_workflow_subgraph()
        self._native_agent_subgraphs = self._native_subgraphs_for_profile()
        self._topology = self._topology_for_profile()
        self._graph = self._build_graph()

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        config = self._config_for_thread(request.workflow_key)
        self._graph.invoke(self._initial_state(request), config=config)
        return self._result_from_thread(
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.CHECKPOINT_MISSING,
                payload={},
            )
        if not self._is_profile_compatible(cast(GraphState, snapshot.values)):
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                payload={"graph_profile": self._graph_profile.value},
            )
        self._graph.invoke(Command(resume=request.resume_payload), config=config)
        return self._result_from_thread(
            workflow_key=request.workflow_key,
            run_id=request.run_id,
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
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.CHECKPOINT_MISSING,
                payload={},
            )
        if not self._is_profile_compatible(cast(GraphState, snapshot.values)):
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                payload={"graph_profile": self._graph_profile.value},
            )
        values = cast(GraphState, snapshot.values)
        if self._latest_unknown_action(request.run_id) is not None:
            state = self._recovery_node(values)
        elif self._has_executed_action(request.run_id):
            state = self._recover_executed_actions(values, request.run_id)
        else:
            return self._result_from_thread(
                workflow_key=request.workflow_key,
                run_id=request.run_id,
            )
        return self._workflow_result_from_state(
            state=state,
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def close(self) -> None:
        self._checkpoint_connection.close()

    def _build_graph(self) -> Any:
        graph = StateGraph(GraphState)
        for name in self._topology:
            graph.add_node(name, self._node_handler(name))
        graph.add_node("domain_validation", self._domain_validation_node)
        graph.add_node("waiting_confirmation", self._waiting_confirmation_node)
        graph.add_node("waiting_approval", self._waiting_approval_node)
        graph.add_node("action_execution", self._action_execution_node)
        graph.add_node("recovery", self._recovery_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, self._topology[0])
        for name in (
            *self._topology,
            "domain_validation",
            "waiting_confirmation",
            "waiting_approval",
            "action_execution",
            "recovery",
            "finalize",
        ):
            graph.add_conditional_edges(name, self._route_next_node, self._edge_map())
        return graph.compile(checkpointer=self._checkpointer)

    def _edge_map(self) -> dict[Hashable, str]:
        edges: dict[Hashable, str] = {
            "domain_validation": "domain_validation",
            "waiting_confirmation": "waiting_confirmation",
            "waiting_approval": "waiting_approval",
            "action_execution": "action_execution",
            "recovery": "recovery",
            "finalize": "finalize",
            "end": END,
        }
        for name in self._topology:
            edges[name] = name
        return edges

    def _initial_state(self, request: WorkflowStartRequest) -> GraphState:
        return {
            "schema_version": 1,
            "run_id": request.run_id,
            "conversation_id": request.conversation_id,
            "thread_id": request.workflow_key,
            "workflow_phase": WorkflowPhase.INITIALIZE.value,
            "request_intent": None,
            "source_fetch_plans": [],
            "acquisition_result": None,
            "context_result": None,
            "analysis_result": None,
            "answer_draft": None,
            "plan_draft": None,
            "plan_review": None,
            "approved_plan_id": None,
            "execution_summary": None,
            "verification_summary": None,
            "finalize_intent": None,
            "user_interrupt": None,
            "retry_budget": {
                "schema_version": 1,
                "profile": "NORMAL",
                "llm_calls_used": 0,
                "additional_acquisitions_used": 0,
                "planning_revisions_used": 0,
                "last_rechecked_planning_revision": 0,
                "semantic_revision_signatures_used": [],
            },
            "prompt_context": {"graph_profile": self._graph_profile.value},
            "trace_context": {
                "agent_invocation_count": 0,
                "llm_call_count": 0,
                "repair_count": 0,
                "revision_count": 0,
                "agent_node_log": [],
                "prompt_refs": [],
            },
            "__request__": request,
            "__target__": self._topology[0],
            "__logical_target__": self._topology[0],
        }

    def describe_topology(self) -> tuple[str, ...]:
        return self._topology

    def graph_profile(self) -> GraphProfile:
        return self._graph_profile

    def _topology_for_profile(self) -> tuple[str, ...]:
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            return (
                "request_understanding",
                "acquisition",
                "context_retriever",
                "work_analysis",
                "planning",
                "review",
            )
        if self._graph_profile is GraphProfile.THREE_STAGE:
            return (
                "stage_one",
                "stage_two",
                "stage_three",
            )
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            return ("single_workflow",)
        raise ValueError(f"unsupported graph profile: {self._graph_profile}")

    def _node_handler(self, name: str) -> Any:
        mapping = {
            "request_understanding": self._request_subgraph,
            "acquisition": self._acquisition_subgraph,
            "context_retriever": self._context_subgraph,
            "work_analysis": self._analysis_subgraph,
            "planning": self._planning_subgraph,
            "review": self._review_subgraph,
            "single_workflow": self._single_workflow_subgraph,
            "source_planning": self._source_planning_node,
            "api_acquisition": self._api_acquisition_node,
            "context_retrieval": self._context_retrieval_node,
            "plan_review": self._plan_review_node,
            "domain_validation": self._domain_validation_node,
            "stage_one": self._three_stage_one_subgraph,
            "stage_two": self._three_stage_two_subgraph,
            "stage_three": self._three_stage_review_subgraph,
        }
        return mapping[name]

    def _native_subgraphs_for_profile(self) -> dict[str, Any]:
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            return {
                "request_understanding": self._request_subgraph,
                "acquisition": self._acquisition_subgraph,
                "context_retriever": self._context_subgraph,
                "work_analysis": self._analysis_subgraph,
                "planning": self._planning_subgraph,
                "review": self._review_subgraph,
            }
        if self._graph_profile is GraphProfile.THREE_STAGE:
            return {
                "stage_one": self._three_stage_one_subgraph,
                "stage_two": self._three_stage_two_subgraph,
                "stage_three": self._three_stage_review_subgraph,
            }
        return {"single_workflow": self._single_workflow_subgraph}

    def _build_request_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._request_subgraph_init_node)
        graph.add_node("classify", self._request_subgraph_classify_node)
        graph.add_node("finalize", self._request_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "classify")
        graph.add_edge("classify", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="request_understanding_subgraph")

    def _build_acquisition_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._acquisition_subgraph_init_node)
        graph.add_node("plan_sources", self._acquisition_subgraph_plan_sources_node)
        graph.add_node("plan_validate", self._acquisition_subgraph_plan_validate_node)
        graph.add_node("deterministic_read", self._acquisition_subgraph_read_node)
        graph.add_node("result_validate", self._acquisition_subgraph_result_validate_node)
        graph.add_node("finalize", self._acquisition_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "plan_sources")
        graph.add_edge("plan_sources", "plan_validate")
        graph.add_conditional_edges(
            "plan_validate",
            self._route_acquisition_plan_validate,
            {
                "deterministic_read": "deterministic_read",
                "finalize": "finalize",
            },
        )
        graph.add_edge("deterministic_read", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="acquisition_subgraph")

    def _request_subgraph_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="request_understanding",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_text": request.request_text,
                "entry_mode": request.entry_mode,
                "selected_resource_ids": list(request.selected_resource_ids),
            },
            prompt_ref=self._request_understanding.prompt_ref,
        )
        return {
            **state,
            REQUEST_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="request_understanding",
                agent_role="request_understanding",
                agent_invocation_id=invocation_id,
                subgraph_namespace="request_understanding",
                node_name="init",
                prompt_ref=self._request_understanding.prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _request_subgraph_classify_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding.invoke_classify_llm(request)
        output = self._request_understanding.build_output_from_llm_result(llm_result)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "CLASSIFY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            REQUEST_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="request_understanding",
                agent_role="request_understanding",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="request_understanding",
                node_name="classify",
                llm_call_id=f"{request.run_id}:request_understanding.classify",
                prompt_ref=self._request_understanding.prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
            ),
        }

    def _request_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        request = self._request_from_state(state)
        output = state[REQUEST_OUTPUT_KEY]
        decision = route_supervisor(
            phase=WorkflowPhase.REQUEST_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, output["result"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="request_understanding",
                    agent_role="request_understanding",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="request_understanding",
                    node_name="finalize",
                ),
                REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            },
            self._request_understanding.build_state_update(output, request=request),
            decision,
        )
        merged.pop(REQUEST_AGENT_LOCAL_KEY, None)
        merged.pop(REQUEST_OUTPUT_KEY, None)
        return merged

    def _acquisition_subgraph_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        additional: AdditionalAcquisitionRequestV1 | None = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if context_result is not None:
            additional = context_result["additional_acquisition_request"]
        if additional is None and analysis_result is not None:
            additional = analysis_result["additional_acquisition_request"]
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="api_discovery_acquisition",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "additional_acquisition_request": additional,
                "entry_mode": request.entry_mode,
            },
            prompt_ref=self._acquisition.prompt_ref,
        )
        next_state: GraphState = {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=invocation_id,
                subgraph_namespace="acquisition",
                node_name="init",
                prompt_ref=self._acquisition.prompt_ref,
                agent_invocation_increment=1,
            ),
        }
        return next_state

    def _acquisition_subgraph_plan_sources_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        additional: AdditionalAcquisitionRequestV1 | None = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if context_result is not None:
            additional = context_result["additional_acquisition_request"]
        if additional is None and analysis_result is not None:
            additional = analysis_result["additional_acquisition_request"]
        llm_result = self._acquisition.invoke_plan_sources_llm(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            request=request,
            additional_acquisition_request=additional,
        )
        output = self._acquisition.build_planning_output_from_llm_result(llm_result)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            ACQUISITION_PLANNING_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="plan_sources",
                llm_call_id=f"{request.run_id}:acquisition.plan_sources",
                prompt_ref=self._acquisition.prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
            ),
        }

    def _acquisition_subgraph_plan_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        source_fetch_plans = planning_output.get("source_fetch_plans")
        if not isinstance(source_fetch_plans, list):
            raise TypeError("acquisition planning output is missing source_fetch_plans")
        updated_local = dict(local_state)
        updated_local["node_state"] = "PLAN_VALIDATED"
        updated_local["typed_result"] = planning_output
        return {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="plan_validate",
            ),
        }

    def _route_acquisition_plan_validate(self, state: GraphState) -> str:
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        return "deterministic_read" if planning_output["result"] == "PLAN_READY" else "finalize"

    def _acquisition_subgraph_read_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        result = self._acquisition.acquire(
            plans=planning_output["source_fetch_plans"],
            request=request,
            request_intent=state.get("request_intent"),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "READ_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            "acquisition_result": result,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="deterministic_read",
            ),
        }

    def _acquisition_subgraph_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        acquisition_result = validate_acquisition_result_v1(state["acquisition_result"])
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], acquisition_result)
        return {
            **state,
            "acquisition_result": acquisition_result,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="result_validate",
            ),
        }

    def _acquisition_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = state[ACQUISITION_PLANNING_OUTPUT_KEY]
        current: GraphState = {
            **state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="finalize",
            ),
        }
        if planning_output["result"] != "PLAN_READY":
            decision = route_supervisor(
                phase=WorkflowPhase.SOURCE_PLANNING,
                state=cast(MultiAgentGraphState, current),
                result=planning_output,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, planning_output["result"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                self._acquisition.build_planning_state_update(planning_output),
                decision,
            )
        else:
            acquisition_result = _require_state_value(
                state["acquisition_result"], "acquisition_result"
            )
            decision = route_supervisor(
                phase=WorkflowPhase.API_ACQUISITION,
                state=cast(MultiAgentGraphState, current),
                result=acquisition_result,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, acquisition_result["status"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    **self._acquisition.build_planning_state_update(planning_output),
                    **self._acquisition.build_acquisition_state_update(acquisition_result),
                },
                decision,
            )
        merged.pop(ACQUISITION_AGENT_LOCAL_KEY, None)
        merged.pop(ACQUISITION_PLANNING_OUTPUT_KEY, None)
        return merged

    def _build_context_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._context_subgraph_init_node)
        graph.add_node("select_evidence", self._context_subgraph_select_evidence_node)
        graph.add_node("selection_validate", self._context_subgraph_selection_validate_node)
        graph.add_node("assess_sufficiency", self._context_subgraph_assess_sufficiency_node)
        graph.add_node("finalize", self._context_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "select_evidence")
        graph.add_edge("select_evidence", "selection_validate")
        graph.add_edge("selection_validate", "assess_sufficiency")
        graph.add_edge("assess_sufficiency", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="context_retriever_subgraph")

    def _build_analysis_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._analysis_subgraph_init_node)
        graph.add_node("analyze", self._analysis_subgraph_analyze_node)
        graph.add_node("result_validate", self._analysis_subgraph_result_validate_node)
        graph.add_node("finalize", self._analysis_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "analyze")
        graph.add_edge("analyze", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="work_analysis_subgraph")

    def _build_planning_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._planning_subgraph_init_node)
        graph.add_node("plan", self._planning_subgraph_plan_node)
        graph.add_node("result_validate", self._planning_subgraph_result_validate_node)
        graph.add_node("finalize", self._planning_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "plan")
        graph.add_edge("plan", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="planning_subgraph")

    def _build_review_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._review_subgraph_init_node)
        graph.add_node("review", self._review_subgraph_review_node)
        graph.add_node("result_validate", self._review_subgraph_result_validate_node)
        graph.add_node("finalize", self._review_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "review")
        graph.add_edge("review", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="review_subgraph")

    def _build_three_stage_one_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._three_stage_one_init_node)
        graph.add_node("request_source", self._three_stage_one_request_source_node)
        graph.add_node("plan_validate", self._three_stage_one_plan_validate_node)
        graph.add_node("deterministic_read", self._three_stage_one_read_node)
        graph.add_node("result_validate", self._three_stage_one_result_validate_node)
        graph.add_node("finalize", self._three_stage_one_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "request_source")
        graph.add_edge("request_source", "plan_validate")
        graph.add_conditional_edges(
            "plan_validate",
            self._route_profile_stage_one_plan_validate,
            {
                "deterministic_read": "deterministic_read",
                "finalize": "finalize",
            },
        )
        graph.add_edge("deterministic_read", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="three_stage_one_subgraph")

    def _build_three_stage_two_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._three_stage_two_init_node)
        graph.add_node("reason_plan", self._three_stage_two_reason_plan_node)
        graph.add_node("result_validate", self._three_stage_two_result_validate_node)
        graph.add_node("finalize", self._three_stage_two_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "reason_plan")
        graph.add_edge("reason_plan", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="three_stage_two_subgraph")

    def _build_three_stage_review_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._three_stage_review_init_node)
        graph.add_node("review", self._three_stage_review_node)
        graph.add_node("result_validate", self._three_stage_review_result_validate_node)
        graph.add_node("finalize", self._three_stage_review_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "review")
        graph.add_edge("review", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="three_stage_review_subgraph")

    def _build_single_workflow_subgraph(self) -> Any:
        graph = StateGraph(GraphState, output_schema=ParentGraphState)
        graph.add_node("init", self._single_workflow_init_node)
        graph.add_node("request_source", self._single_workflow_request_source_node)
        graph.add_node("plan_validate", self._single_workflow_plan_validate_node)
        graph.add_node("deterministic_read", self._single_workflow_read_node)
        graph.add_node("reason_plan", self._single_workflow_reason_plan_node)
        graph.add_node("self_review", self._single_workflow_self_review_node)
        graph.add_node("result_validate", self._single_workflow_result_validate_node)
        graph.add_node("finalize", self._single_workflow_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "request_source")
        graph.add_edge("request_source", "plan_validate")
        graph.add_conditional_edges(
            "plan_validate",
            self._route_single_workflow_plan_validate,
            {
                "deterministic_read": "deterministic_read",
                "reason_plan": "reason_plan",
                "finalize": "finalize",
            },
        )
        graph.add_edge("deterministic_read", "reason_plan")
        graph.add_edge("reason_plan", "self_review")
        graph.add_edge("self_review", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="single_workflow_subgraph")

    def _context_subgraph_init_node(self, state: GraphState) -> GraphState:
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="context_retriever",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "acquisition_result": _require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
            },
            prompt_ref=self._context.select_prompt_ref,
        )
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=invocation_id,
                subgraph_namespace="context",
                node_name="init",
                prompt_ref=self._context.select_prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _context_subgraph_select_evidence_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        acquisition_result = _require_state_value(state["acquisition_result"], "acquisition_result")
        segments = self._context.build_segments_from_acquisition(acquisition_result)
        selection = self._context.select_evidence(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            acquisition_result=acquisition_result,
            request=request,
            segments=cast(list[Any], segments),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECT_EVIDENCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            CONTEXT_SELECTION_OUTPUT_KEY: selection,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="select_evidence",
                llm_call_id=f"{request.run_id}:context.select_evidence",
                prompt_ref=self._context.select_prompt_ref,
                llm_call_increment=1,
            ),
        }

    def _context_subgraph_selection_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        acquisition_result = _require_state_value(state["acquisition_result"], "acquisition_result")
        draft_bundle, evidence_drafts = self._context.build_draft_context_bundle(
            selection_result=selection,
            acquisition_result=acquisition_result,
            missing_information=selection["missing_information"],
            ambiguity=selection["ambiguity"],
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SELECTION_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], selection)
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "context_bundle": draft_bundle,
            "evidence_drafts": evidence_drafts,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="selection_validate",
            ),
        }

    def _context_subgraph_assess_sufficiency_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        sufficiency_result, llm_provider_result = self._context.assess_sufficiency(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            request=request,
            context_bundle=state["context_bundle"],
            evidence_drafts=state["evidence_drafts"],
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "SUFFICIENCY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], sufficiency_result)
        return {
            **state,
            CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            CONTEXT_SUFFICIENCY_OUTPUT_KEY: sufficiency_result,
            "llm_provider_result": llm_provider_result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="context_retriever",
                agent_role="context_retriever",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="context",
                node_name="assess_sufficiency",
                llm_call_id=f"{request.run_id}:context.assess_sufficiency",
                prompt_ref=self._context.sufficiency_prompt_ref,
                llm_call_increment=1,
            ),
        }

    def _context_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[CONTEXT_AGENT_LOCAL_KEY])
        selection = state[CONTEXT_SELECTION_OUTPUT_KEY]
        sufficiency = state[CONTEXT_SUFFICIENCY_OUTPUT_KEY]
        llm_provider_result = _require_state_value(
            state.get("llm_provider_result"), "llm_provider_result"
        )
        result = validate_context_retrieval_result_v1(
            self._context.build_result_from_outputs(
                selection_result=selection,
                sufficiency_result=sufficiency,
                acquisition_result=_require_state_value(
                    state["acquisition_result"], "acquisition_result"
                ),
                llm_provider_result=llm_provider_result,
            )
        )
        decision = route_supervisor(
            phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                CONTEXT_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="context_retriever",
                    agent_role="context_retriever",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="context",
                    node_name="finalize",
                ),
            },
            self._context.build_state_update(result),
            decision,
        )
        merged.pop(CONTEXT_AGENT_LOCAL_KEY, None)
        merged.pop(CONTEXT_SELECTION_OUTPUT_KEY, None)
        merged.pop(CONTEXT_SUFFICIENCY_OUTPUT_KEY, None)
        merged.pop("evidence_drafts", None)
        merged.pop("llm_provider_result", None)
        return merged

    def _analysis_subgraph_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="work_analysis",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": _require_state_value(state["request_intent"], "request_intent"),
                "context_result": _require_state_value(state["context_result"], "context_result"),
            },
            prompt_ref=self._analysis.analyze_prompt_ref,
        )
        return {
            **state,
            ANALYSIS_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="work_analysis",
                agent_role="work_analysis",
                agent_invocation_id=invocation_id,
                subgraph_namespace="analysis",
                node_name="init",
                prompt_ref=self._analysis.analyze_prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _analysis_subgraph_analyze_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        llm_result = self._analysis.invoke_analyze_llm(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            context_result=_require_state_value(state["context_result"], "context_result"),
            request=request,
        )
        result = self._analysis.build_output_from_llm_result(
            llm_result,
            context_result=_require_state_value(state["context_result"], "context_result"),
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "ANALYZE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            ANALYSIS_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "analysis_result": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="work_analysis",
                agent_role="work_analysis",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="analysis",
                node_name="analyze",
                llm_call_id=f"{request.run_id}:analysis.analyze",
                prompt_ref=self._analysis.analyze_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _analysis_subgraph_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        result = _require_state_value(state["analysis_result"], "analysis_result")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            ANALYSIS_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "analysis_result": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="work_analysis",
                agent_role="work_analysis",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="analysis",
                node_name="result_validate",
            ),
        }

    def _analysis_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ANALYSIS_AGENT_LOCAL_KEY])
        result = _require_state_value(state["analysis_result"], "analysis_result")
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                ANALYSIS_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="work_analysis",
                    agent_role="work_analysis",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="analysis",
                    node_name="finalize",
                ),
            },
            self._analysis.build_state_update(result),
            decision,
        )
        merged.pop(ANALYSIS_AGENT_LOCAL_KEY, None)
        return merged

    def _planning_subgraph_init_node(self, state: GraphState) -> GraphState:
        invocation_id = self._id_factory()
        review = state["plan_review"]
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        analysis_result = _require_state_value(state["analysis_result"], "analysis_result")
        mode = self._planning_mode_from_request_intent(request_intent)
        if review is not None and review.get("status") == ReviewResult.REVISE.value:
            mode = "revise_answer" if state.get("answer_draft") is not None else "revise_plan"
        prompt_ref = {
            "answer_only": self._planning.answer_only_prompt_ref,
            "draft_plan": self._planning.draft_plan_prompt_ref,
            "revise_answer": self._planning.revise_answer_prompt_ref,
            "revise_plan": self._planning.revise_plan_prompt_ref,
        }[mode]
        local_state = build_agent_local_state(
            agent_role="planning",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": request_intent,
                "analysis_result": analysis_result,
                "mode": mode,
            },
            prompt_ref=prompt_ref,
        )
        return {
            **state,
            PLANNING_AGENT_LOCAL_KEY: local_state,
            PLANNING_MODE_KEY: mode,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="planning",
                agent_role="planning",
                agent_invocation_id=invocation_id,
                subgraph_namespace="planning",
                node_name="init",
                prompt_ref=prompt_ref,
                agent_invocation_increment=1,
                revision_increment=1 if mode.startswith("revise") else 0,
            ),
        }

    def _planning_subgraph_plan_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
        review_state = state["plan_review"]
        review_issues: list[dict[str, object]] = []
        review_summary: str | None = None
        if review_state is not None:
            review_issues = [dict(issue) for issue in review_state["issues"]]
            review_summary = review_state.get("summary")
        result: AnswerDraftV1 | ActionPlanDraftV1
        if mode == "answer_only":
            llm_result = self._planning.invoke_answer_only_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
            )
            result = self._planning.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            llm_call_id = f"{request.run_id}:planning.answer_only"
        elif mode == "draft_plan":
            llm_result = self._planning.invoke_draft_plan_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
            )
            result = self._planning.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            llm_call_id = f"{request.run_id}:planning.draft_plan"
        elif mode == "revise_answer":
            llm_result = self._planning.invoke_revise_answer_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                answer_draft=_require_state_value(state["answer_draft"], "answer_draft"),
                review_issues=review_issues,
                review_summary=review_summary,
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
            )
            result = self._planning.build_answer_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            llm_call_id = f"{request.run_id}:planning.revise_answer"
        else:
            llm_result = self._planning.invoke_revise_plan_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                plan_draft=_require_state_value(state["plan_draft"], "plan_draft"),
                review_issues=review_issues,
                review_summary=review_summary,
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                request=request,
            )
            result = self._planning.build_plan_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            llm_call_id = f"{request.run_id}:planning.revise_plan"
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "__planning_result__": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="planning",
                agent_role="planning",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="planning",
                node_name="plan",
                llm_call_id=llm_call_id,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _planning_subgraph_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        result = state["__planning_result__"]
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = result
        return {
            **state,
            PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="planning",
                agent_role="planning",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="planning",
                node_name="result_validate",
            ),
        }

    def _planning_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PLANNING_AGENT_LOCAL_KEY])
        mode = state[PLANNING_MODE_KEY]
        result = state["__planning_result__"]
        if "answer" in result:
            answer_result = validate_answer_draft_v1(
                result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            state_update = self._planning.build_answer_state_update(answer_result)
        else:
            plan_result = validate_action_plan_draft_v1(
                result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
            )
            state_update = self._planning.build_plan_state_update(plan_result)
        decision = route_supervisor(
            phase=WorkflowPhase.SOLUTION_PLANNING,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                PLANNING_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="planning",
                    agent_role="planning",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="planning",
                    node_name="finalize",
                    revision_increment=1 if mode == "revise_plan" else 0,
                ),
            },
            state_update,
            decision,
        )
        merged.pop(PLANNING_AGENT_LOCAL_KEY, None)
        merged.pop(PLANNING_MODE_KEY, None)
        merged.pop("__planning_result__", None)
        return merged

    def _review_subgraph_init_node(self, state: GraphState) -> GraphState:
        invocation_id = self._id_factory()
        review = state["plan_review"]
        mode = (
            "recheck"
            if review is not None and review.get("status") == ReviewResult.REVISE.value
            else "inspect"
        )
        prompt_ref = (
            self._review.recheck_prompt_ref
            if mode == "recheck"
            else self._review.inspect_prompt_ref
        )
        local_state = build_agent_local_state(
            agent_role="review",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "mode": mode,
                "has_answer_draft": state.get("answer_draft") is not None,
                "has_plan_draft": state.get("plan_draft") is not None,
            },
            prompt_ref=prompt_ref,
        )
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: local_state,
            REVIEW_MODE_KEY: mode,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="review",
                agent_role="review",
                agent_invocation_id=invocation_id,
                subgraph_namespace="review",
                node_name="init",
                prompt_ref=prompt_ref,
                agent_invocation_increment=1,
                revision_increment=1 if mode == "recheck" else 0,
            ),
        }

    def _review_subgraph_review_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        mode = state[REVIEW_MODE_KEY]
        if mode == "recheck":
            llm_result = self._review.invoke_recheck_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
            result = self._review.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                allowed_statuses=frozenset({ReviewResult.PASS.value, ReviewResult.BLOCK.value}),
            )
            llm_call_id = f"{request.run_id}:review.recheck"
        else:
            llm_result = self._review.invoke_inspect_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
            result = self._review.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
            )
            llm_call_id = f"{request.run_id}:review.inspect"
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "plan_review": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="review",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="review",
                node_name="review",
                llm_call_id=llm_call_id,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _review_subgraph_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "plan_review": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="review",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="review",
                node_name="result_validate",
            ),
        }

    def _review_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="review",
                    agent_role="review",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="review",
                    node_name="finalize",
                ),
            },
            self._review.build_state_update(result),
            decision,
        )
        merged.pop(REVIEW_AGENT_LOCAL_KEY, None)
        merged.pop(REVIEW_MODE_KEY, None)
        return merged

    def _three_stage_one_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="request_source_agent",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection=self._profile_request_source_prompt_input(request),
            prompt_ref=self._three_stage1_prompt_ref,
        )
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=invocation_id,
                subgraph_namespace="three.stage1",
                node_name="init",
                prompt_ref=self._three_stage1_prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _three_stage_one_request_source_node(self, state: GraphState) -> GraphState:
        assert self._three_stage1_prompt_ref is not None
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding._llm_runtime.invoke_structured(
            prompt_ref=self._three_stage1_prompt_ref,
            prompt_input=self._profile_request_source_prompt_input(request),
            output_schema=PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA,
            trace_context=self._profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.three.stage1.initial",
            ),
        )
        output = validate_profile_request_source_output_v1(llm_result.structured_output)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REQUEST_SOURCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            PROFILE_REQUEST_SOURCE_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="request_source",
                llm_call_id=f"{request.run_id}:profile.three.stage1.initial",
                prompt_ref=self._three_stage1_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _three_stage_one_plan_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        updated_local = dict(local_state)
        updated_local["node_state"] = "PLAN_VALIDATED"
        updated_local["typed_result"] = prompt_output
        next_state: GraphState = {
            **state,
            "request_intent": prompt_output["request_intent"],
            "source_fetch_plans": source_plan["source_fetch_plans"],
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="plan_validate",
            ),
        }
        if source_plan["result"] == "NO_FETCH_NEEDED":
            next_state["acquisition_result"] = self._build_no_fetch_acquisition_result()
        return next_state

    def _route_profile_stage_one_plan_validate(self, state: GraphState) -> str:
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        return "deterministic_read" if source_plan["result"] == "PLAN_READY" else "finalize"

    def _route_single_workflow_plan_validate(self, state: GraphState) -> str:
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        if source_plan["result"] == "PLAN_READY":
            return "deterministic_read"
        if source_plan["result"] == "NO_FETCH_NEEDED":
            return "reason_plan"
        return "finalize"

    def _three_stage_one_read_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        result = self._acquisition.acquire(
            plans=state["source_fetch_plans"],
            request=request,
            request_intent=state.get("request_intent"),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "READ_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            "acquisition_result": result,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="deterministic_read",
            ),
        }

    def _three_stage_one_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        acquisition_result = validate_acquisition_result_v1(state["acquisition_result"])
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], acquisition_result)
        return {
            **state,
            "acquisition_result": acquisition_result,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="result_validate",
            ),
        }

    def _three_stage_one_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        request_intent = prompt_output["request_intent"]
        current: GraphState = {
            **state,
            "request_intent": request_intent,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="finalize",
            ),
        }
        if source_plan["result"] != "PLAN_READY":
            decision = route_supervisor(
                phase=WorkflowPhase.SOURCE_PLANNING,
                state=cast(MultiAgentGraphState, current),
                result=source_plan,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, source_plan["result"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    "request_intent": request_intent,
                    **self._acquisition.build_planning_state_update(source_plan),
                },
                decision,
            )
        else:
            acquisition_result = _require_state_value(
                state["acquisition_result"], "acquisition_result"
            )
            decision = route_supervisor(
                phase=WorkflowPhase.API_ACQUISITION,
                state=cast(MultiAgentGraphState, current),
                result=acquisition_result,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, acquisition_result["status"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    "request_intent": request_intent,
                    **self._acquisition.build_planning_state_update(source_plan),
                    **self._acquisition.build_acquisition_state_update(acquisition_result),
                },
                decision,
            )
        merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
        merged.pop(PROFILE_REQUEST_SOURCE_OUTPUT_KEY, None)
        return merged

    def _three_stage_two_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="evidence_analysis_plan_agent",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection=self._profile_post_read_prompt_input(state),
            prompt_ref=self._three_stage2_prompt_ref,
        )
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_two",
                agent_role="evidence_analysis_plan_agent",
                agent_invocation_id=invocation_id,
                subgraph_namespace="three.stage2",
                node_name="init",
                prompt_ref=self._three_stage2_prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _three_stage_two_reason_plan_node(self, state: GraphState) -> GraphState:
        assert self._three_stage2_prompt_ref is not None
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding._llm_runtime.invoke_structured(
            prompt_ref=self._three_stage2_prompt_ref,
            prompt_input=self._profile_post_read_prompt_input(state),
            output_schema=PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA,
            trace_context=self._profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.three.stage2.initial",
            ),
        )
        output = validate_profile_reason_plan_output_v1(llm_result.structured_output)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REASON_PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            PROFILE_REASON_PLAN_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_two",
                agent_role="evidence_analysis_plan_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage2",
                node_name="reason_plan",
                llm_call_id=f"{request.run_id}:profile.three.stage2.initial",
                prompt_ref=self._three_stage2_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _three_stage_two_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        output = state[PROFILE_REASON_PLAN_OUTPUT_KEY]
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = output
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_two",
                agent_role="evidence_analysis_plan_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage2",
                node_name="result_validate",
            ),
        }

    def _three_stage_two_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        output = state[PROFILE_REASON_PLAN_OUTPUT_KEY]
        context_result = output["context_result"]
        analysis_result = output["analysis_result"]
        planning_result = output["planning_result"]
        result = self._planning_result_from_projection(planning_result)
        state_update = self._profile_reason_plan_state_update(output)
        decision = route_supervisor(
            phase=WorkflowPhase.SOLUTION_PLANNING,
            state=cast(
                MultiAgentGraphState,
                {
                    **state,
                    "context_result": context_result,
                    "analysis_result": analysis_result,
                },
            ),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="stage_two",
                    agent_role="evidence_analysis_plan_agent",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="three.stage2",
                    node_name="finalize",
                ),
            },
            state_update,
            decision,
        )
        merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
        merged.pop(PROFILE_REASON_PLAN_OUTPUT_KEY, None)
        return merged

    def _three_stage_review_init_node(self, state: GraphState) -> GraphState:
        invocation_id = self._id_factory()
        review = state["plan_review"]
        mode = (
            "recheck"
            if review is not None and review.get("status") == ReviewResult.REVISE.value
            else "inspect"
        )
        prompt_ref = (
            self._review.recheck_prompt_ref
            if mode == "recheck"
            else self._review.inspect_prompt_ref
        )
        local_state = build_agent_local_state(
            agent_role="review",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={"mode": mode},
            prompt_ref=prompt_ref,
        )
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: local_state,
            REVIEW_MODE_KEY: mode,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_three",
                agent_role="review",
                agent_invocation_id=invocation_id,
                subgraph_namespace="three.stage3",
                node_name="init",
                prompt_ref=prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _three_stage_review_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        mode = state[REVIEW_MODE_KEY]
        if mode == "recheck":
            llm_result = self._review.invoke_recheck_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
            result = self._review.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                allowed_statuses=frozenset({ReviewResult.PASS.value, ReviewResult.BLOCK.value}),
            )
            llm_call_id = f"{request.run_id}:review.recheck"
        else:
            llm_result = self._review.invoke_inspect_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
            result = self._review.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
            )
            llm_call_id = f"{request.run_id}:review.inspect"
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "plan_review": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_three",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage3",
                node_name="review",
                llm_call_id=llm_call_id,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _three_stage_review_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = result
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_three",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage3",
                node_name="result_validate",
            ),
        }

    def _three_stage_review_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="stage_three",
                    agent_role="review",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="three.stage3",
                    node_name="finalize",
                ),
            },
            self._review.build_state_update(result),
            decision,
        )
        merged.pop(REVIEW_AGENT_LOCAL_KEY, None)
        merged.pop(REVIEW_MODE_KEY, None)
        return merged

    def _single_workflow_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="unified_agent",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection=self._profile_request_source_prompt_input(request),
            prompt_ref=self._single_request_source_prompt_ref,
        )
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=invocation_id,
                subgraph_namespace="single",
                node_name="init",
                prompt_ref=self._single_request_source_prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _single_workflow_request_source_node(self, state: GraphState) -> GraphState:
        assert self._single_request_source_prompt_ref is not None
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding._llm_runtime.invoke_structured(
            prompt_ref=self._single_request_source_prompt_ref,
            prompt_input=self._profile_request_source_prompt_input(request),
            output_schema=PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA,
            trace_context=self._profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.single.request_source.initial",
            ),
        )
        output = validate_profile_request_source_output_v1(llm_result.structured_output)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REQUEST_SOURCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            PROFILE_REQUEST_SOURCE_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="request_source",
                llm_call_id=f"{request.run_id}:profile.single.request_source.initial",
                prompt_ref=self._single_request_source_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _single_workflow_plan_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        updated_local = dict(local_state)
        updated_local["node_state"] = "PLAN_VALIDATED"
        updated_local["typed_result"] = prompt_output
        next_state: GraphState = {
            **state,
            "request_intent": prompt_output["request_intent"],
            "source_fetch_plans": source_plan["source_fetch_plans"],
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="plan_validate",
            ),
        }
        if source_plan["result"] == "NO_FETCH_NEEDED":
            next_state["acquisition_result"] = self._build_no_fetch_acquisition_result()
        return next_state

    def _single_workflow_read_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        result = self._acquisition.acquire(
            plans=state["source_fetch_plans"],
            request=request,
            request_intent=state.get("request_intent"),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "READ_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            "acquisition_result": result,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="deterministic_read",
            ),
        }

    def _single_workflow_reason_plan_node(self, state: GraphState) -> GraphState:
        assert self._single_reason_plan_prompt_ref is not None
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding._llm_runtime.invoke_structured(
            prompt_ref=self._single_reason_plan_prompt_ref,
            prompt_input=self._profile_post_read_prompt_input(state),
            output_schema=PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA,
            trace_context=self._profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.single.reason_plan.initial",
            ),
        )
        output = validate_profile_reason_plan_output_v1(llm_result.structured_output)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REASON_PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            PROFILE_REASON_PLAN_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="reason_plan",
                llm_call_id=f"{request.run_id}:profile.single.reason_plan.initial",
                prompt_ref=self._single_reason_plan_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _single_workflow_self_review_node(self, state: GraphState) -> GraphState:
        assert self._single_review is not None
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        output = state[PROFILE_REASON_PLAN_OUTPUT_KEY]
        planning_result = output["planning_result"]
        result = self._planning_result_from_projection(planning_result)
        answer_draft = (
            validate_answer_draft_v1(result, analysis_result=output["analysis_result"])
            if "answer" in result
            else None
        )
        plan_draft = (
            validate_action_plan_draft_v1(result, analysis_result=output["analysis_result"])
            if "plan_id" in result
            else None
        )
        llm_result = self._single_review.invoke_inspect_llm(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            context_result=output["context_result"],
            analysis_result=output["analysis_result"],
            answer_draft=answer_draft,
            plan_draft=plan_draft,
            request=request,
        )
        review_result = self._single_review.build_output_from_llm_result(
            llm_result,
            analysis_result=output["analysis_result"],
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "SELF_REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], review_result)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "context_result": output["context_result"],
            "analysis_result": output["analysis_result"],
            **self._profile_planning_state_update(
                planning_result,
                analysis_result=output["analysis_result"],
            ),
            "plan_review": review_result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="self_review",
                llm_call_id=f"{request.run_id}:profile.single.self_review.initial",
                prompt_ref=self._single_review.inspect_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _single_workflow_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        review_result = _require_state_value(state["plan_review"], "plan_review")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = review_result
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="result_validate",
            ),
        }

    def _single_workflow_finalize_node(self, state: GraphState) -> GraphState:
        assert self._single_review is not None
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        if state.get("plan_review") is None:
            prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
            source_plan = prompt_output["source_plan"]
            request_intent = prompt_output["request_intent"]
            current: GraphState = {
                **state,
                "request_intent": request_intent,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="single_workflow",
                    agent_role="unified_agent",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="single",
                    node_name="finalize",
                ),
            }
            decision = route_supervisor(
                phase=WorkflowPhase.SOURCE_PLANNING,
                state=cast(MultiAgentGraphState, current),
                result=source_plan,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, source_plan["result"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    "request_intent": request_intent,
                    **self._acquisition.build_planning_state_update(source_plan),
                },
                decision,
            )
            merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
            merged.pop(PROFILE_REQUEST_SOURCE_OUTPUT_KEY, None)
            return merged
        result = _require_state_value(state["plan_review"], "plan_review")
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="single_workflow",
                    agent_role="unified_agent",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="single",
                    node_name="finalize",
                ),
            },
            self._single_review.build_state_update(result),
            decision,
        )
        merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
        merged.pop(PROFILE_REASON_PLAN_OUTPUT_KEY, None)
        return merged

    def _profile_request_source_prompt_input(
        self,
        request: WorkflowStartRequest,
    ) -> dict[str, object]:
        return {
            "request_text": request.request_text,
            "entry_mode": request.entry_mode,
            "selected_resource_ids": list(request.selected_resource_ids),
        }

    def _profile_post_read_prompt_input(self, state: GraphState) -> dict[str, object]:
        request = self._request_from_state(state)
        return {
            "request_text": request.request_text,
            "request_intent": _require_state_value(state["request_intent"], "request_intent"),
            "acquisition_result": _require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
        }

    def _profile_trace_context(
        self,
        *,
        request: WorkflowStartRequest,
        llm_call_id: str,
    ) -> ObservabilityContext:
        return ObservabilityContext(
            request_id=request.correlation.request_id,
            command_id=request.correlation.command_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            langgraph_thread_id=request.workflow_key,
            llm_call_id=llm_call_id,
        )

    def _planning_result_from_projection(
        self,
        planning_result: ProfilePlanningProjectionV1,
    ) -> AnswerDraftV1 | ActionPlanDraftV1:
        answer_draft = planning_result["answer_draft"]
        if answer_draft is not None:
            return answer_draft
        plan_draft = planning_result["plan_draft"]
        if plan_draft is not None:
            return plan_draft
        raise ValueError("planning_result must contain answer_draft or plan_draft")

    def _profile_reason_plan_state_update(
        self,
        output: ProfileReasonPlanOutputV1,
    ) -> GraphStateUpdateV1:
        planning_result = output["planning_result"]
        return {
            "context_result": output["context_result"],
            "analysis_result": output["analysis_result"],
            **self._profile_planning_state_update(
                planning_result,
                analysis_result=output["analysis_result"],
            ),
        }

    def _profile_planning_state_update(
        self,
        planning_result: ProfilePlanningProjectionV1,
        *,
        analysis_result: WorkAnalysisResultV1,
    ) -> GraphStateUpdateV1:
        result = self._planning_result_from_projection(planning_result)
        if "answer" in result:
            answer_result = validate_answer_draft_v1(result, analysis_result=analysis_result)
            return self._planning.build_answer_state_update(answer_result)
        plan_result = validate_action_plan_draft_v1(result, analysis_result=analysis_result)
        return self._planning.build_plan_state_update(plan_result)

    def _build_no_fetch_acquisition_result(self) -> AcquisitionResultV1:
        return {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": [],
            "source_summaries": [],
            "missing_slots": [],
            "remaining_budget": {
                "sources": 0,
                "pages": 0,
                "candidates": 0,
                "details": 0,
            },
        }

    def _request_understanding_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        output = self._request_understanding.classify(request)
        decision = route_supervisor(
            phase=WorkflowPhase.REQUEST_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        return self._merge_decision(
            state,
            self._request_understanding.build_state_update(output, request=request),
            decision,
        )

    def _source_planning_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        additional: AdditionalAcquisitionRequestV1 | None = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if context_result is not None:
            additional = context_result["additional_acquisition_request"]
        if additional is None and analysis_result is not None:
            additional = analysis_result["additional_acquisition_request"]
        output = self._acquisition.plan_sources(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            request=request,
            additional_acquisition_request=additional,
        )
        decision = route_supervisor(
            phase=WorkflowPhase.SOURCE_PLANNING,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        return self._merge_decision(
            state, self._acquisition.build_planning_state_update(output), decision
        )

    def _api_acquisition_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        result = self._acquisition.acquire(
            plans=state["source_fetch_plans"],
            request=request,
            request_intent=state.get("request_intent"),
        )
        decision = route_supervisor(
            phase=WorkflowPhase.API_ACQUISITION,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(
            state, self._acquisition.build_acquisition_state_update(result), decision
        )

    def _context_retrieval_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        result = self._context.retrieve(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            request=request,
        )
        decision = route_supervisor(
            phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(state, self._context.build_state_update(result), decision)

    def _work_analysis_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        result = self._analysis.analyze(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            context_result=_require_state_value(state["context_result"], "context_result"),
            request=request,
        )
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(state, self._analysis.build_state_update(result), decision)

    def _plan_review_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        review = state["plan_review"]
        if review is not None and review.get("status") == ReviewResult.REVISE.value:
            result = self._review.recheck(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
        else:
            result = self._review.inspect(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(state, self._review.build_state_update(result), decision)

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
        if result["result"] == DomainValidationResult.REQUIRE_APPROVAL.value:
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
        _ = interrupt(payload)
        return {
            **state,
            "__target__": "action_execution",
            "workflow_phase": WorkflowPhase.PREFLIGHT.value,
        }

    def _action_execution_node(self, state: GraphState) -> GraphState:
        run_id = cast(str, state["run_id"])
        if self._should_stop_for_cancel(run_id):
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                "execution_summary": {"result": "CANCEL_REQUESTED"},
            }
        plan_id = self._required_string(state.get("approved_plan_id"), "approved_plan_id")
        actions = self._list_actions(plan_id)
        if actions and all(action.effect_type == "READ" for action in actions):
            return self._execute_read_only_plan(state, plan_id, actions)

        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(cast(str, state["run_id"]))
            if run is None:
                raise LookupError(f"run not found: {state['run_id']}")
            if run.status != RunStatus.VERIFYING:
                unit_of_work.runs.set_verifying(cast(str, state["run_id"]))
                unit_of_work.commit()
        verification_statuses: list[str] = []
        for action in actions:
            if self._should_stop_for_cancel(run_id):
                return {
                    **state,
                    "__target__": "end",
                    "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                    "execution_summary": {"result": "CANCEL_REQUESTED", "plan_id": plan_id},
                    "verification_summary": {"action_statuses": verification_statuses},
                }
            if action.status in {
                ActionStatus.VERIFIED.value,
                ActionStatus.MISMATCH.value,
                ActionStatus.FAILED.value,
                ActionStatus.BLOCKED.value,
                ActionStatus.DEPENDENCY_BLOCKED.value,
            }:
                verification_statuses.append(action.status)
                continue
            if action.status != ActionStatus.APPROVED.value:
                continue
            try:
                self._preflight_write(action_id=action.id)
            except (GoogleWorkspaceGatewayError, LookupError, PolicyViolationError) as error:
                refreshed = next(
                    (item for item in self._list_actions(plan_id) if item.id == action.id),
                    None,
                )
                if refreshed is not None and refreshed.status == ActionStatus.MODIFIED.value:
                    _ = interrupt(
                        {
                            "interrupt_kind": "APPROVAL",
                            "run_id": run_id,
                            "plan_id": plan_id,
                            "action_id": action.id,
                            "reason": "PREFLIGHT_REAPPROVAL_REQUIRED",
                        }
                    )
                    return {
                        **state,
                        "__target__": "action_execution",
                        "workflow_phase": WorkflowPhase.PREFLIGHT.value,
                    }
                return {
                    **state,
                    "__target__": "end",
                    "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                    "execution_summary": {
                        "result": "PREFLIGHT_BLOCKED",
                        "action_id": action.id,
                        "safe_error_code": type(error).__name__,
                    },
                }
            if self._should_stop_for_cancel(run_id):
                return {
                    **state,
                    "__target__": "end",
                    "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                    "execution_summary": {"result": "CANCEL_REQUESTED", "plan_id": plan_id},
                    "verification_summary": {"action_statuses": verification_statuses},
                }
            claim_response = self._claim_write(
                ClaimWriteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "claim", "action_id": action.id}),
                    action_id=action.id,
                    expected_version=action.version,
                    source_snapshot={},
                    attempt_id=self._id_factory(),
                    nonce=self._id_factory(),
                )
            )
            if (
                not claim_response.applied
                or claim_response.claim_token is None
                or claim_response.attempt_id is None
            ):
                continue
            if self._should_stop_for_cancel(run_id):
                self._mark_write_failed(
                    MarkWriteActionFailedCommand(
                        command_id=self._id_factory(),
                        request_hash=self._request_hash(
                            {"kind": "cancel_before_write", "action_id": action.id}
                        ),
                        action_id=action.id,
                        attempt_id=self._required_string(claim_response.attempt_id, "attempt_id"),
                        expected_action_version=claim_response.action_version,
                        expected_attempt_version=0,
                        error_code="CANCEL_REQUESTED",
                        error_detail="write was not sent because cancellation was requested",
                    )
                )
                verification_statuses.append(ActionStatus.FAILED.value)
                return {
                    **state,
                    "__target__": "end",
                    "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                    "execution_summary": {"result": "CANCEL_REQUESTED", "plan_id": plan_id},
                    "verification_summary": {"action_statuses": verification_statuses},
                }
            try:
                executed = self._execute_write(
                    action_id=action.id,
                    claim_token=claim_response.claim_token,
                )
            except GoogleWorkspaceGatewayError as error:
                if error.code in {
                    GoogleWorkspaceErrorCode.AUTH_EXPIRED,
                    GoogleWorkspaceErrorCode.PERMISSION_DENIED,
                }:
                    self._require_write_reauth(
                        RequireWriteReauthCommand(
                            command_id=self._id_factory(),
                            request_hash=self._request_hash(
                                {"kind": "reauth", "action_id": action.id}
                            ),
                            run_id=cast(str, state["run_id"]),
                            action_id=action.id,
                            safe_error_code=error.code.value,
                        )
                    )
                    return {
                        **state,
                        "__target__": "end",
                        "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                        "execution_summary": {"result": "REAUTH_REQUIRED", "action_id": action.id},
                    }
                if error.delivery_certainty is not DeliveryCertainty.NOT_SENT:
                    unknown = self._mark_write_unknown(
                        MarkWriteActionUnknownResultCommand(
                            command_id=self._id_factory(),
                            request_hash=self._request_hash(
                                {"kind": "unknown", "action_id": action.id}
                            ),
                            action_id=action.id,
                            attempt_id=self._required_string(
                                claim_response.attempt_id, "attempt_id"
                            ),
                            expected_action_version=claim_response.action_version,
                            expected_attempt_version=0,
                            error_code=error.code.value,
                            error_detail=str(error),
                        )
                    )
                    return {
                        **state,
                        "__target__": "recovery",
                        "workflow_phase": WorkflowPhase.RECOVERY.value,
                        "execution_summary": {
                            "result": unknown.result_code,
                            "action_id": action.id,
                            "safe_error_code": error.code.value,
                        },
                    }
                self._mark_write_failed(
                    MarkWriteActionFailedCommand(
                        command_id=self._id_factory(),
                        request_hash=self._request_hash({"kind": "failed", "action_id": action.id}),
                        action_id=action.id,
                        attempt_id=self._required_string(claim_response.attempt_id, "attempt_id"),
                        expected_action_version=claim_response.action_version,
                        expected_attempt_version=0,
                        error_code=error.code.value,
                        error_detail=str(error),
                    )
                )
                verification_statuses.append(ActionStatus.FAILED.value)
                continue

            stored = self._store_write_success(
                StoreWriteActionSuccessCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "store_success", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=self._required_string(claim_response.attempt_id, "attempt_id"),
                    expected_action_version=claim_response.action_version,
                    expected_attempt_version=0,
                    snapshot=executed.snapshot,
                )
            )
            verified = self._verify_write(
                VerifyWriteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "verify", "action_id": action.id}),
                    action_id=action.id,
                    attempt_id=self._required_string(stored.attempt_id, "attempt_id"),
                    expected_action_version=stored.action_version,
                    verification_id=self._id_factory(),
                )
            )
            verification_statuses.append(verified.action_status)
            if self._should_stop_for_cancel(run_id):
                return {
                    **state,
                    "__target__": "end",
                    "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                    "execution_summary": {"result": "CANCEL_REQUESTED", "plan_id": plan_id},
                    "verification_summary": {"action_statuses": verification_statuses},
                }
        if (
            actions
            and verification_statuses
            and all(status == ActionStatus.VERIFIED.value for status in verification_statuses)
            and not self._has_persisted_cancel_intent(run_id)
        ):
            self._complete_write_run(
                CompleteWriteRunCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "complete_write_run", "run_id": state["run_id"]}
                    ),
                    run_id=cast(str, state["run_id"]),
                    expected_version=self._current_run_version(cast(str, state["run_id"])),
                )
            )
        return {
            **state,
            "__target__": "finalize",
            "workflow_phase": WorkflowPhase.VERIFICATION.value,
            "execution_summary": {"result": "EXECUTED", "plan_id": plan_id},
            "verification_summary": {"action_statuses": verification_statuses},
        }

    def _recovery_node(self, state: GraphState) -> GraphState:
        unknown_action = self._latest_unknown_action(cast(str, state["run_id"]))
        if unknown_action is None:
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
            }
        action, attempt_id, attempt_version = unknown_action
        if action.effect_type == "CREATE":
            response = self._recover_unknown_create(
                RecoverUnknownCreateActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "recover_create", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=action.version,
                    expected_attempt_version=attempt_version,
                )
            )
        elif action.effect_type == "SEND":
            response = self._recover_unknown_send(
                RecoverUnknownSendActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "recover_send", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=action.version,
                    expected_attempt_version=attempt_version,
                )
            )
        elif action.effect_type == "DELETE":
            response = self._recover_unknown_delete(
                RecoverUnknownDeleteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "recover_delete", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=action.version,
                    expected_attempt_version=attempt_version,
                )
            )
        else:
            response = self._recover_unknown_update(
                RecoverUnknownUpdateActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "recover_update", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=action.version,
                    expected_attempt_version=attempt_version,
                )
            )
        if response.applied and response.action_status == ActionStatus.EXECUTED.value:
            response = self._verify_write(
                VerifyWriteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "verify_recovered", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=response.action_version,
                    verification_id=self._id_factory(),
                )
            )
        if response.applied and response.action_status == ActionStatus.VERIFIED.value:
            self._complete_write_run_if_verified(action.plan_id, cast(str, state["run_id"]))
        outcome = (
            "RECOVERY_REQUIRED"
            if response.result_code == ResultCode.RECOVERY_REQUIRED.value
            else "RECOVERED"
        )
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "execution_summary": {"result": outcome, "action_id": action.id},
            "verification_summary": {"action_statuses": [response.action_status]},
        }

    def _recover_executed_actions(self, state: GraphState, run_id: str) -> GraphState:
        plans = self._plans_for_run(run_id)
        if not plans:
            return {**state, "__target__": "end", "workflow_phase": WorkflowPhase.RECOVERY.value}
        latest_plan = sorted(plans, key=lambda item: (item.revision_no, item.created_at_ms))[-1]
        statuses: list[str] = []
        for action in self._list_actions(latest_plan.id):
            if action.status != ActionStatus.EXECUTED.value:
                statuses.append(action.status)
                continue
            attempt_id = self._latest_attempt_id(action.id)
            verified = self._verify_write(
                VerifyWriteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "verify_after_restart", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=action.version,
                    verification_id=self._id_factory(),
                )
            )
            statuses.append(verified.action_status)
        self._complete_write_run_if_verified(latest_plan.id, run_id)
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "execution_summary": {"result": "RESTART_RECONCILED", "plan_id": latest_plan.id},
            "verification_summary": {"action_statuses": statuses},
        }

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
        if self._graph_profile is GraphProfile.SINGLE_BASELINE and target in {
            SupervisorTarget.SOURCE_PLANNING.value,
            SupervisorTarget.API_ACQUISITION.value,
            SupervisorTarget.CONTEXT_RETRIEVAL.value,
            SupervisorTarget.WORK_ANALYSIS.value,
            SupervisorTarget.SOLUTION_PLANNING.value,
            SupervisorTarget.PLAN_REVIEW_INSPECT.value,
            SupervisorTarget.PLAN_REVIEW_RECHECK.value,
            SupervisorTarget.PLANNING_REVISE_ANSWER.value,
            SupervisorTarget.PLANNING_REVISE_PLAN.value,
        }:
            return "single_workflow"
        if self._graph_profile is GraphProfile.THREE_STAGE and target in {
            SupervisorTarget.SOURCE_PLANNING.value,
            SupervisorTarget.API_ACQUISITION.value,
        }:
            return "stage_one"
        if self._graph_profile is GraphProfile.THREE_STAGE and target in {
            SupervisorTarget.CONTEXT_RETRIEVAL.value,
            SupervisorTarget.WORK_ANALYSIS.value,
            SupervisorTarget.SOLUTION_PLANNING.value,
            SupervisorTarget.PLANNING_REVISE_ANSWER.value,
            SupervisorTarget.PLANNING_REVISE_PLAN.value,
        }:
            return "stage_two"
        if self._graph_profile is GraphProfile.THREE_STAGE and target in {
            SupervisorTarget.PLAN_REVIEW_INSPECT.value,
            SupervisorTarget.PLAN_REVIEW_RECHECK.value,
        }:
            return "stage_three"
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE and target in {
            SupervisorTarget.SOURCE_PLANNING.value,
            SupervisorTarget.API_ACQUISITION.value,
        }:
            return "acquisition"
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            six_logical_mapping = {
                SupervisorTarget.CONTEXT_RETRIEVAL.value: "context_retriever",
                SupervisorTarget.WORK_ANALYSIS.value: "work_analysis",
                SupervisorTarget.SOLUTION_PLANNING.value: "planning",
                SupervisorTarget.PLAN_REVIEW_INSPECT.value: "review",
                SupervisorTarget.PLAN_REVIEW_RECHECK.value: "review",
                SupervisorTarget.PLANNING_REVISE_ANSWER.value: "planning",
                SupervisorTarget.PLANNING_REVISE_PLAN.value: "planning",
            }
            resolved = six_logical_mapping.get(target)
            if resolved is not None:
                return resolved
        mapping = {
            SupervisorTarget.SOURCE_PLANNING.value: "source_planning",
            SupervisorTarget.API_ACQUISITION.value: "api_acquisition",
            SupervisorTarget.CONTEXT_RETRIEVAL.value: "context_retrieval",
            SupervisorTarget.WORK_ANALYSIS.value: "work_analysis",
            SupervisorTarget.SOLUTION_PLANNING.value: "solution_planning",
            SupervisorTarget.PLAN_REVIEW_INSPECT.value: "plan_review",
            SupervisorTarget.PLAN_REVIEW_RECHECK.value: "plan_review",
            SupervisorTarget.PLANNING_REVISE_ANSWER.value: "solution_planning",
            SupervisorTarget.PLANNING_REVISE_PLAN.value: "solution_planning",
            SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
            SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
            SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
            SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
            SupervisorTarget.REAUTH.value: "end",
            SupervisorTarget.RECOVERY.value: "recovery",
            SupervisorTarget.FINALIZE.value: "finalize",
        }
        return mapping.get(target, "end")

    def _target_to_node(self, target: str) -> str:
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            single_mapping = {
                SupervisorTarget.SOURCE_PLANNING.value: "single_workflow",
                SupervisorTarget.API_ACQUISITION.value: "single_workflow",
                SupervisorTarget.CONTEXT_RETRIEVAL.value: "single_workflow",
                SupervisorTarget.WORK_ANALYSIS.value: "single_workflow",
                SupervisorTarget.SOLUTION_PLANNING.value: "single_workflow",
                SupervisorTarget.PLAN_REVIEW_INSPECT.value: "single_workflow",
                SupervisorTarget.PLAN_REVIEW_RECHECK.value: "single_workflow",
                SupervisorTarget.PLANNING_REVISE_ANSWER.value: "single_workflow",
                SupervisorTarget.PLANNING_REVISE_PLAN.value: "single_workflow",
                SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
                SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
                SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
                SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
                SupervisorTarget.REAUTH.value: "end",
                SupervisorTarget.RECOVERY.value: "recovery",
                SupervisorTarget.FINALIZE.value: "finalize",
            }
            return single_mapping.get(target, "end")
        if self._graph_profile is GraphProfile.THREE_STAGE:
            three_stage_mapping = {
                SupervisorTarget.SOURCE_PLANNING.value: "stage_one",
                SupervisorTarget.API_ACQUISITION.value: "stage_two",
                SupervisorTarget.CONTEXT_RETRIEVAL.value: "stage_two",
                SupervisorTarget.WORK_ANALYSIS.value: "stage_two",
                SupervisorTarget.SOLUTION_PLANNING.value: "stage_two",
                SupervisorTarget.PLAN_REVIEW_INSPECT.value: "stage_three",
                SupervisorTarget.PLAN_REVIEW_RECHECK.value: "stage_three",
                SupervisorTarget.PLANNING_REVISE_ANSWER.value: "stage_two",
                SupervisorTarget.PLANNING_REVISE_PLAN.value: "stage_two",
                SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
                SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
                SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
                SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
                SupervisorTarget.REAUTH.value: "end",
                SupervisorTarget.RECOVERY.value: "recovery",
                SupervisorTarget.FINALIZE.value: "finalize",
            }
            return three_stage_mapping.get(target, "end")
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            six_stage_mapping = {
                SupervisorTarget.SOURCE_PLANNING.value: "acquisition",
                SupervisorTarget.API_ACQUISITION.value: "acquisition",
                SupervisorTarget.CONTEXT_RETRIEVAL.value: "context_retriever",
                SupervisorTarget.WORK_ANALYSIS.value: "work_analysis",
                SupervisorTarget.SOLUTION_PLANNING.value: "planning",
                SupervisorTarget.PLAN_REVIEW_INSPECT.value: "review",
                SupervisorTarget.PLAN_REVIEW_RECHECK.value: "review",
                SupervisorTarget.PLANNING_REVISE_ANSWER.value: "planning",
                SupervisorTarget.PLANNING_REVISE_PLAN.value: "planning",
                SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
                SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
                SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
                SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
                SupervisorTarget.REAUTH.value: "end",
                SupervisorTarget.RECOVERY.value: "recovery",
                SupervisorTarget.FINALIZE.value: "finalize",
            }
            return six_stage_mapping.get(target, "end")
        mapping = {
            SupervisorTarget.SOURCE_PLANNING.value: "source_planning",
            SupervisorTarget.API_ACQUISITION.value: "api_acquisition",
            SupervisorTarget.CONTEXT_RETRIEVAL.value: "context_retrieval",
            SupervisorTarget.WORK_ANALYSIS.value: "work_analysis",
            SupervisorTarget.SOLUTION_PLANNING.value: "solution_planning",
            SupervisorTarget.PLAN_REVIEW_INSPECT.value: "plan_review",
            SupervisorTarget.PLAN_REVIEW_RECHECK.value: "plan_review",
            SupervisorTarget.PLANNING_REVISE_ANSWER.value: "solution_planning",
            SupervisorTarget.PLANNING_REVISE_PLAN.value: "solution_planning",
            SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
            SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
            SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
            SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
            SupervisorTarget.REAUTH.value: "end",
            SupervisorTarget.RECOVERY.value: "recovery",
            SupervisorTarget.FINALIZE.value: "finalize",
        }
        return mapping.get(target, "end")

    def _confirmation_resume_target(self, interrupt_payload: dict[str, object]) -> str:
        origin_target = cast(str | None, interrupt_payload.get("origin_target"))
        if self._graph_profile is GraphProfile.THREE_STAGE and origin_target is not None:
            if origin_target.startswith(("request_understanding.", "acquisition.")):
                return "stage_one"
            if origin_target.startswith(("context.", "analysis.", "planning.")):
                return "stage_two"
            if origin_target.startswith("review."):
                return "stage_three"
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            return "single_workflow"
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            return "acquisition"
        return "source_planning"

    def _request_from_state(self, state: GraphState) -> WorkflowStartRequest:
        request = state.get("__request__")
        if not isinstance(request, WorkflowStartRequest):
            raise TypeError("workflow state is missing WorkflowStartRequest")
        prompt_context = cast(dict[str, object], state.get("prompt_context", {}))
        confirmation_response = prompt_context.get("confirmation_response")
        if not isinstance(confirmation_response, dict):
            return request
        request_text = (
            request.request_text
            + "\n\n[clarification]\n"
            + dumps(
                {
                    "selected_option_ids": cast(
                        list[str], confirmation_response.get("selected_option_ids", [])
                    ),
                    "free_text": cast(str | None, confirmation_response.get("free_text")),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return WorkflowStartRequest(
            run_id=request.run_id,
            conversation_id=request.conversation_id,
            workflow_key=request.workflow_key,
            entry_mode=request.entry_mode,
            requested_mode=request.requested_mode,
            request_text=request_text,
            selected_resource_ids=request.selected_resource_ids,
            correlation=request.correlation,
            selected_resources=request.selected_resources,
        )

    def _config_for_thread(self, workflow_key: str) -> dict[str, object]:
        return {"configurable": {"thread_id": workflow_key}}

    def _workflow_result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        return self._result_from_state(state=state, workflow_key=workflow_key, run_id=run_id)

    def _result_from_thread(self, *, workflow_key: str, run_id: str) -> WorkflowInvocationResult:
        snapshot = self._graph.get_state(self._config_for_thread(workflow_key))
        return self._result_from_state(
            state=cast(GraphState, snapshot.values),
            workflow_key=workflow_key,
            run_id=run_id,
        )

    def _result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        run_status = self._current_run_status(run_id)
        if run_status in {
            RunStatus.COMPLETED.value,
            RunStatus.BLOCKED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }:
            outcome = WorkflowOutcome.COMPLETED
        elif run_status == RunStatus.RECOVERY_REQUIRED.value:
            outcome = WorkflowOutcome.RECOVERY_REQUIRED
        elif run_status == RunStatus.REAUTH_REQUIRED.value:
            outcome = WorkflowOutcome.ACCEPTED
        else:
            outcome = WorkflowOutcome.ACCEPTED
        if run_status in {
            RunStatus.COMPLETED.value,
            RunStatus.BLOCKED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }:
            with self._cancel_signal_lock:
                self._cancel_signals.discard(run_id)
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=outcome,
            payload={
                "phase": state.get("workflow_phase"),
                "finalize_intent": state.get("finalize_intent"),
                "user_interrupt": state.get("user_interrupt"),
                "execution_summary": state.get("execution_summary"),
                "verification_summary": state.get("verification_summary"),
                "run_status": run_status,
                "graph_profile": self._graph_profile.value,
            },
        )

    def _is_profile_compatible(self, state: GraphState) -> bool:
        prompt_context = state.get("prompt_context")
        if not isinstance(prompt_context, dict):
            return True
        persisted_profile = prompt_context.get("graph_profile")
        if not isinstance(persisted_profile, str):
            return True
        return persisted_profile == self._graph_profile.value

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        run_id = state["run_id"]
        run_version = self._current_run_version(run_id)
        context_result = _require_state_value(state["context_result"], "context_result")
        evidence_drafts = {item["evidence_id"]: item for item in context_result["evidence_drafts"]}
        mapped_evidence = []
        for evidence_id in plan_draft["evidence_refs"]:
            item = evidence_drafts[evidence_id]
            mapped_evidence.append(
                WriteEvidenceDraft(
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
            WriteActionDraft(
                action_id=action["action_id"],
                position=action["position"],
                tool_name=action["tool_name"],
                arguments=action["arguments"],
                expected=action["expected"],
                evidence_ids=tuple(action["evidence_refs"]),
                depends_on_action_ids=tuple(action.get("depends_on_action_ids", [])),
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
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        save_response = self._save_write_plan(
            SaveWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_write_plan", "plan_id": plan_id}),
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
        context_result = _require_state_value(state["context_result"], "context_result")
        evidence_drafts = {item["evidence_id"]: item for item in context_result["evidence_drafts"]}
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

    def _planning_mode_from_request_intent(self, request_intent: RequestIntentV1) -> str:
        """Deterministic answer_only/draft_plan selection (GAP-F1).

        Reads the ``response_disposition`` typed field produced by
        ``request_understanding.classify`` instead of matching keyword
        substrings against ``request_text`` -- the previous approach silently
        misrouted any request whose natural-language phrasing (in particular
        Korean) did not contain one of a fixed English token list. The field
        is optional on ``RequestIntentV1`` (see its definition) because only
        SIX_ROLE_BASELINE's standalone Planning subgraph needs this upfront
        choice between the two mutually exclusive ``planning.answer_only`` /
        ``planning.draft_plan`` prompt slots; SINGLE_BASELINE and THREE_STAGE
        decide ANSWER_ONLY vs PLAN_READY inside one fused planning call. When
        the field is absent -- an older classify prompt version that predates
        this field, or a profile that never sets it -- this falls back to
        ``answer_only`` rather than guessing an action the user did not ask
        for (docs/01-b-policy-definition-v2.8.md POL-EVD-003 / "Answer-only에서
        불필요한 Action을 생성하지 않는다").
        """
        return (
            "draft_plan"
            if request_intent.get("response_disposition") == "ACTION_REQUIRED"
            else "answer_only"
        )
