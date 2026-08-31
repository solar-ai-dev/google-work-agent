"""Transport-independent typed subgraph-to-Main control signal contract."""

from typing import Literal, Required, TypedDict

from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    SemanticAgentOwnerIdV1,
)


class ConfirmationRequiredV1(TypedDict):
    kind: Required[Literal["CONFIRMATION_REQUIRED"]]
    interrupt_id: str
    semantic_owner_id: SemanticAgentOwnerIdV1
    resume_target: AgentNodeResumeTargetV2
    question: str
    options: list[str]


class RouteReconsiderationRequiredV1(TypedDict):
    kind: Required[Literal["ROUTE_RECONSIDERATION_REQUIRED"]]
    reason_codes: list[str]


class RetrievalNeedV1(TypedDict):
    required_information: str
    reason_codes: list[str]


class RetrievalRequiredV1(TypedDict):
    kind: Required[Literal["RETRIEVAL_REQUIRED"]]
    reason_codes: list[str]
    needs: list[RetrievalNeedV1]


class PlanningRevisionIssueV1(TypedDict):
    dimension: Literal["GOAL_EVIDENCE", "ACTION_SCOPE_ROUTE", "CONSTRAINTS_POLICY"]
    code: str
    description: str
    action_id: str | None
    route_id: str | None


class PlanningRevisionRequiredV1(TypedDict):
    kind: Required[Literal["PLANNING_REVISION_REQUIRED"]]
    destination: Required[Literal["PLANNING"]]
    disposition: Required[Literal["REVISE"]]
    issues: list[PlanningRevisionIssueV1]


class BlockedSignalV1(TypedDict):
    kind: Required[Literal["BLOCKED"]]
    reason_codes: list[str]


WorkflowSignalV1 = (
    ConfirmationRequiredV1
    | RouteReconsiderationRequiredV1
    | RetrievalRequiredV1
    | PlanningRevisionRequiredV1
    | BlockedSignalV1
)


class SubgraphReturnV2[TypedResultT](TypedDict):
    disposition: str
    typed_result: TypedResultT | None
    workflow_signal: WorkflowSignalV1 | None
