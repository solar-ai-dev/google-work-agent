"""Retrieval planning, local evidence, and parent-result contracts."""

from enum import StrEnum
from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1


class ContextResult(StrEnum):
    """Retrieval sufficiency routing result."""

    SUFFICIENT = "SUFFICIENT"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


ContextStatusValue = Literal[
    "SUFFICIENT",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "PARTIAL",
    "BLOCKED",
]


SufficiencyIssueTypeValue = Literal["MISSING", "CONFLICT"]


SufficiencyResolutionSourceValue = Literal["USER", "GOOGLE", "POLICY", "ROUTE"]


MissingInformationRequiredForValue = Literal[
    "RETRIEVAL", "ANALYSIS", "PLANNING", "USER_CONFIRMATION"
]


class AcquisitionResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: Literal[
        "COMPLETE", "PARTIAL", "AUTH_REQUIRED", "RATE_LIMITED", "BUDGET_EXHAUSTED", "FAILED"
    ]
    resource_handles: list[str]
    source_summaries: list[dict[str, object]]
    missing_slots: list[str]
    remaining_budget: dict[str, int]


class EvidenceDraftV1(TypedDict):
    schema_version: Required[Literal[1]]
    evidence_id: str
    resource_handle: str
    segment_id: str
    kind: str
    excerpt: str
    locator: dict[str, object] | None
    reason_codes: list[str]


class ContextBundleV1(TypedDict):
    schema_version: Required[Literal[1]]
    resource_refs: list[dict[str, object]]
    segment_refs: list[dict[str, object]]
    evidence_refs: list[str]
    normalized_context: list[dict[str, object]]
    missing_information: list[str]
    ambiguity: dict[str, object] | None


class EvidenceRoleDraftV2(TypedDict):
    """docs/05-context-retrieval.md SS5.6 / evidence-selection-result-v2.schema.json.

    Thin reference + classification only -- the LLM never re-supplies
    resource_handle/excerpt/locator; those are joined back from the
    normalized SourceSegment by segment_id (see
    retrieval/select_evidence.py ``materialize_evidence_drafts``)."""

    segment_id: str
    role: Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"]
    relevance_reason: str


class EvidenceSelectionResultV2(TypedDict):
    """docs/05-context-retrieval.md SS5.6 -- retrieval.select_evidence output,
    Retrieval Local State only (RetrievalStateV1.evidence_selection)."""

    schema_version: Required[Literal[2]]
    evidence_drafts: list[EvidenceRoleDraftV2]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]


class SufficiencyIssueV2(TypedDict):
    """docs/05-context-retrieval.md SS19.1 SufficiencyIssue.

    Retrieval's own internal judgment input to the SS19.2 deterministic
    Guard -- not the Parent-facing handoff shape (see MissingInformationV1
    below). The PHASE 7.5 sufficiency-result-v2.schema.json Candidate
    Artifact originally reused MissingInformationV1's
    {code,description,required_for} shape here by mistake (an
    ARTIFACT_CONTRACT_CONFLICT against this exact Canonical section);
    the Candidate schema was corrected to match Canonical instead of
    weakening Canonical to match the mistaken Candidate."""

    slot: str
    issue_type: SufficiencyIssueTypeValue
    required: bool
    resolution_source: SufficiencyResolutionSourceValue
    safety_critical: bool
    reason_codes: list[str]


class SufficiencyResultV2(TypedDict):
    """docs/05-context-retrieval.md SS5.7 -- retrieval.assess_sufficiency
    output, Retrieval Local State only (RetrievalStateV1.sufficiency)."""

    schema_version: Required[Literal[2]]
    status: ContextStatusValue
    issues: list[SufficiencyIssueV2]


class MissingInformationV1(TypedDict):
    """docs/06-agent-workflow.md SS3.3 -- RetrievalResultV1.missing_information
    item. Parent-facing handoff shape, deliberately not the same type as
    SufficiencyIssueV2: a deterministic projection
    (retrieval_sufficiency.missing_information_projection) converts one into
    the other. Full RetrievalResultV1 finalization (wiring this field onto
    the Parent result, renaming coverage/source_statuses/retrieval_rounds)
    is Q2-E scope; this type only prepares the boundary."""

    code: str
    description: str
    required_for: MissingInformationRequiredForValue


class RetrievalSourceStatusV1(TypedDict):
    route_id: str
    resource_type: str
    status: Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"]
    evidence_refs: list[str]
    failure_kind: (
        Literal[
            "AUTH", "SCOPE", "RATE_LIMIT", "TIMEOUT", "PROVIDER", "NOT_FOUND", "BUDGET", "OTHER"
        ]
        | None
    )


class RetrievalResultV1(TypedDict):
    """Canonical Retrieval parent handoff (06-agent-workflow.md SS3.3)."""

    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    coverage: Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]
    context_bundle_ref: str | None
    evidence_refs: list[str]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]
    source_resource_refs: list[str]
    source_statuses: list[RetrievalSourceStatusV1]
    availability_results: list[dict[str, object]]
    missing_information: list[MissingInformationV1]
    retrieval_rounds: int
