"""Work Analysis V2 semantic producer and deterministic finalization.

This module is the Runtime V2 Work Analysis application boundary approved by
Workflow v7.20 plus the Work Analysis V2 Minimum Semantic Authority Amendment.
It deliberately does *not* treat the broader Workflow v7.21 proposal as
canonical authority.

Only ``WorkAnalysisResultV2`` may become the Work Analysis Main-State artifact.
All candidate and aggregation contracts in this module are invocation-local.
The three semantic candidate calls own only:

* ``extract_work_facts`` -> WorkFact candidates,
* ``resolve_relations`` -> relation candidates whose operands are fact ids,
* ``assess_analysis_gaps`` -> semantic gap decision, ambiguity candidates,
  and risk candidates.

Deterministic code owns relation validation, risk validation/merge, action
necessity, artifact lineage, policy receipt references, and all workflow
interrupt/resume metadata.  Non-COMPLETE outcomes never produce a partial
``WorkAnalysisResultV2``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Literal, NotRequired, Protocol, TypedDict, cast

from google_work_agent.application.workflows.handoff_contracts import (
    BlockedSignalV1,
    ConfirmationRequiredV1,
    EvidenceDraftV1,
    RegisteredResumeTargetRefV1,
    RequestIntentV2,
    RetrievalNeedV1,
    RetrievalRequiredV1,
    RetrievalResultV1,
    RouteReconsiderationRequiredV1,
    StateArtifactMetaV1,
    StateArtifactRefV1,
    WorkflowSignalV1,
)
from google_work_agent.application.workflows.state_artifacts_v2 import (
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.ports import OutputSchemaDefinition

ActionNecessityV1 = Literal["REQUIRED", "NOT_REQUIRED"]
_GUARDED_RELATION_TYPES = frozenset({"DUPLICATES", "CONFLICTS_WITH"})
_RISK_SEVERITIES = frozenset({"INFO", "WARNING", "BLOCKING"})

WORK_ANALYSIS_V2_NODE_CHAIN = (
    "extract_work_facts",
    "resolve_relations",
    "validate_relations",
    "assess_analysis_gaps",
    "validate_risks",
    "assemble_analysis",
    "validate",
)

WORK_ANALYSIS_FACTS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="work-analysis-v2-facts-candidate",
    json_schema={
        "type": "object",
        "required": ["fact_candidates"],
        "additionalProperties": False,
        "properties": {
            "fact_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["fact_id", "fact_type", "value", "evidence_refs"],
                    "additionalProperties": False,
                    "properties": {
                        "fact_id": {"type": "string", "minLength": 1},
                        "fact_type": {"type": "string", "minLength": 1},
                        "value": {
                            "oneOf": [
                                {"type": "string", "minLength": 1},
                                {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                },
                            ]
                        },
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            }
        },
    },
)

WORK_ANALYSIS_RELATIONS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="work-analysis-v2-relations-candidate",
    json_schema={
        "type": "object",
        "required": ["relation_candidates"],
        "additionalProperties": False,
        "properties": {
            "relation_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["relation_type", "left_ref", "right_ref", "evidence_refs"],
                    "additionalProperties": False,
                    "properties": {
                        "relation_type": {"type": "string", "minLength": 1},
                        "left_ref": {"type": "string", "minLength": 1},
                        "right_ref": {"type": "string", "minLength": 1},
                        "evidence_refs": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            }
        },
    },
)

WORK_ANALYSIS_GAPS_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="work-analysis-v2-gaps-candidate",
    json_schema={
        "type": "object",
        "required": ["gap_decision", "ambiguity_candidates", "risk_candidates", "evidence_refs"],
        "additionalProperties": False,
        "properties": {
            "gap_decision": {
                "oneOf": [
                    {
                        "type": "object",
                        "required": ["disposition"],
                        "additionalProperties": False,
                        "properties": {"disposition": {"const": "COMPLETE"}},
                    },
                    {
                        "type": "object",
                        "required": ["disposition", "needs"],
                        "additionalProperties": False,
                        "properties": {
                            "disposition": {"const": "NEEDS_MORE_DATA"},
                            "needs": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "required": ["required_information", "reason_codes"],
                                    "additionalProperties": False,
                                    "properties": {
                                        "required_information": {"type": "string", "minLength": 1},
                                        "reason_codes": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {"type": "string", "minLength": 1},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["disposition", "question", "options", "reason_codes"],
                        "additionalProperties": False,
                        "properties": {
                            "disposition": {"const": "NEEDS_CONFIRMATION"},
                            "question": {"type": "string", "minLength": 1},
                            "options": {"type": "array", "items": {"type": "string", "minLength": 1}},
                            "reason_codes": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                    {
                        "type": "object",
                        "required": ["disposition", "reason_codes"],
                        "additionalProperties": False,
                        "properties": {
                            "disposition": {
                                "type": "string",
                                "enum": ["ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"],
                            },
                            "reason_codes": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                ]
            },
            "ambiguity_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["code", "description", "evidence_refs"],
                    "additionalProperties": False,
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "evidence_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    },
                },
            },
            "risk_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["code", "severity", "description", "evidence_refs"],
                    "additionalProperties": False,
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "severity": {"type": "string", "enum": ["INFO", "WARNING", "BLOCKING"]},
                        "description": {"type": "string", "minLength": 1},
                        "evidence_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
                    },
                },
            },
            "evidence_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
        },
    },
)


class WorkRelationLocalCandidate(TypedDict):
    relation_type: str
    left_ref: str
    right_ref: str
    evidence_refs: list[str]


class WorkAnalysisGapCompleteV1(TypedDict):
    disposition: Literal["COMPLETE"]


class WorkAnalysisGapNeedsMoreDataV1(TypedDict):
    disposition: Literal["NEEDS_MORE_DATA"]
    needs: list[RetrievalNeedV1]


class WorkAnalysisGapNeedsConfirmationV1(TypedDict):
    disposition: Literal["NEEDS_CONFIRMATION"]
    question: str
    options: list[str]
    reason_codes: list[str]


class WorkAnalysisGapRouteReconsiderationV1(TypedDict):
    disposition: Literal["ROUTE_RECONSIDERATION_REQUIRED"]
    reason_codes: list[str]


class WorkAnalysisGapBlockedV1(TypedDict):
    disposition: Literal["BLOCKED"]
    reason_codes: list[str]


WorkAnalysisGapDecisionV1 = (
    WorkAnalysisGapCompleteV1
    | WorkAnalysisGapNeedsMoreDataV1
    | WorkAnalysisGapNeedsConfirmationV1
    | WorkAnalysisGapRouteReconsiderationV1
    | WorkAnalysisGapBlockedV1
)


class WorkAnalysisLocalAggregation(TypedDict):
    """Invocation-local aggregation; deterministic fields are not caller inputs."""

    fact_candidates: list[dict[str, object]]
    relation_candidates: list[WorkRelationLocalCandidate]
    relation_validation_ambiguities: list[dict[str, object]]
    ambiguity_candidates: list[dict[str, object]]
    risk_candidates: list[dict[str, object]]
    relation_validation_risks: list[dict[str, object]]
    gap_decision: WorkAnalysisGapDecisionV1
    evidence_refs: list[str]


class WorkAnalysisSemanticInputV1(TypedDict):
    """Approved semantic Product-Prompt root projection for Work Analysis."""

    user_request: str
    request_intent: RequestIntentV2
    evidence: list[EvidenceDraftV1]
    confirmation_response: NotRequired[dict[str, object]]


class RelationValidationOutcomeV1(TypedDict):
    accepted: bool
    validator_codes: list[str]
    ambiguity: NotRequired[WorkAmbiguityV1 | None]
    risk: NotRequired[WorkRiskV1 | None]
    action_necessity: NotRequired[ActionNecessityV1]


class GuardedRelationValidationInputV1(TypedDict):
    relation: WorkRelationLocalCandidate
    left_fact: WorkFactV1
    right_fact: WorkFactV1
    left_resource_handle: str
    right_resource_handle: str


class RelationValidationBundleV1(TypedDict):
    validated_relations: list[WorkRelationV1]
    relation_validation_ambiguities: list[WorkAmbiguityV1]
    relation_validation_risks: list[WorkRiskV1]
    action_necessity: ActionNecessityV1


class WorkAnalysisV2CandidateProvider(Protocol):
    """Three semantic calls; implementations may invoke the approved prompt lane.

    The provider never receives availability or policy-receipt roots and never
    authors deterministic fields.  Prompt source/manifest alignment is a
    separate activation lane.
    """

    def extract_work_facts(self, *, semantic_input: WorkAnalysisSemanticInputV1) -> object: ...

    def resolve_relations(
        self,
        *,
        semantic_input: WorkAnalysisSemanticInputV1,
        work_facts: Sequence[WorkFactV1],
    ) -> object: ...

    def assess_analysis_gaps(
        self,
        *,
        semantic_input: WorkAnalysisSemanticInputV1,
        work_facts: Sequence[WorkFactV1],
        validated_relations: Sequence[WorkRelationV1],
        relation_validation_ambiguities: Sequence[WorkAmbiguityV1],
    ) -> object: ...


# Backward source-name compatibility only.  The old proposal exposed a
# connector-neutral structural identity under this name.  Runtime V2 no longer
# uses that structure: identity is the opaque, current-run Evidence
# ``resource_handle`` string.
NormalizedCurrentResourceIdentityV1 = str


class FactIdentityResolver(Protocol):
    def __call__(self, fact: WorkFactV1) -> Sequence[str]: ...


RelationValidator = Callable[[GuardedRelationValidationInputV1], RelationValidationOutcomeV1]
RetrievalNeedSatisfier = Callable[[Sequence[RetrievalNeedV1]], bool]


class WorkAnalysisV2ValidationError(ValueError):
    pass


def build_current_run_fact_identity_resolver(
    evidence_drafts: Sequence[EvidenceDraftV1],
) -> FactIdentityResolver:
    """Resolve a fact only through current-run Evidence to opaque resource handles."""

    by_id: dict[str, EvidenceDraftV1] = {}
    for index, draft in enumerate(evidence_drafts):
        evidence_id = _text(draft.get("evidence_id"), f"evidence_drafts[{index}].evidence_id")
        handle = _text(draft.get("resource_handle"), f"evidence_drafts[{index}].resource_handle")
        normalized = cast(EvidenceDraftV1, dict(draft))
        existing = by_id.get(evidence_id)
        if existing is not None and existing != normalized:
            raise WorkAnalysisV2ValidationError("conflicting current-run evidence id")
        if not handle:
            raise WorkAnalysisV2ValidationError("current-run evidence resource_handle is required")
        by_id[evidence_id] = normalized

    def resolve(fact: WorkFactV1) -> Sequence[str]:
        handles: list[str] = []
        seen: set[str] = set()
        for evidence_ref in fact["evidence_refs"]:
            draft = by_id.get(evidence_ref)
            if draft is None:
                return []
            handle = draft["resource_handle"]
            if handle not in seen:
                seen.add(handle)
                handles.append(handle)
        return handles

    return resolve


def validate_work_analysis_gap_decision_v1(value: object) -> WorkAnalysisGapDecisionV1:
    root = _mapping(value, "$.gap_decision")
    disposition = _text(root.get("disposition"), "$.gap_decision.disposition")
    if disposition == "COMPLETE":
        _exact(root, {"disposition"}, "$.gap_decision")
        return cast(WorkAnalysisGapCompleteV1, dict(root))
    if disposition == "NEEDS_MORE_DATA":
        _exact(root, {"disposition", "needs"}, "$.gap_decision")
        raw_needs = _list(root["needs"], "$.gap_decision.needs")
        if not raw_needs:
            raise WorkAnalysisV2ValidationError("NEEDS_MORE_DATA requires at least one RetrievalNeedV1")
        return {
            "disposition": "NEEDS_MORE_DATA",
            "needs": [_retrieval_need(v, f"$.gap_decision.needs[{i}]") for i, v in enumerate(raw_needs)],
        }
    if disposition == "NEEDS_CONFIRMATION":
        _exact(root, {"disposition", "question", "options", "reason_codes"}, "$.gap_decision")
        return {
            "disposition": "NEEDS_CONFIRMATION",
            "question": _text(root["question"], "$.gap_decision.question"),
            "options": _strings(root["options"], "$.gap_decision.options"),
            "reason_codes": _non_empty_strings(root["reason_codes"], "$.gap_decision.reason_codes"),
        }
    if disposition in {"ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"}:
        _exact(root, {"disposition", "reason_codes"}, "$.gap_decision")
        reasons = _non_empty_strings(root["reason_codes"], "$.gap_decision.reason_codes")
        if disposition == "ROUTE_RECONSIDERATION_REQUIRED":
            return {"disposition": "ROUTE_RECONSIDERATION_REQUIRED", "reason_codes": reasons}
        return {"disposition": "BLOCKED", "reason_codes": reasons}
    raise WorkAnalysisV2ValidationError("$.gap_decision.disposition is invalid")


def project_work_analysis_retrieval_required_v1(
    decision: WorkAnalysisGapDecisionV1,
) -> RetrievalRequiredV1:
    decision = validate_work_analysis_gap_decision_v1(decision)
    if decision["disposition"] != "NEEDS_MORE_DATA":
        raise WorkAnalysisV2ValidationError("retrieval projection requires NEEDS_MORE_DATA")
    needs = [dict(need) for need in decision["needs"]]
    reason_codes = _ordered_unique(
        code for need in needs for code in cast(list[str], need["reason_codes"])
    )
    return {"kind": "RETRIEVAL_REQUIRED", "reason_codes": reason_codes, "needs": needs}


def project_work_analysis_confirmation_required_v1(
    decision: WorkAnalysisGapDecisionV1,
    *,
    interrupt_id: str,
    resume_target: RegisteredResumeTargetRefV1,
) -> ConfirmationRequiredV1:
    decision = validate_work_analysis_gap_decision_v1(decision)
    if decision["disposition"] != "NEEDS_CONFIRMATION":
        raise WorkAnalysisV2ValidationError("confirmation projection requires NEEDS_CONFIRMATION")
    return {
        "kind": "CONFIRMATION_REQUIRED",
        "interrupt_id": _text(interrupt_id, "interrupt_id"),
        "owner_subgraph": "WORK_ANALYSIS",
        "resume_target": _resume_target(resume_target),
        "question": decision["question"],
        "options": list(decision["options"]),
    }


def project_work_analysis_noncomplete_signal_v1(
    decision: WorkAnalysisGapDecisionV1,
) -> RouteReconsiderationRequiredV1 | BlockedSignalV1:
    decision = validate_work_analysis_gap_decision_v1(decision)
    if decision["disposition"] == "ROUTE_RECONSIDERATION_REQUIRED":
        return {"kind": "ROUTE_RECONSIDERATION_REQUIRED", "reason_codes": list(decision["reason_codes"])}
    if decision["disposition"] == "BLOCKED":
        return {"kind": "BLOCKED", "reason_codes": list(decision["reason_codes"])}
    raise WorkAnalysisV2ValidationError("reason signal projection requires route reconsideration or block")


def validate_work_analysis_local_aggregation(
    value: object,
    *,
    allowed_evidence_refs: set[str],
) -> WorkAnalysisLocalAggregation:
    root = _mapping(value, "$")
    _exact(
        root,
        {
            "fact_candidates",
            "relation_candidates",
            "relation_validation_ambiguities",
            "ambiguity_candidates",
            "risk_candidates",
            "relation_validation_risks",
            "gap_decision",
            "evidence_refs",
        },
        "$",
    )
    top = _evidence_refs(root["evidence_refs"], "$.evidence_refs", allowed_evidence_refs)
    top_set = set(top)
    facts = _facts(root["fact_candidates"], allowed_evidence_refs, top_set)
    fact_ids = {fact["fact_id"] for fact in facts}
    relations = _relations(root["relation_candidates"], allowed_evidence_refs, top_set, fact_ids)
    return {
        "fact_candidates": [cast(dict[str, object], fact) for fact in facts],
        "relation_candidates": relations,
        "relation_validation_ambiguities": [
            cast(dict[str, object], item)
            for item in _ambiguities(
                root["relation_validation_ambiguities"],
                "$.relation_validation_ambiguities",
                allowed_evidence_refs,
                top_set,
            )
        ],
        "ambiguity_candidates": [
            cast(dict[str, object], item)
            for item in _ambiguities(
                root["ambiguity_candidates"],
                "$.ambiguity_candidates",
                allowed_evidence_refs,
                top_set,
            )
        ],
        "risk_candidates": [
            cast(dict[str, object], item)
            for item in _risk_sequence(root["risk_candidates"], "$.risk_candidates", allowed_evidence_refs, top_set)
        ],
        "relation_validation_risks": [
            cast(dict[str, object], item)
            for item in _risk_sequence(
                root["relation_validation_risks"],
                "$.relation_validation_risks",
                allowed_evidence_refs,
                top_set,
            )
        ],
        "gap_decision": validate_work_analysis_gap_decision_v1(root["gap_decision"]),
        "evidence_refs": top,
    }


def validate_and_merge_work_analysis_risks(
    *,
    risk_candidates: Sequence[Mapping[str, object]],
    relation_validation_risks: Sequence[Mapping[str, object]],
    allowed_evidence_refs: set[str],
) -> list[WorkRiskV1]:
    """Validate and collapse only byte-semantic-equivalent normalized risks.

    Risk code alone is never a duplicate key.  Same-code risks with a different
    severity, description, or ordered-unique evidence reference payload remain
    separate official risks.
    """

    seen: set[tuple[str, str, str, tuple[str, ...]]] = set()
    ordered: list[WorkRiskV1] = []
    for index, raw in enumerate([*risk_candidates, *relation_validation_risks]):
        risk = _risk(raw, f"$.risk_merge[{index}]", allowed_evidence_refs)
        identity = (
            risk["code"],
            risk["severity"],
            risk["description"],
            tuple(risk["evidence_refs"]),
        )
        if identity in seen:
            continue
        seen.add(identity)
        ordered.append(risk)
    return ordered


def validate_work_analysis_relations(
    *,
    work_facts: Sequence[WorkFactV1],
    relation_candidates: Sequence[WorkRelationLocalCandidate],
    allowed_evidence_refs: set[str],
    relation_validator: RelationValidator | None,
    fact_identity_resolver: FactIdentityResolver | None,
) -> RelationValidationBundleV1:
    """Deterministically promote relation candidates after current-run identity checks."""

    facts_by_id = {fact["fact_id"]: fact for fact in work_facts}
    relations: list[WorkRelationV1] = []
    ambiguities: list[WorkAmbiguityV1] = []
    risks: list[WorkRiskV1] = []
    action_necessity: ActionNecessityV1 = "REQUIRED"

    for index, raw_relation in enumerate(relation_candidates):
        relation = _relation(raw_relation, f"$.relation_candidates[{index}]", allowed_evidence_refs)
        left_fact = facts_by_id.get(relation["left_ref"])
        right_fact = facts_by_id.get(relation["right_ref"])
        if left_fact is None or right_fact is None:
            raise WorkAnalysisV2ValidationError("relation operands must reference same-invocation WorkFactV1.fact_id")
        if relation["relation_type"] not in _GUARDED_RELATION_TYPES:
            relations.append({**relation, "validator_codes": []})
            continue
        if relation_validator is None or fact_identity_resolver is None:
            raise WorkAnalysisV2ValidationError(
                f"{relation['relation_type']} requires deterministic relation and current-run evidence identity validation"
            )
        left_handles = _ordered_unique(fact_identity_resolver(left_fact))
        right_handles = _ordered_unique(fact_identity_resolver(right_fact))
        if len(left_handles) != 1 or len(right_handles) != 1:
            ambiguities.append(
                {
                    "code": "RELATION_OPERAND_IDENTITY_UNRESOLVED",
                    "description": "guarded relation operand did not resolve to exactly one current-run evidence resource identity",
                    "evidence_refs": _ordered_unique(
                        [*left_fact["evidence_refs"], *right_fact["evidence_refs"], *relation["evidence_refs"]]
                    ),
                }
            )
            continue
        outcome = relation_validator(
            {
                "relation": relation,
                "left_fact": left_fact,
                "right_fact": right_fact,
                "left_resource_handle": left_handles[0],
                "right_resource_handle": right_handles[0],
            }
        )
        codes = _non_empty_strings(outcome.get("validator_codes"), "$.relation_validation.validator_codes")
        if outcome.get("accepted") is True:
            relations.append({**relation, "validator_codes": codes})
        elif outcome.get("ambiguity") is not None:
            ambiguities.append(
                _ambiguity(
                    cast(Mapping[str, object], outcome["ambiguity"]),
                    "$.relation_validation.ambiguity",
                    allowed_evidence_refs,
                )
            )
        if outcome.get("risk") is not None:
            risks.append(
                _risk(
                    cast(Mapping[str, object], outcome["risk"]),
                    "$.relation_validation.risk",
                    allowed_evidence_refs,
                )
            )
        necessity = outcome.get("action_necessity")
        if necessity not in {None, "REQUIRED", "NOT_REQUIRED"}:
            raise WorkAnalysisV2ValidationError("invalid action_necessity")
        if necessity == "NOT_REQUIRED":
            action_necessity = "NOT_REQUIRED"

    return {
        "validated_relations": relations,
        "relation_validation_ambiguities": ambiguities,
        "relation_validation_risks": risks,
        "action_necessity": action_necessity,
    }


def materialize_complete_work_analysis_result_v2(
    local: WorkAnalysisLocalAggregation,
    *,
    meta: StateArtifactMetaV1,
    allowed_evidence_refs: set[str],
    policy_confirmation_receipt_refs: Sequence[StateArtifactRefV1],
    relation_validator: RelationValidator | None = None,
    fact_identity_resolver: FactIdentityResolver | None = None,
) -> WorkAnalysisResultV2:
    """Strict COMPLETE helper retained for deterministic callers and tests."""

    local = validate_work_analysis_local_aggregation(local, allowed_evidence_refs=allowed_evidence_refs)
    if local["gap_decision"]["disposition"] != "COMPLETE":
        raise WorkAnalysisV2ValidationError("COMPLETE artifact requires gap_decision COMPLETE")
    facts = [
        _fact(cast(Mapping[str, object], value), f"$.fact_candidates[{index}]", allowed_evidence_refs)
        for index, value in enumerate(local["fact_candidates"])
    ]
    relation_bundle = validate_work_analysis_relations(
        work_facts=facts,
        relation_candidates=local["relation_candidates"],
        allowed_evidence_refs=allowed_evidence_refs,
        relation_validator=relation_validator,
        fact_identity_resolver=fact_identity_resolver,
    )
    risks = validate_and_merge_work_analysis_risks(
        risk_candidates=cast(Sequence[Mapping[str, object]], local["risk_candidates"]),
        relation_validation_risks=[
            *cast(Sequence[Mapping[str, object]], local["relation_validation_risks"]),
            *cast(Sequence[Mapping[str, object]], relation_bundle["relation_validation_risks"]),
        ],
        allowed_evidence_refs=allowed_evidence_refs,
    )
    if any(risk["severity"] == "BLOCKING" for risk in risks):
        raise WorkAnalysisV2ValidationError(
            "unresolved BLOCKING risk requires BLOCKED workflow signal; COMPLETE artifact is forbidden"
        )
    ambiguities = [
        _ambiguity(cast(Mapping[str, object], value), f"$.relation_validation_ambiguities[{index}]", allowed_evidence_refs)
        for index, value in enumerate(local["relation_validation_ambiguities"])
    ]
    ambiguities.extend(relation_bundle["relation_validation_ambiguities"])
    ambiguities.extend(
        _ambiguity(cast(Mapping[str, object], value), f"$.ambiguity_candidates[{index}]", allowed_evidence_refs)
        for index, value in enumerate(local["ambiguity_candidates"])
    )
    return _assemble_work_analysis_result_v2(
        facts=facts,
        relations=relation_bundle["validated_relations"],
        ambiguities=ambiguities,
        risks=risks,
        evidence_refs=local["evidence_refs"],
        action_necessity=relation_bundle["action_necessity"],
        meta=meta,
        allowed_evidence_refs=allowed_evidence_refs,
        policy_confirmation_receipt_refs=policy_confirmation_receipt_refs,
    )


class WorkAnalysisV2NodeChain:
    """Checkpoint-A producer implementing the approved seven-node semantic chain."""

    def __init__(
        self,
        *,
        candidate_provider: WorkAnalysisV2CandidateProvider,
        relation_validator: RelationValidator | None = None,
        retrieval_need_satisfier: RetrievalNeedSatisfier | None = None,
    ) -> None:
        self._candidate_provider = candidate_provider
        self._relation_validator = relation_validator
        self._retrieval_need_satisfier = retrieval_need_satisfier

    def run(
        self,
        *,
        user_request: str,
        request_intent: RequestIntentV2,
        retrieval_result: RetrievalResultV1,
        evidence_drafts: Sequence[EvidenceDraftV1],
        meta: StateArtifactMetaV1,
        policy_confirmation_receipt_refs: Sequence[StateArtifactRefV1],
        confirmation_response: Mapping[str, object] | None = None,
        interrupt_id: str | None = None,
        resume_target: RegisteredResumeTargetRefV1 | None = None,
    ) -> WorkAnalysisResultV2 | WorkflowSignalV1:
        allowed_evidence_refs = set(retrieval_result["evidence_refs"])
        evidence = _validate_current_run_evidence(
            evidence_drafts,
            expected_refs=retrieval_result["evidence_refs"],
        )
        semantic_input: WorkAnalysisSemanticInputV1 = {
            "user_request": _text(user_request, "user_request"),
            "request_intent": request_intent,
            "evidence": evidence,
        }
        if confirmation_response is not None:
            semantic_input["confirmation_response"] = dict(confirmation_response)

        # 1. extract_work_facts [LLM candidate]
        facts_candidate = _mapping(
            self._candidate_provider.extract_work_facts(semantic_input=semantic_input),
            "$.extract_work_facts",
        )
        _exact(facts_candidate, {"fact_candidates"}, "$.extract_work_facts")
        facts = _facts(facts_candidate["fact_candidates"], allowed_evidence_refs, allowed_evidence_refs)

        # 2. resolve_relations [LLM candidate]
        relations_candidate = _mapping(
            self._candidate_provider.resolve_relations(
                semantic_input=semantic_input,
                work_facts=facts,
            ),
            "$.resolve_relations",
        )
        _exact(relations_candidate, {"relation_candidates"}, "$.resolve_relations")
        relation_candidates = _relations(
            relations_candidate["relation_candidates"],
            allowed_evidence_refs,
            allowed_evidence_refs,
            {fact["fact_id"] for fact in facts},
        )

        # 3. validate_relations [deterministic]
        relation_bundle = validate_work_analysis_relations(
            work_facts=facts,
            relation_candidates=relation_candidates,
            allowed_evidence_refs=allowed_evidence_refs,
            relation_validator=self._relation_validator,
            fact_identity_resolver=build_current_run_fact_identity_resolver(evidence),
        )

        # 4. assess_analysis_gaps [LLM semantic candidate]
        gaps_candidate = _mapping(
            self._candidate_provider.assess_analysis_gaps(
                semantic_input=semantic_input,
                work_facts=facts,
                validated_relations=relation_bundle["validated_relations"],
                relation_validation_ambiguities=relation_bundle["relation_validation_ambiguities"],
            ),
            "$.assess_analysis_gaps",
        )
        _exact(
            gaps_candidate,
            {"gap_decision", "ambiguity_candidates", "risk_candidates", "evidence_refs"},
            "$.assess_analysis_gaps",
        )
        gap_decision = validate_work_analysis_gap_decision_v1(gaps_candidate["gap_decision"])
        top_evidence = _evidence_refs(
            gaps_candidate["evidence_refs"],
            "$.assess_analysis_gaps.evidence_refs",
            allowed_evidence_refs,
        )
        top_set = set(top_evidence)
        ambiguity_candidates = _ambiguities(
            gaps_candidate["ambiguity_candidates"],
            "$.assess_analysis_gaps.ambiguity_candidates",
            allowed_evidence_refs,
            top_set,
        )

        # 5. validate_risks [deterministic]
        risk_candidates = _risk_sequence(
            gaps_candidate["risk_candidates"],
            "$.assess_analysis_gaps.risk_candidates",
            allowed_evidence_refs,
            top_set,
        )
        risks = validate_and_merge_work_analysis_risks(
            risk_candidates=cast(Sequence[Mapping[str, object]], risk_candidates),
            relation_validation_risks=cast(
                Sequence[Mapping[str, object]], relation_bundle["relation_validation_risks"]
            ),
            allowed_evidence_refs=allowed_evidence_refs,
        )
        blocking = [risk for risk in risks if risk["severity"] == "BLOCKING"]
        if blocking:
            return {
                "kind": "BLOCKED",
                "reason_codes": _ordered_unique(risk["code"] for risk in blocking),
            }

        # Non-COMPLETE dispositions project to typed workflow signals and never
        # proceed to assembly / Parent-State artifact merge.
        if gap_decision["disposition"] == "NEEDS_MORE_DATA":
            needs = gap_decision["needs"]
            if self._retrieval_need_satisfier is not None and not self._retrieval_need_satisfier(needs):
                return {
                    "kind": "ROUTE_RECONSIDERATION_REQUIRED",
                    "reason_codes": _ordered_unique(
                        code for need in needs for code in need["reason_codes"]
                    ),
                }
            return project_work_analysis_retrieval_required_v1(gap_decision)
        if gap_decision["disposition"] == "NEEDS_CONFIRMATION":
            if interrupt_id is None or resume_target is None:
                raise WorkAnalysisV2ValidationError(
                    "Application-owned interrupt_id and resume_target are required for NEEDS_CONFIRMATION"
                )
            return project_work_analysis_confirmation_required_v1(
                gap_decision,
                interrupt_id=interrupt_id,
                resume_target=resume_target,
            )
        if gap_decision["disposition"] in {"ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"}:
            return project_work_analysis_noncomplete_signal_v1(gap_decision)

        # 6. assemble_analysis [deterministic]
        ambiguities = [
            *relation_bundle["relation_validation_ambiguities"],
            *ambiguity_candidates,
        ]
        result = _assemble_work_analysis_result_v2(
            facts=facts,
            relations=relation_bundle["validated_relations"],
            ambiguities=ambiguities,
            risks=risks,
            evidence_refs=top_evidence,
            action_necessity=relation_bundle["action_necessity"],
            meta=meta,
            allowed_evidence_refs=allowed_evidence_refs,
            policy_confirmation_receipt_refs=policy_confirmation_receipt_refs,
        )

        # 7. validate [deterministic]
        return validate_complete_work_analysis_result_v2(
            result,
            allowed_evidence_refs=allowed_evidence_refs,
        )


def validate_complete_work_analysis_result_v2(
    value: object,
    *,
    allowed_evidence_refs: set[str],
) -> WorkAnalysisResultV2:
    root = _mapping(value, "$.work_analysis_result_v2")
    _exact(
        root,
        {
            "schema_version",
            "meta",
            "work_facts",
            "relations",
            "ambiguities",
            "risks",
            "evidence_refs",
            "policy_confirmation_receipt_refs",
            "action_necessity",
        },
        "$.work_analysis_result_v2",
    )
    if root["schema_version"] != 2:
        raise WorkAnalysisV2ValidationError("WorkAnalysisResultV2.schema_version must be 2")
    top = _evidence_refs(root["evidence_refs"], "$.work_analysis_result_v2.evidence_refs", allowed_evidence_refs)
    facts = _facts(root["work_facts"], allowed_evidence_refs, set(top))
    fact_ids = {fact["fact_id"] for fact in facts}
    relations: list[WorkRelationV1] = []
    for index, raw in enumerate(_list(root["relations"], "$.work_analysis_result_v2.relations")):
        item = _mapping(raw, f"$.work_analysis_result_v2.relations[{index}]")
        _exact(item, {"relation_type", "left_ref", "right_ref", "evidence_refs", "validator_codes"}, f"$.work_analysis_result_v2.relations[{index}]")
        relation = _relation(item, f"$.work_analysis_result_v2.relations[{index}]", allowed_evidence_refs, allow_validator_codes=True)
        if relation["left_ref"] not in fact_ids or relation["right_ref"] not in fact_ids:
            raise WorkAnalysisV2ValidationError("official relation operand is not a same-invocation fact id")
        relations.append(
            {
                **relation,
                "validator_codes": _strings(item["validator_codes"], f"$.work_analysis_result_v2.relations[{index}].validator_codes"),
            }
        )
    risks = _risk_sequence(root["risks"], "$.work_analysis_result_v2.risks", allowed_evidence_refs, set(top))
    if any(risk["severity"] == "BLOCKING" for risk in risks):
        raise WorkAnalysisV2ValidationError("WorkAnalysisResultV2 may not contain unresolved BLOCKING risk")
    action_necessity = root["action_necessity"]
    if action_necessity not in {"REQUIRED", "NOT_REQUIRED"}:
        raise WorkAnalysisV2ValidationError("invalid action_necessity")
    return {
        "schema_version": 2,
        "meta": _meta(root["meta"]),
        "work_facts": facts,
        "relations": relations,
        "ambiguities": _ambiguities(root["ambiguities"], "$.work_analysis_result_v2.ambiguities", allowed_evidence_refs, set(top)),
        "risks": risks,
        "evidence_refs": top,
        "policy_confirmation_receipt_refs": [
            _artifact_ref(item, f"$.work_analysis_result_v2.policy_confirmation_receipt_refs[{index}]")
            for index, item in enumerate(_list(root["policy_confirmation_receipt_refs"], "$.work_analysis_result_v2.policy_confirmation_receipt_refs"))
        ],
        "action_necessity": cast(ActionNecessityV1, action_necessity),
    }


def _assemble_work_analysis_result_v2(
    *,
    facts: Sequence[WorkFactV1],
    relations: Sequence[WorkRelationV1],
    ambiguities: Sequence[WorkAmbiguityV1],
    risks: Sequence[WorkRiskV1],
    evidence_refs: Sequence[str],
    action_necessity: ActionNecessityV1,
    meta: StateArtifactMetaV1,
    allowed_evidence_refs: set[str],
    policy_confirmation_receipt_refs: Sequence[StateArtifactRefV1],
) -> WorkAnalysisResultV2:
    if any(risk["severity"] == "BLOCKING" for risk in risks):
        raise WorkAnalysisV2ValidationError("cannot assemble COMPLETE artifact with BLOCKING risk")
    return {
        "schema_version": 2,
        "meta": _meta(meta),
        "work_facts": [dict(fact) for fact in facts],
        "relations": [dict(relation) for relation in relations],
        "ambiguities": [dict(ambiguity) for ambiguity in ambiguities],
        "risks": [dict(risk) for risk in risks],
        "evidence_refs": _evidence_refs(list(evidence_refs), "$.evidence_refs", allowed_evidence_refs),
        "policy_confirmation_receipt_refs": [
            _artifact_ref(value, f"$.policy_confirmation_receipt_refs[{index}]")
            for index, value in enumerate(policy_confirmation_receipt_refs)
        ],
        "action_necessity": action_necessity,
    }


def _validate_current_run_evidence(
    evidence_drafts: Sequence[EvidenceDraftV1],
    *,
    expected_refs: Sequence[str],
) -> list[EvidenceDraftV1]:
    expected = list(expected_refs)
    by_id: dict[str, EvidenceDraftV1] = {}
    for index, raw in enumerate(evidence_drafts):
        item = cast(EvidenceDraftV1, dict(raw))
        evidence_id = _text(item.get("evidence_id"), f"evidence_drafts[{index}].evidence_id")
        if evidence_id in by_id and by_id[evidence_id] != item:
            raise WorkAnalysisV2ValidationError("conflicting current-run evidence id")
        by_id[evidence_id] = item
    if set(by_id) != set(expected):
        raise WorkAnalysisV2ValidationError("current-run evidence projection must exactly cover RetrievalResultV1.evidence_refs")
    return [by_id[evidence_ref] for evidence_ref in expected]


def _facts(value: object, allowed: set[str], top: set[str]) -> list[WorkFactV1]:
    result: list[WorkFactV1] = []
    seen: set[str] = set()
    for index, raw in enumerate(_list(value, "$.fact_candidates")):
        fact = _fact(_mapping(raw, f"$.fact_candidates[{index}]"), f"$.fact_candidates[{index}]", allowed)
        if fact["fact_id"] in seen:
            raise WorkAnalysisV2ValidationError(f"duplicate WorkFactV1.fact_id: {fact['fact_id']}")
        seen.add(fact["fact_id"])
        _nested(fact["evidence_refs"], top, f"$.fact_candidates[{index}].evidence_refs")
        result.append(fact)
    return result


def _relations(
    value: object,
    allowed: set[str],
    top: set[str],
    fact_ids: set[str],
) -> list[WorkRelationLocalCandidate]:
    result: list[WorkRelationLocalCandidate] = []
    for index, raw in enumerate(_list(value, "$.relation_candidates")):
        path = f"$.relation_candidates[{index}]"
        relation = _relation(raw, path, allowed)
        _nested(relation["evidence_refs"], top, f"{path}.evidence_refs")
        if relation["left_ref"] not in fact_ids or relation["right_ref"] not in fact_ids:
            raise WorkAnalysisV2ValidationError(f"{path} operands must reference same-invocation WorkFactV1.fact_id")
        result.append(relation)
    return result


def _fact(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkFactV1:
    _exact(value, {"fact_id", "fact_type", "value", "evidence_refs"}, path)
    raw_value = value["value"]
    fact_value: str | list[str] = (
        _text(raw_value, f"{path}.value")
        if isinstance(raw_value, str)
        else _strings(raw_value, f"{path}.value")
    )
    return {
        "fact_id": _text(value["fact_id"], f"{path}.fact_id"),
        "fact_type": _text(value["fact_type"], f"{path}.fact_type"),
        "value": fact_value,
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _relation(
    value: object,
    path: str,
    allowed: set[str],
    *,
    allow_validator_codes: bool = False,
) -> WorkRelationLocalCandidate:
    item = _mapping(value, path)
    expected = {"relation_type", "left_ref", "right_ref", "evidence_refs"}
    if allow_validator_codes:
        expected.add("validator_codes")
    _exact(item, expected, path)
    refs = _evidence_refs(item["evidence_refs"], f"{path}.evidence_refs", allowed)
    if not refs:
        raise WorkAnalysisV2ValidationError(f"{path}.evidence_refs must not be empty")
    return {
        "relation_type": _text(item["relation_type"], f"{path}.relation_type"),
        "left_ref": _text(item["left_ref"], f"{path}.left_ref"),
        "right_ref": _text(item["right_ref"], f"{path}.right_ref"),
        "evidence_refs": refs,
    }


def _retrieval_need(value: object, path: str) -> RetrievalNeedV1:
    item = _mapping(value, path)
    _exact(item, {"required_information", "reason_codes"}, path)
    return {
        "required_information": _text(item["required_information"], f"{path}.required_information"),
        "reason_codes": _non_empty_strings(item["reason_codes"], f"{path}.reason_codes"),
    }


def _resume_target(value: object) -> RegisteredResumeTargetRefV1:
    item = _mapping(value, "resume_target")
    _exact(item, {"subgraph_id", "node_id", "graph_version"}, "resume_target")
    if item["subgraph_id"] != "WORK_ANALYSIS":
        raise WorkAnalysisV2ValidationError("Work Analysis confirmation must resume WORK_ANALYSIS")
    return cast(
        RegisteredResumeTargetRefV1,
        {
            "subgraph_id": "WORK_ANALYSIS",
            "node_id": _text(item["node_id"], "resume_target.node_id"),
            "graph_version": _text(item["graph_version"], "resume_target.graph_version"),
        },
    )


def _ambiguities(value: object, path: str, allowed: set[str], top: set[str]) -> list[WorkAmbiguityV1]:
    result: list[WorkAmbiguityV1] = []
    for index, raw in enumerate(_list(value, path)):
        item_path = f"{path}[{index}]"
        ambiguity = _ambiguity(_mapping(raw, item_path), item_path, allowed)
        _nested(ambiguity["evidence_refs"], top, f"{item_path}.evidence_refs")
        result.append(ambiguity)
    return result


def _ambiguity(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkAmbiguityV1:
    _exact(value, {"code", "description", "evidence_refs"}, path)
    return {
        "code": _text(value["code"], f"{path}.code"),
        "description": _text(value["description"], f"{path}.description"),
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _risk_sequence(value: object, path: str, allowed: set[str], top: set[str]) -> list[WorkRiskV1]:
    result: list[WorkRiskV1] = []
    for index, raw in enumerate(_list(value, path)):
        item_path = f"{path}[{index}]"
        risk = _risk(_mapping(raw, item_path), item_path, allowed)
        _nested(risk["evidence_refs"], top, f"{item_path}.evidence_refs")
        result.append(risk)
    return result


def _risk(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkRiskV1:
    _exact(value, {"code", "severity", "description", "evidence_refs"}, path)
    severity = _text(value["severity"], f"{path}.severity")
    if severity not in _RISK_SEVERITIES:
        raise WorkAnalysisV2ValidationError(f"{path}.severity is invalid")
    refs = _ordered_unique(_strings(value["evidence_refs"], f"{path}.evidence_refs"))
    unknown = [ref for ref in refs if ref not in allowed]
    if unknown:
        raise WorkAnalysisV2ValidationError(f"{path}.evidence_refs contains unknown/current-run-invalid refs: {unknown}")
    return {
        "code": _text(value["code"], f"{path}.code"),
        "severity": cast(Literal["INFO", "WARNING", "BLOCKING"], severity),
        "description": _text(value["description"], f"{path}.description"),
        "evidence_refs": refs,
    }


def _meta(value: object) -> StateArtifactMetaV1:
    item = _mapping(value, "$.meta")
    _exact(item, {"artifact_id", "revision", "based_on"}, "$.meta")
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError("$.meta.revision is invalid")
    return {
        "artifact_id": _text(item["artifact_id"], "$.meta.artifact_id"),
        "revision": revision,
        "based_on": [
            _artifact_ref(ref, f"$.meta.based_on[{index}]")
            for index, ref in enumerate(_list(item["based_on"], "$.meta.based_on"))
        ],
    }


def _artifact_ref(value: object, path: str) -> StateArtifactRefV1:
    item = _mapping(value, path)
    _exact(item, {"artifact_id", "revision"}, path)
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError(f"{path}.revision is invalid")
    return {"artifact_id": _text(item["artifact_id"], f"{path}.artifact_id"), "revision": revision}


def _evidence_refs(value: object, path: str, allowed: set[str]) -> list[str]:
    refs = _strings(value, path)
    if len(refs) != len(set(refs)):
        raise WorkAnalysisV2ValidationError(f"{path} contains duplicates")
    unknown = [ref for ref in refs if ref not in allowed]
    if unknown:
        raise WorkAnalysisV2ValidationError(f"{path} contains unknown/current-run-invalid evidence refs: {unknown}")
    return refs


def _nested(refs: Sequence[str], top: set[str], path: str) -> None:
    missing = [ref for ref in refs if ref not in top]
    if missing:
        raise WorkAnalysisV2ValidationError(f"{path} must also be listed in top-level evidence_refs: {missing}")


def _ordered_unique(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        value = _text(raw, "ordered_unique")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise WorkAnalysisV2ValidationError(f"{path} must be an object with string keys")
    return dict(value)


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkAnalysisV2ValidationError(f"{path} must be an array")
    return list(value)


def _strings(value: object, path: str) -> list[str]:
    return [_text(item, f"{path}[{index}]") for index, item in enumerate(_list(value, path))]


def _non_empty_strings(value: object, path: str) -> list[str]:
    items = _strings(value, path)
    if not items:
        raise WorkAnalysisV2ValidationError(f"{path} must not be empty")
    return items


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkAnalysisV2ValidationError(f"{path} must be a non-empty string")
    return value


def _exact(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise WorkAnalysisV2ValidationError(f"{path} keys are invalid: expected {sorted(expected)}, got {sorted(value)}")


__all__ = [
    "ActionNecessityV1",
    "FactIdentityResolver",
    "GuardedRelationValidationInputV1",
    "NormalizedCurrentResourceIdentityV1",
    "RelationValidationBundleV1",
    "RelationValidationOutcomeV1",
    "RelationValidator",
    "WORK_ANALYSIS_FACTS_OUTPUT_SCHEMA",
    "WORK_ANALYSIS_GAPS_OUTPUT_SCHEMA",
    "WORK_ANALYSIS_RELATIONS_OUTPUT_SCHEMA",
    "WORK_ANALYSIS_V2_NODE_CHAIN",
    "WorkAnalysisGapDecisionV1",
    "WorkAnalysisLocalAggregation",
    "WorkAnalysisSemanticInputV1",
    "WorkAnalysisV2CandidateProvider",
    "WorkAnalysisV2NodeChain",
    "WorkAnalysisV2ValidationError",
    "WorkRelationLocalCandidate",
    "build_current_run_fact_identity_resolver",
    "materialize_complete_work_analysis_result_v2",
    "project_work_analysis_confirmation_required_v1",
    "project_work_analysis_noncomplete_signal_v1",
    "project_work_analysis_retrieval_required_v1",
    "validate_and_merge_work_analysis_risks",
    "validate_complete_work_analysis_result_v2",
    "validate_work_analysis_gap_decision_v1",
    "validate_work_analysis_local_aggregation",
    "validate_work_analysis_relations",
]
