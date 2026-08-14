"""Application contracts for the legacy persisted READ action lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports import EvidenceOriginType, ResourceSource, StoredResourceType


@dataclass(frozen=True, slots=True)
class ReadEvidenceDraft:
    """Input evidence row for a read-only plan draft."""

    evidence_id: str
    origin_type: EvidenceOriginType
    kind: str
    excerpt: str
    locator_json: str | None = None
    resource_ref_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReadActionDraft:
    """Input action row for a read-only plan draft."""

    action_id: str
    position: int
    tool_name: str
    arguments: dict[str, object]
    expected: dict[str, object]
    evidence_ids: tuple[str, ...]
    depends_on_action_ids: tuple[str, ...] = ()
    target_resource_ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class SaveReadOnlyPlanCommand:
    """Save one explicit read-only plan draft."""

    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    revision_no: int
    summary_text: str
    expected_run_version: int
    actions: tuple[ReadActionDraft, ...]
    evidence: tuple[ReadEvidenceDraft, ...]


@dataclass(frozen=True, slots=True)
class PublishReadOnlyPlanCommand:
    """Publish one read-only plan."""

    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    expected_run_version: int


@dataclass(frozen=True, slots=True)
class ClaimReadActionCommand:
    """Claim one read action."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class CompletedResourceRef:
    """Projected resource reference from a read result."""

    id: str
    source: ResourceSource
    resource_type: StoredResourceType
    resource_id: str
    parent_resource_id: str | None
    canonical_url: str | None
    title: str | None
    event_time_ms: int | None
    version_token: str | None
    metadata_json: str


@dataclass(frozen=True, slots=True)
class CompletedEvidence:
    """Projected evidence row from a read result."""

    id: str
    origin_type: EvidenceOriginType
    kind: str
    excerpt: str
    locator_json: str | None
    resource_ref_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class CompleteReadActionCommand:
    """Persist a successful read action result."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    output_json: str
    resource_refs: tuple[CompletedResourceRef, ...]
    evidence: tuple[CompletedEvidence, ...]


@dataclass(frozen=True, slots=True)
class FinalizeReadActionCommand:
    """Finalize an executed read action."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class FailReadActionCommand:
    """Persist a failed read action result."""

    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    safe_error_code: str
    retryable: bool
    safe_error_detail: str


@dataclass(frozen=True, slots=True)
class SaveReadOnlyPlanResponse:
    """Result of saving a read-only plan."""

    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    action_ids: tuple[str, ...]
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class PublishReadOnlyPlanResponse:
    """Result of publishing a read-only plan."""

    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReadActionCommandResponse:
    """Result of a read action command."""

    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    plan_completed: bool = False
    run_completed: bool = False
    partial: bool = False
    safe_error_code: str | None = None
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutedReadAction:
    """Typed output from one dispatched read action."""

    output_json: str
    resource_refs: tuple[CompletedResourceRef, ...]
    evidence: tuple[CompletedEvidence, ...]


type ReadOnlyResponse = (
    SaveReadOnlyPlanResponse | PublishReadOnlyPlanResponse | ReadActionCommandResponse
)
