"""Application contracts for persisting and publishing write plans."""

from __future__ import annotations

from dataclasses import dataclass, field

from google_work_agent.domain.evidence.model import EvidenceOriginType


@dataclass(frozen=True, slots=True)
class WriteEvidenceDraft:
    evidence_id: str
    origin_type: EvidenceOriginType
    kind: str
    excerpt: str
    locator_json: str | None = None
    resource_ref_id: str | None = None
    message_id: str | None = None


@dataclass(frozen=True, slots=True)
class WriteActionDraft:
    action_id: str
    connector_id: str
    position: int
    tool_name: str
    arguments: dict[str, object]
    expected: dict[str, object]
    evidence_ids: tuple[str, ...]
    depends_on_action_ids: tuple[str, ...] = ()
    target_resource_ref_id: str | None = None
    risk: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SaveWritePlanCommand:
    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    revision_no: int
    summary_text: str
    expected_run_version: int
    actions: tuple[WriteActionDraft, ...]
    evidence: tuple[WriteEvidenceDraft, ...]


@dataclass(frozen=True, slots=True)
class PublishWritePlanCommand:
    command_id: str
    request_hash: str
    plan_id: str
    run_id: str
    expected_run_version: int


@dataclass(frozen=True, slots=True)
class SaveWritePlanResponse:
    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    action_ids: tuple[str, ...]
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class PublishWritePlanResponse:
    applied: bool
    result_code: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    conflict_detail: str | None = None
