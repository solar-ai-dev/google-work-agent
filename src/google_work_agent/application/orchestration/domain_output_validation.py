"""Domain Validation input boundary for canonical post-Retrieval artifacts.

This module changes only the Application/Workflow input authority used by
Domain Validation. It does not change Domain run/action transitions, approval,
claim, cancellation, recovery commands, or persistence invariants.

The production graph is not switched to this service until the post-Retrieval
V2 owner chain can be cut over atomically. Until then this module is an
import-ready boundary with contract tests, not a second production authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, Protocol, TypedDict, cast

from google_work_agent.application.orchestration.contracts import (
    DomainValidationOutputV1,
    DomainValidationResult,
    PolicyConfirmationReceiptV1,
    validate_domain_validation_output_v1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    StateArtifactMetaV1,
    StateArtifactRefV1,
)
from google_work_agent.application.orchestration.inspect_plan_output import (
    validate_plan_review_candidate_v2,
)
from google_work_agent.application.orchestration.planning_plan_assembler import (
    ActionPlanDraftV2,
    PlannedActionV2,
)
from google_work_agent.application.orchestration.planning_tool_schemas import (
    planning_tool_argument_schema,
)
from google_work_agent.application.orchestration.state_artifacts import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.tool_registry.signed_tool_registry import (
    P0_GOOGLE_WORKSPACE_CONNECTOR_ID,
    SignedToolRegistry,
)
from google_work_agent.application.use_cases.action.validate_action_arguments import (
    ValidateActionArgumentsHandler,
    ValidateActionArgumentsQueryV1,
)
from google_work_agent.domain.action.model import EffectType

_WRITE_EFFECTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})
_TARGET_BINDINGS: dict[str, tuple[str, str, str | None]] = {
    "gmail_update_draft": ("gmail_draft", "draft_id", None),
    "tasks_update_task": ("task", "task_id", "task_list_id"),
    "tasks_delete_task": ("task", "task_id", "task_list_id"),
    "calendar_update_event": ("calendar_event", "event_id", "calendar_id"),
    "calendar_delete_event": ("calendar_event", "event_id", "calendar_id"),
}


class CurrentRunResourceIdentityV1(TypedDict):
    resource_handle: str
    resource_type: str
    resource_id: str
    parent_id: str | None


class RunScopedResourceIdentityReader(Protocol):
    """Agent-3 consumer protocol for current-run normalized resource identity.

    This name/shape is not a provider-side Agent 4 contract. Integration may
    adapt Agent 4's final ephemeral read-only boundary to this consumer shape.
    Raw provider payloads must never cross this boundary.
    """

    def resolve_resource_identity(
        self,
        *,
        run_id: str,
        resource_handle: str,
    ) -> CurrentRunResourceIdentityV1 | None: ...


class CanonicalDomainValidationError(ValueError):
    pass


class PolicyOverrideProvenanceDependency(RuntimeError):
    """Override safety cannot be proven until the Policy Receipt wave lands."""


class CanonicalDomainValidationService:
    """Validate V2 artifacts without reintroducing legacy plan authority."""

    def __init__(self, *, tool_registry: SignedToolRegistry) -> None:
        self._tool_registry = tool_registry

    def __call__(
        self,
        *,
        run_id: str,
        planning_result: ActionPlanDraftV2,
        plan_review: PlanReviewResultV2,
        work_analysis_result: WorkAnalysisResultV2 | None,
        evidence_drafts: Sequence[EvidenceDraftV1],
        policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
        resource_identity_reader: RunScopedResourceIdentityReader,
    ) -> DomainValidationOutputV1:
        return build_domain_validation_output_from_v2(
            run_id=run_id,
            planning_result=planning_result,
            plan_review=plan_review,
            work_analysis_result=work_analysis_result,
            evidence_drafts=evidence_drafts,
            policy_confirmation_receipts=policy_confirmation_receipts,
            resource_identity_reader=resource_identity_reader,
            tool_registry=self._tool_registry,
        )


def build_domain_validation_output_from_v2(
    *,
    run_id: str,
    planning_result: ActionPlanDraftV2,
    plan_review: PlanReviewResultV2,
    work_analysis_result: WorkAnalysisResultV2 | None,
    evidence_drafts: Sequence[EvidenceDraftV1],
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
    resource_identity_reader: RunScopedResourceIdentityReader,
    tool_registry: SignedToolRegistry,
) -> DomainValidationOutputV1:
    try:
        if not isinstance(run_id, str) or not run_id:
            raise CanonicalDomainValidationError("run_id is required")
        plan = validate_action_plan_draft_v2_for_domain(
            planning_result,
            run_id=run_id,
            evidence_drafts=evidence_drafts,
            resource_identity_reader=resource_identity_reader,
            tool_registry=tool_registry,
        )
        _validate_pass_review_for_plan(plan_review, planning_result=plan)
        if work_analysis_result is not None:
            _validate_work_analysis_receipt_references(
                work_analysis_result,
                policy_confirmation_receipts=policy_confirmation_receipts,
            )
            _fail_closed_on_unproven_policy_override(
                work_analysis_result=work_analysis_result,
                planning_result=plan,
            )
    except CanonicalDomainValidationError as error:
        reason_code = (
            "PLAN_REVIEW_INVALID"
            if str(error).startswith("plan review")
            else "WORK_ANALYSIS_INVALID"
            if str(error).startswith("work analysis")
            else "PLAN_DRAFT_INVALID"
        )
        return validate_domain_validation_output_v1(
            {
                "schema_version": 1,
                "result": DomainValidationResult.BLOCK.value,
                "reason_codes": [reason_code],
                "blocked_action_ids": [],
            }
        )

    return validate_domain_validation_output_v1(
        {
            "schema_version": 1,
            "result": DomainValidationResult.REQUIRE_APPROVAL.value,
            "reason_codes": ["WRITE_EFFECT_PRESENT"],
            "blocked_action_ids": [],
        }
    )


def validate_action_plan_draft_v2_for_domain(
    value: object,
    *,
    run_id: str,
    evidence_drafts: Sequence[EvidenceDraftV1],
    resource_identity_reader: RunScopedResourceIdentityReader,
    tool_registry: SignedToolRegistry,
) -> ActionPlanDraftV2:
    root = _mapping(value, "$")
    if set(root) != {"schema_version", "meta", "actions"}:
        raise CanonicalDomainValidationError("ActionPlanDraftV2 keys are invalid")
    if root["schema_version"] != 2:
        raise CanonicalDomainValidationError("ActionPlanDraftV2.schema_version must be 2")
    meta = _validate_meta(root["meta"], path="ActionPlanDraftV2.meta")
    raw_actions = root["actions"]
    if not isinstance(raw_actions, list) or not raw_actions:
        raise CanonicalDomainValidationError("ActionPlanDraftV2 requires at least one action")

    evidence_by_id = _evidence_index(evidence_drafts)
    actions = [
        _validate_action(
            raw,
            path=f"$.actions[{index}]",
            run_id=run_id,
            evidence_by_id=evidence_by_id,
            resource_identity_reader=resource_identity_reader,
            tool_registry=tool_registry,
        )
        for index, raw in enumerate(raw_actions)
    ]
    _validate_action_collection(actions)
    return {"schema_version": 2, "meta": meta, "actions": actions}


def _validate_pass_review_for_plan(
    value: object,
    *,
    planning_result: ActionPlanDraftV2,
) -> None:
    root = _mapping(value, "plan review")
    if set(root) != {"schema_version", "meta", "status", "summary"}:
        raise CanonicalDomainValidationError("plan review PASS keys are invalid")
    try:
        validate_plan_review_candidate_v2(
            {
                "schema_version": root["schema_version"],
                "status": root["status"],
                "summary": root["summary"],
            }
        )
    except ValueError as error:
        raise CanonicalDomainValidationError(f"plan review invalid: {error}") from error
    if root["status"] != "PASS":
        raise CanonicalDomainValidationError("plan review must be PASS before Domain Validation")

    review_meta = _validate_meta(root["meta"], path="plan review.meta")
    plan_meta = _validate_meta(planning_result["meta"], path="planning result.meta")
    required_ref = {"artifact_id": plan_meta["artifact_id"], "revision": plan_meta["revision"]}
    if required_ref not in review_meta["based_on"]:
        raise CanonicalDomainValidationError(
            "plan review is stale: meta.based_on does not reference current planning result"
        )


def _validate_work_analysis_receipt_references(
    value: object,
    *,
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
) -> None:
    root = _mapping(value, "work analysis")
    expected = {
        "schema_version",
        "meta",
        "work_facts",
        "relations",
        "ambiguities",
        "risks",
        "evidence_refs",
        "policy_confirmation_receipt_refs",
        "action_necessity",
    }
    if set(root) != expected or root["schema_version"] != 2:
        raise CanonicalDomainValidationError("work analysis artifact is invalid")
    _validate_meta(root["meta"], path="work analysis.meta")
    if root["action_necessity"] not in {"REQUIRED", "NOT_REQUIRED"}:
        raise CanonicalDomainValidationError("work analysis action_necessity is invalid")

    raw_refs = root["policy_confirmation_receipt_refs"]
    if not isinstance(raw_refs, list):
        raise CanonicalDomainValidationError(
            "work analysis policy_confirmation_receipt_refs must be an array"
        )
    refs = [
        _artifact_ref(raw, path=f"work analysis.policy_confirmation_receipt_refs[{index}]")
        for index, raw in enumerate(raw_refs)
    ]
    receipt_by_ref: dict[tuple[str, int], PolicyConfirmationReceiptV1] = {}
    for receipt in policy_confirmation_receipts:
        if not isinstance(receipt, Mapping) or receipt.get("schema_version") != 1:
            raise CanonicalDomainValidationError("work analysis referenced receipt set is invalid")
        meta = _validate_meta(receipt.get("meta"), path="policy confirmation receipt.meta")
        key = (meta["artifact_id"], meta["revision"])
        if key in receipt_by_ref:
            raise CanonicalDomainValidationError(
                "work analysis referenced receipt set contains duplicate artifact revisions"
            )
        receipt_by_ref[key] = cast(PolicyConfirmationReceiptV1, receipt)

    for ref in refs:
        receipt = receipt_by_ref.get((ref["artifact_id"], ref["revision"]))
        if receipt is None:
            raise CanonicalDomainValidationError(
                "work analysis references a missing/stale policy confirmation receipt"
            )
        if receipt.get("decision") != "APPROVED":
            raise CanonicalDomainValidationError(
                "work analysis references a non-approved policy confirmation receipt"
            )


def _fail_closed_on_unproven_policy_override(
    *,
    work_analysis_result: WorkAnalysisResultV2,
    planning_result: ActionPlanDraftV2,
) -> None:
    """Do not convert a NOT_REQUIRED analysis into executable work.

    Canonical override success requires more than an APPROVED receipt reference:
    the later Policy Receipt Provenance wave must prove the exact override
    context and Approval Snapshot binding. This boundary intentionally does not
    invent a DomainValidationOutput reason code for that missing provenance.
    """

    if work_analysis_result["action_necessity"] == "NOT_REQUIRED" and planning_result["actions"]:
        raise PolicyOverrideProvenanceDependency(
            "POLICY_OVERRIDE_PROVENANCE_DEPENDENCY: "
            "NOT_REQUIRED Work Analysis cannot authorize non-empty Planning actions "
            "until exact duplicate/conflict override provenance is available"
        )


def _validate_action(
    value: object,
    *,
    path: str,
    run_id: str,
    evidence_by_id: Mapping[str, EvidenceDraftV1],
    resource_identity_reader: RunScopedResourceIdentityReader,
    tool_registry: SignedToolRegistry,
) -> PlannedActionV2:
    item = _mapping(value, path)
    required = {
        "action_id",
        "route_id",
        "tool_id",
        "effect",
        "arguments",
        "evidence_refs",
        "depends_on_action_ids",
    }
    if set(item) != required:
        raise CanonicalDomainValidationError(f"{path} keys are invalid")

    action_id = _text(item["action_id"], f"{path}.action_id")
    route_id = _text(item["route_id"], f"{path}.route_id")
    tool_id = _text(item["tool_id"], f"{path}.tool_id")
    effect = _text(item["effect"], f"{path}.effect")
    if effect not in _WRITE_EFFECTS:
        raise CanonicalDomainValidationError(f"{path}.effect is not a write effect")

    try:
        entry = tool_registry.get_required(P0_GOOGLE_WORKSPACE_CONNECTOR_ID, tool_id)
    except LookupError as exc:
        raise CanonicalDomainValidationError(f"{path}.tool_id is not registered") from exc
    if entry.effect_type.value != effect:
        raise CanonicalDomainValidationError(f"{path}.effect does not match Tool Registry")

    arguments = _mapping(item["arguments"], f"{path}.arguments")
    try:
        schema = planning_tool_argument_schema(tool_id)
    except ValueError as error:
        raise CanonicalDomainValidationError(str(error)) from error
    validation = ValidateActionArgumentsHandler()(ValidateActionArgumentsQueryV1(arguments, schema))
    if not validation.valid:
        raise CanonicalDomainValidationError(
            f"{path}.arguments violate selected Tool schema: "
            f"{'; '.join(validation.error_paths[:8])}"
        )

    evidence_refs = _string_list(item["evidence_refs"], f"{path}.evidence_refs")
    if not evidence_refs:
        raise CanonicalDomainValidationError(f"{path}.evidence_refs must not be empty")
    if len(evidence_refs) != len(set(evidence_refs)):
        raise CanonicalDomainValidationError(f"{path}.evidence_refs contains duplicates")
    missing_evidence = [ref for ref in evidence_refs if ref not in evidence_by_id]
    if missing_evidence:
        raise CanonicalDomainValidationError(
            f"{path}.evidence_refs are unavailable: {missing_evidence}"
        )

    dependencies = _string_list(item["depends_on_action_ids"], f"{path}.depends_on_action_ids")
    if len(dependencies) != len(set(dependencies)):
        raise CanonicalDomainValidationError(f"{path}.depends_on_action_ids contains duplicates")

    if effect in {EffectType.UPDATE.value, EffectType.DELETE.value}:
        _require_exact_target_evidence(
            tool_id=tool_id,
            arguments=arguments,
            evidence_refs=evidence_refs,
            evidence_by_id=evidence_by_id,
            run_id=run_id,
            resource_identity_reader=resource_identity_reader,
            path=path,
        )

    return {
        "action_id": action_id,
        "route_id": route_id,
        "tool_id": tool_id,
        "effect": cast(Literal["CREATE", "UPDATE", "SEND", "DELETE"], effect),
        "arguments": arguments,
        "evidence_refs": evidence_refs,
        "depends_on_action_ids": dependencies,
    }


def _require_exact_target_evidence(
    *,
    tool_id: str,
    arguments: Mapping[str, object],
    evidence_refs: Sequence[str],
    evidence_by_id: Mapping[str, EvidenceDraftV1],
    run_id: str,
    resource_identity_reader: RunScopedResourceIdentityReader,
    path: str,
) -> None:
    binding = _TARGET_BINDINGS.get(tool_id)
    if binding is None:
        raise CanonicalDomainValidationError(
            f"{path} has no deterministic target binding for existing-resource write"
        )
    resource_type, target_field, parent_field = binding
    target_id = _text(arguments.get(target_field), f"{path}.arguments.{target_field}")
    parent_id = (
        None
        if parent_field is None
        else _text(arguments.get(parent_field), f"{path}.arguments.{parent_field}")
    )

    target_handles: set[str] = set()
    for evidence_ref in evidence_refs:
        handle = evidence_by_id[evidence_ref]["resource_handle"]
        identity = resource_identity_reader.resolve_resource_identity(
            run_id=run_id,
            resource_handle=handle,
        )
        if identity is None:
            continue
        if identity["resource_handle"] != handle:
            raise CanonicalDomainValidationError(
                f"{path} resource identity resolver returned a mismatched handle"
            )
        if (
            identity["resource_type"] == resource_type
            and identity["resource_id"] == target_id
            and (parent_field is None or identity["parent_id"] == parent_id)
        ):
            target_handles.add(handle)

    if len(target_handles) != 1:
        raise CanonicalDomainValidationError(
            f"{path} target must resolve through evidence to exactly one current-run resource"
        )


def _validate_action_collection(actions: Sequence[PlannedActionV2]) -> None:
    action_ids = [action["action_id"] for action in actions]
    route_ids = [action["route_id"] for action in actions]
    if len(action_ids) != len(set(action_ids)):
        raise CanonicalDomainValidationError("ActionPlanDraftV2 contains duplicate action_id")
    if len(route_ids) != len(set(route_ids)):
        raise CanonicalDomainValidationError("ActionPlanDraftV2 contains duplicate route_id")

    action_id_set = set(action_ids)
    adjacency: dict[str, list[str]] = {}
    for action in actions:
        action_id = action["action_id"]
        dependencies = action["depends_on_action_ids"]
        if action_id in dependencies:
            raise CanonicalDomainValidationError("action cannot depend on itself")
        unknown = [dependency for dependency in dependencies if dependency not in action_id_set]
        if unknown:
            raise CanonicalDomainValidationError(
                f"action dependency references unknown actions: {unknown}"
            )
        adjacency[action_id] = list(dependencies)
    _validate_acyclic(adjacency)


def _validate_acyclic(adjacency: Mapping[str, Sequence[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visited:
            return
        if action_id in visiting:
            raise CanonicalDomainValidationError("action dependency cycle detected")
        visiting.add(action_id)
        for dependency in adjacency[action_id]:
            visit(dependency)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in adjacency:
        visit(action_id)


def _evidence_index(evidence_drafts: Sequence[EvidenceDraftV1]) -> dict[str, EvidenceDraftV1]:
    result: dict[str, EvidenceDraftV1] = {}
    for draft in evidence_drafts:
        evidence_id = draft.get("evidence_id")
        resource_handle = draft.get("resource_handle")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise CanonicalDomainValidationError("EvidenceDraftV1.evidence_id is invalid")
        if not isinstance(resource_handle, str) or not resource_handle:
            raise CanonicalDomainValidationError("EvidenceDraftV1.resource_handle is invalid")
        existing = result.get(evidence_id)
        if existing is not None and existing != draft:
            raise CanonicalDomainValidationError("conflicting EvidenceDraftV1.evidence_id")
        result[evidence_id] = draft
    return result


def _validate_meta(value: object, *, path: str) -> StateArtifactMetaV1:
    meta = _mapping(value, path)
    if set(meta) != {"artifact_id", "revision", "based_on"}:
        raise CanonicalDomainValidationError(f"{path} keys are invalid")
    artifact_id = _text(meta["artifact_id"], f"{path}.artifact_id")
    revision = meta["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise CanonicalDomainValidationError(f"{path}.revision is invalid")
    based_on = meta["based_on"]
    if not isinstance(based_on, list):
        raise CanonicalDomainValidationError(f"{path}.based_on is invalid")
    refs = [
        _artifact_ref(raw, path=f"{path}.based_on[{index}]") for index, raw in enumerate(based_on)
    ]
    return {"artifact_id": artifact_id, "revision": revision, "based_on": refs}


def _artifact_ref(value: object, *, path: str) -> StateArtifactRefV1:
    ref = _mapping(value, path)
    if set(ref) != {"artifact_id", "revision"}:
        raise CanonicalDomainValidationError(f"{path} keys are invalid")
    artifact_id = _text(ref["artifact_id"], f"{path}.artifact_id")
    revision = ref["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise CanonicalDomainValidationError(f"{path}.revision is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise CanonicalDomainValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise CanonicalDomainValidationError(f"{path} keys must be strings")
        result[key] = item
    return result


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise CanonicalDomainValidationError(f"{path} must be a non-empty string")
    return value


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise CanonicalDomainValidationError(f"{path} must contain non-empty strings")
    return cast(list[str], list(value))


__all__ = [
    "CanonicalDomainValidationError",
    "CanonicalDomainValidationService",
    "CurrentRunResourceIdentityV1",
    "PolicyOverrideProvenanceDependency",
    "RunScopedResourceIdentityReader",
    "build_domain_validation_output_from_v2",
    "validate_action_plan_draft_v2_for_domain",
]
